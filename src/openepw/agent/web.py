"""Agent sessions hosted for the web chat (P4): turns in worker threads, ownership, limits, spend.

No web framework here: ``openepw.api.agent_routes`` maps HTTP onto ``AgentHost``. Each turn runs
in a worker thread with its own event loop, MCP client (in-memory transport) and policy, so a
blocking tool only blocks its own turn. One input runs at a time per session.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Literal

from pydantic import model_validator

from ..models import Model
from .guided import GuidedPolicy
from .interactions import Answer
from .mcp_port import ApprovalBook, InProcessMCP
from .model_port import ModelPort, ModelReply, ModelUnavailable
from .moderation import ModerationPort
from .policy_config import SecurityPolicy, default_policy
from .policy_model import ModelPolicy
from .session import TERMINAL, AgentSession, Policy
from .slots import parts
from .store import SessionStore

logger = logging.getLogger("openepw.agent.web")
Action = Callable[[AgentSession], Awaitable[Any]]
RECENT_EVENTS = 300


class WebRefusal(Exception):
    """An input or session the host refuses: ``status`` is the HTTP status the routes return."""

    def __init__(self, code: str, message: str, status: int = 429):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class WebInput(Model):
    """One input from the web chat; ``answer`` answers the open form."""

    type: Literal["text", "answer", "back", "new", "mode", "request"]
    text: str | None = None
    answer: Answer | None = None
    mode: Literal["agent", "guided"] | None = None

    @model_validator(mode="after")
    def complete(self) -> WebInput:
        needed = {"text": self.text, "answer": self.answer, "mode": self.mode}.get(self.type, True)
        if needed is None:
            raise ValueError(f"A {self.type} input needs its {self.type} field")
        return self


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class WebStore:
    """Who owns each web session, recent inputs per person, model spend and started jobs."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS owners (session_id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS hits (owner TEXT NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS hits_owner ON hits (owner, kind, at);
    CREATE TABLE IF NOT EXISTS spend (owner TEXT NOT NULL, session_id TEXT NOT NULL, day TEXT NOT NULL,
        usd REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS spend_day ON spend (day, owner);
    CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, session_id TEXT NOT NULL);
    """

    def __init__(self, path: str | Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(self._SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def claim(self, session_id: str, owner: str) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO owners VALUES (?, ?, ?)", (session_id, owner, self.clock()))

    def owner_of(self, session_id: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT owner FROM owners WHERE session_id=?", (session_id,)).fetchone()
        return row[0] if row else None

    def hit(self, owner: str, kind: str, window: float, limit: int | None) -> bool:
        """Record one use unless ``limit`` uses already fall inside ``window`` seconds."""
        now = self.clock()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM hits WHERE at < ?", (now - 86_400,))
            if limit is not None:
                used = db.execute("SELECT COUNT(*) FROM hits WHERE owner=? AND kind=? AND at>=?",
                                  (owner, kind, now - window)).fetchone()[0]
                if used >= limit:
                    return False
            db.execute("INSERT INTO hits VALUES (?, ?, ?)", (owner, kind, now))
        return True

    def record_spend(self, owner: str, session_id: str, usd: float) -> None:
        if usd > 0:
            with self._connect() as db:
                db.execute("INSERT INTO spend VALUES (?, ?, ?, ?)", (owner, session_id, today(), usd))

    def spent(self, *, session_id: str | None = None, owner: str | None = None,
              day: str | None = None) -> float:
        clauses, values = [], []
        for column, value in (("session_id", session_id), ("owner", owner), ("day", day)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as db:
            return float(db.execute(f"SELECT COALESCE(SUM(usd), 0) FROM spend{where}", values).fetchone()[0])

    def add_jobs(self, owner: str, session_id: str, job_ids: list[str]) -> None:
        with self._connect() as db:
            db.executemany("INSERT OR IGNORE INTO jobs VALUES (?, ?, ?)",
                           [(job_id, owner, session_id) for job_id in job_ids])

    def jobs_of(self, owner: str) -> list[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT job_id FROM jobs WHERE owner=?", (owner,))]


class SpendGuard:
    """A model port that stops at the profile's spend caps and records every call's cost."""

    def __init__(self, model: ModelPort, store: WebStore, security: SecurityPolicy, owner: str, session_id: str):
        self.model, self.store, self.limits = model, store, security.limits
        self.owner, self.session_id = owner, session_id
        self.name = model.name

    def stopped(self) -> str | None:
        """Why no further call may be made, or None."""
        limits, day = self.limits, today()
        if limits.session_usd is not None and self.store.spent(session_id=self.session_id) >= limits.session_usd:
            return "this session's model budget is used up"
        if (limits.person_usd_per_day is not None
                and self.store.spent(owner=self.owner, day=day) >= limits.person_usd_per_day):
            return "your model budget for today is used up"
        if limits.total_usd_per_day is not None and self.store.spent(day=day) >= limits.total_usd_per_day:
            return "the site's model budget for today is used up"
        return None

    async def respond(self, system: str, items: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        reason = self.stopped()
        if reason:
            raise ModelUnavailable(reason, "budget")
        usage = getattr(self.model, "usage", None)
        before = float(usage.get("estimated_usd") or 0.0) if isinstance(usage, dict) else None
        reply: ModelReply | None = None
        try:
            reply = await self.model.respond(system, items, tools)
            return reply
        finally:
            # A charged call that failed afterwards (an incomplete reply) still counts.
            after = float(usage.get("estimated_usd") or 0.0) if isinstance(usage, dict) else None
            cost = (after - before) if before is not None and after is not None else (reply.cost_usd if reply else 0.0)
            self.store.record_spend(self.owner, self.session_id, cost)


def _places(facts: Any) -> list[dict[str, Any]]:
    """The points the map shows: the reviewed points, else the proposed geography's points."""
    if facts.review:
        rows = facts.review.get("points") or []
    elif isinstance(facts.geography, dict) and "lat" in facts.geography:
        rows = [facts.geography]
    elif isinstance(facts.geography, list):
        rows = [item for item in facts.geography if isinstance(item, dict) and "lat" in item]
    else:
        rows = []
    return [{key: item[key] for key in ("name", "lat", "lon", "standard_offset_minutes") if key in item}
            for item in rows[:500]]


class AgentHost:
    """Web agent sessions on one service, job runner and MCP server (one per server process)."""

    def __init__(self, data_root: str | Path, runner: Any, mcp_server: Any, *,
                 security: SecurityPolicy | None = None,
                 model_factory: Callable[[], ModelPort | None] | None = None,
                 moderation_factory: Callable[[], ModerationPort | None] | None = None,
                 workers: int = 4, poll_seconds: float = 2.0, clock: Callable[[], float] = time.time):
        root = Path(data_root) / "agent"
        self.store = SessionStore(root / "sessions.sqlite")
        self.web = WebStore(root / "web.sqlite", clock=clock)
        self.runner = runner
        self.mcp_server = mcp_server
        self.security = security or default_policy()
        self.model_factory = model_factory
        self.moderation_factory = moderation_factory
        self.poll_seconds = poll_seconds
        self.approvals = ApprovalBook()            # one-shot plan approvals, answered in-process
        self._pool = ThreadPoolExecutor(workers, thread_name_prefix="agent-turn")
        self._mutex = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._busy: set[str] = set()
        self._following: dict[str, dict[str, tuple]] = {}   # session id -> last job snapshot seen
        self._stop = threading.Event()
        self._follower: threading.Thread | None = None

    @property
    def model_available(self) -> bool:
        return self.model_factory is not None

    # Lifecycle ----------------------------------------------------------------------------
    def start(self) -> None:
        """Start following jobs (idempotent)."""
        if self._follower is None:
            self._follower = threading.Thread(target=self._follow_loop, name="agent-jobs", daemon=True)
            self._follower.start()

    def close(self) -> None:
        self._stop.set()
        if self._follower is not None:
            self._follower.join(timeout=5)
        self._pool.shutdown(wait=True, cancel_futures=True)

    # Sessions -----------------------------------------------------------------------------
    def create(self, owner: str) -> str:
        if not self.web.hit(owner, "session", 3600, self.security.limits.sessions_per_hour):
            raise WebRefusal("SESSION_LIMIT", "You have started the most chat sessions allowed in an hour; "
                                              "continue an open one or try again later.")
        state = self.store.create()
        state.mode = "agent" if self.model_available else "guided"
        self.store.save(state)
        self.web.claim(state.id, owner)
        self._submit(state.id, owner, lambda s: s.begin())
        return state.id

    def check_owner(self, session_id: str, owner: str) -> None:
        """Other people's sessions (and unknown ones) do not exist for this person."""
        if self.web.owner_of(session_id) != owner:
            raise KeyError(session_id)

    def busy(self, session_id: str) -> bool:
        with self._mutex:
            return session_id in self._busy

    def submit(self, session_id: str, owner: str, item: WebInput) -> Future:
        """Start one input in the background; the caller follows the session's events."""
        self.check_owner(session_id, owner)
        if not self.web.hit(owner, "input", 60, self.security.limits.inputs_per_minute):
            raise WebRefusal("RATE_LIMIT", "Too many messages in a minute; wait a moment and try again.")
        state = self.store.load(session_id)
        answer, form = item.answer if item.type == "answer" else None, state.form
        if answer is not None and form is not None and answer.approve and form.gate == "review_plan":
            self._check_running_jobs(owner, sum(1 for plan in state.facts.plans
                                                if plan.get("output_count") and not plan.get("job_id")))
        elif (answer is not None and form is not None and answer.choice_ids == ["retry"]
              and form.gate == "review_retry"):
            self._check_running_jobs(owner, len(form.data.get("jobs") or []))   # a retry starts jobs too
        return self._submit(session_id, owner, self._action(item))

    def upload(self, session_id: str, owner: str, content: bytes, filename: str | None) -> Future:
        self.check_owner(session_id, owner)
        if not self.web.hit(owner, "input", 60, self.security.limits.inputs_per_minute):
            raise WebRefusal("RATE_LIMIT", "Too many messages in a minute; wait a moment and try again.")
        return self._submit(session_id, owner, lambda s: s.upload_epw(content, filename))

    @staticmethod
    def _action(item: WebInput) -> Action:
        if item.type == "text":
            return lambda s: s.send_text(item.text or "")
        if item.type == "answer":
            answer = item.answer
            assert answer is not None
            return lambda s: s.answer(answer)
        if item.type == "back":
            return lambda s: s.back()
        if item.type == "new":
            return lambda s: s.new_request()
        if item.type == "mode":
            return lambda s: s.set_mode(item.mode or "guided")
        return lambda s: s.show_request()

    def _check_running_jobs(self, owner: str, starting: int) -> None:
        limit = self.security.limits.running_jobs
        if limit is None:
            return
        running = 0
        for job_id in self.web.jobs_of(owner):
            try:
                running += self.runner.store.get(job_id).state not in TERMINAL
            except Exception:                        # a job record that is gone is not running
                continue
        if running + starting > limit:
            raise WebRefusal("JOB_LIMIT", f"You already have {running} weather job(s) running (limit {limit}); "
                                          "wait for them to finish before starting another.")

    def _submit(self, session_id: str, owner: str, action: Action) -> Future:
        with self._mutex:
            if session_id in self._busy:
                raise WebRefusal("SESSION_BUSY", "The previous input is still being handled.", status=409)
            self._busy.add(session_id)
        try:
            return self._pool.submit(self._turn, session_id, owner, action)
        except RuntimeError:                           # shutting down
            with self._mutex:
                self._busy.discard(session_id)
            raise WebRefusal("SHUTTING_DOWN", "The server is restarting; try again shortly.", status=503) from None

    def _lock(self, session_id: str) -> threading.Lock:
        with self._mutex:
            return self._locks.setdefault(session_id, threading.Lock())

    def _turn(self, session_id: str, owner: str, action: Action) -> None:
        try:
            with self._lock(session_id):
                asyncio.run(self._run(session_id, owner, action))
        except Exception:
            logger.exception("Web agent turn failed for session %s", session_id[:8])
        finally:
            with self._mutex:
                self._busy.discard(session_id)

    async def _run(self, session_id: str, owner: str, action: Action) -> AgentSession:
        model = self.model_factory() if self.model_factory else None
        policy: Policy = (ModelPolicy(SpendGuard(model, self.web, self.security, owner, session_id))
                          if model is not None else GuidedPolicy())
        moderation = self.moderation_factory() if self.moderation_factory else None
        try:
            async with InProcessMCP(self.mcp_server, self.approvals) as port:
                session = AgentSession.resume(self.store, port, self.approvals, policy, session_id,
                                              security=self.security, moderation=moderation)
                if model is None and session.state.mode == "agent":
                    session.state.mode = "guided"              # no model on this server
                    session.state.pending_call, session.state.turn = None, []
                await action(session)
                facts = session.facts
                self.web.add_jobs(owner, session_id, facts.job_ids)
                if any(job not in facts.finished_job_ids for job in facts.job_ids):
                    with self._mutex:
                        self._following.setdefault(session_id, {})
                return session
        finally:
            # Their HTTP clients belong to this turn's event loop, which ends with the turn.
            for port_with_client in (model, moderation):
                client = getattr(port_with_client, "client", None)
                if client is not None and hasattr(client, "aclose"):
                    await client.aclose()

    # Jobs ---------------------------------------------------------------------------------
    def follow(self, session_id: str) -> None:
        """Follow a session's running jobs (after a restart, when someone opens it again)."""
        facts = self.store.load(session_id).facts
        if any(job not in facts.finished_job_ids for job in facts.job_ids):
            with self._mutex:
                self._following.setdefault(session_id, {})

    def _follow_loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            self.follow_once()

    def follow_once(self) -> None:
        """One pass over followed sessions that are idle and show no form."""
        with self._mutex:
            waiting = [sid for sid in self._following if sid not in self._busy]
        for session_id in waiting:
            state = self.store.load(session_id)
            pending = [job for job in state.facts.job_ids if job not in state.facts.finished_job_ids]
            if not pending or state.ended is not None:
                with self._mutex:
                    self._following.pop(session_id, None)
                continue
            if state.form is not None:
                continue                                   # as in the CLI: follow while no form is open
            owner = self.web.owner_of(session_id) or ""
            try:
                self._submit(session_id, owner, self._checker(self._following.get(session_id, {}))).result()
            except WebRefusal:
                continue

    @staticmethod
    def _checker(seen: dict[str, tuple]) -> Action:
        return lambda s: s.check_jobs(seen)

    # Snapshot -----------------------------------------------------------------------------
    def snapshot(self, session_id: str, *, events: int = RECENT_EVENTS) -> dict[str, Any]:
        state = self.store.load(session_id)
        facts, form = state.facts, state.form
        recent = self.store.events(session_id, max(self.store.last_seq(session_id) - events, 0))
        max_chars = self.security.external_text.max_chars
        snapshot: dict[str, Any] = {
            "id": state.id, "mode": state.mode, "revision": state.revision,
            "form": form.model_dump(mode="json") if form else None,
            "busy": self.busy(session_id), "ended": state.ended is not None,
            "downgraded": state.downgraded, "model_available": self.model_available,
            "profile": self.security.profile, "strikes": state.strikes,
            "strike_limit": self.security.strikes.limit,
            "events": [event.model_dump(mode="json") for event in recent],
            "cursor": recent[-1].seq if recent else 0,
            "parts": parts(facts, max_chars=max_chars), "places": _places(facts), "years": facts.years,
            "job_ids": facts.job_ids, "finished_job_ids": facts.finished_job_ids,
            "artifact_ids": facts.artifact_ids, "candidates": [], "offers": [],
        }
        if form is not None and form.gate == "choose_location":
            snapshot["candidates"] = [{"id": str(item.get("id", index)), "name": item.get("name"),
                                       "lat": item["lat"], "lon": item["lon"]}
                                      for index, item in enumerate(facts.candidates)]
        if form is not None and form.kind == "product_choice":
            snapshot["offers"] = [{"id": offer["id"], "label": offer["label"], "detail": offer.get("detail"),
                                   "group": "actual" if offer["request"]["product"] == "historical" else "typical",
                                   "available": offer.get("available"), "sites": offer.get("sites")}
                                  for offer in facts.offers]
        return snapshot
