"""One conversation: inputs, forms, tool calls, Back, uploads and job following."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import Any, Callable, Protocol

from ..models import OpenEPWError
from .gates import GateRequired
from .guard import normalize_input
from .interactions import Answer, Event, Interaction
from .mcp_port import ApprovalBook, MCPPort, ToolFailure, ToolResult
from .moderation import ModerationPort, ModerationUnavailable, epw_text_fields
from .policy_config import SecurityPolicy, default_policy
from .state import Facts, SessionState
from .store import SessionStore
from .text import safe_prompt
from .tracing import NullTracer, summarize_arguments

WITHHELD = "[message withheld by moderation]"
TERMINAL = frozenset({"completed", "partially_completed", "failed", "cancelled"})
MAX_UPLOAD = 5_000_000
logger = logging.getLogger("openepw.agent")


class Policy(Protocol):
    async def on_text(self, session: AgentSession, text: str) -> None: ...

    async def on_answer(self, session: AgentSession, form: Interaction, answer: Answer) -> None: ...

    async def advance(self, session: AgentSession) -> None: ...


def answer_text(form: Interaction, answer: Answer) -> str:
    """What the person said, for the transcript."""
    if answer.text:
        return answer.text
    if answer.approve:
        return "Run" if form.kind == "plan_review" else "Approved"
    if answer.choice_ids:
        labels = {option.id: option.label for option in form.options}
        return ", ".join(labels.get(choice, choice) for choice in answer.choice_ids)
    return "Selected on the map" if answer.value is not None else ""


class AgentSession:
    def __init__(self, store: SessionStore, port: MCPPort, approvals: ApprovalBook,
                 state: SessionState, policy: Policy, *, poll_seconds: float = 0.5,
                 tracer: NullTracer | None = None, security: SecurityPolicy | None = None,
                 moderation: ModerationPort | None = None):
        self.store = store
        self.moderation = moderation                    # None: moderation cannot run (on_error decides)
        self.security = security or default_policy()   # the YAML security profile in force
        self.trace = tracer or NullTracer()        # LangSmith runs when the env file turns them on
        self.port = port
        self.approvals = approvals
        self.state = state
        self.policy = policy
        self.poll_seconds = poll_seconds

    @classmethod
    def start(cls, store: SessionStore, port: MCPPort, approvals: ApprovalBook, policy: Policy,
              **options: Any) -> AgentSession:
        state = store.create()
        # A new conversation starts in the policy's own mode (agent for a model policy).
        state.mode = getattr(policy, "initial_mode", "guided")
        store.save(state)
        return cls(store, port, approvals, state, policy, **options)

    @classmethod
    def resume(cls, store: SessionStore, port: MCPPort, approvals: ApprovalBook, policy: Policy,
               session_id: str, **options: Any) -> AgentSession:
        return cls(store, port, approvals, store.load(session_id), policy, **options)

    @property
    def id(self) -> str:
        return self.state.id

    @property
    def facts(self) -> Facts:
        return self.state.facts

    @property
    def form(self) -> Interaction | None:
        return self.state.form

    def events(self, after: int = 0) -> list[Event]:
        return self.store.events(self.id, after)

    def emit(self, type: str, text: str = "", **data: Any) -> Event:
        return self.store.append(self.id, type, text, data)

    def open_form(self, form: Interaction) -> Interaction:
        """Show a form; the snapshot taken here is what Back returns to."""
        self.state.revision += 1
        form = form.model_copy(update={"revision": self.state.revision})
        self.state.form = form
        self.store.save(self.state)
        self.store.push_snapshot(self.state)
        self.emit("form", form.prompt, form=form.model_dump(mode="json"))
        return form

    def close_form(self) -> None:
        self.state.form = None

    async def tool(self, name: str, /, *, by: str = "host", **arguments: Any) -> ToolResult:
        """Call an MCP tool; ``by`` records whether the host or the model asked for it."""
        self.emit("tool", name, tool=name, phase="call", by=by)
        run = self.trace.start(name, "tool", {"by": by, "arguments": summarize_arguments(arguments)})
        try:
            result = await self.port.call(name, **arguments)
        except ToolFailure as failure:
            self.trace.end(run, error=failure.code)
            raise
        except Exception as error:
            self.trace.end(run, error=type(error).__name__)
            raise
        self.trace.end(run, outputs={"summary": result.text[:1000]})
        self.emit("tool", result.text, tool=name, phase="result", by=by)
        return result

    async def _guard(self, work: Any, kind: str = "advance", inputs: dict[str, Any] | None = None) -> None:
        """Run one input's work; failures become error events, never a crash. One trace per input."""
        events = self.events()
        before = events[-1].seq if events else 0
        self.state.struck_this_turn = False
        self.trace.start_turn(kind, inputs or {}, session_id=self.id, mode=self.state.mode)
        error_code: str | None = None
        try:
            await work
        except ToolFailure as failure:
            error_code = failure.code
            self.emit("error", f"{failure.code}: {failure.message}", code=failure.code,
                      retryable=failure.retryable)
        except GateRequired as gate:
            error_code = "GATE_REQUIRED"
            self.emit("error", str(gate), code="GATE_REQUIRED", need=gate.need)
        except OpenEPWError as error:
            error_code = error.issue.code
            self.emit("error", f"{error.issue.code}: {error.issue.message}", code=error.issue.code,
                      retryable=error.issue.retryable)
        except Exception:
            error_code = "INTERNAL_ERROR"
            # The exception text may carry payloads, so only a correlation id reaches the person.
            correlation_id = uuid.uuid4().hex[:12]
            logger.exception("agent turn failed (correlation id %s)", correlation_id)
            self.emit("error", f"INTERNAL_ERROR: Something went wrong; the form is kept "
                               f"(correlation id {correlation_id}).",
                      code="INTERNAL_ERROR", correlation_id=correlation_id)
        finally:
            if (self.security.strikes.counting == "consecutive" and kind in ("message", "answer")
                    and not self.state.struck_this_turn):
                self.state.strikes = 0              # a normal input resets consecutive strikes
            self.store.save(self.state)
            replies = [event.text[:500] for event in self.events(before) if event.type == "assistant"]
            form = self.form
            self.trace.end_turn({"replies": replies[-5:], "mode": self.state.mode,
                                 "form": f"{form.kind} ({form.gate})" if form else None}, error_code)

    async def begin(self) -> None:
        if self.form is None:
            await self._guard(self.policy.advance(self), "begin")

    def _refuse_if_ended(self) -> bool:
        if self.state.ended is None:
            return False
        self.emit("error", "This session has ended; start a new session to continue.", code="SESSION_ENDED")
        return True

    async def _moderation(self, kind: str, texts: list[str]) -> tuple[str, tuple[str, ...]]:
        """'ok', 'flagged', 'blocked' (cannot run and the profile refuses) or 'unchecked'
        (cannot run and the profile allows it), with flagged category names."""
        rules = self.security.moderation
        texts = [text for text in texts if text and text.strip()]
        if not rules.enabled or kind not in rules.check or not texts:
            return "ok", ()
        try:
            if self.moderation is None:
                raise ModerationUnavailable("No moderation is configured")
            result = await self.moderation.check(texts)
        except ModerationUnavailable:
            return ("blocked" if rules.on_error == "block" else "unchecked"), ()
        if result.flagged:
            logger.info("Moderation flagged %s input: %s", kind, ", ".join(result.categories))
            return "flagged", result.categories
        return "ok", ()

    def _moderation_notice(self, status: str) -> bool:
        """Report a moderation outage; True when the input must not be processed."""
        if status == "blocked":
            self.emit("error", "This could not be checked by moderation, so it was not processed. "
                               "Try again later.", code="MODERATION_UNAVAILABLE")
            return True
        if status == "unchecked" and "moderation_unavailable" not in self.state.shown_notices:
            self.state.shown_notices.append("moderation_unavailable")
            self.emit("notice", "Moderation is unavailable; continuing without it under the "
                                f"{self.security.profile} profile.", code="MODERATION_UNAVAILABLE")
        return False

    async def model_says(self, text: str, **data: Any) -> None:
        """Show the model's text after the host's output checks (moderation if configured)."""
        status, categories = await self._moderation("model_output", [text])
        if status == "flagged":
            self.emit("assistant", "I can't show that reply.", code="MODERATION_FLAG",
                      categories=list(categories))
            return
        if status == "blocked":
            self.emit("assistant", "That reply could not be checked by moderation, so it is not shown.",
                      code="MODERATION_UNAVAILABLE")
            return
        self.emit("assistant", text, **data)

    async def strike(self, source: str, message: str, *, code: str = "OUT_OF_SCOPE", **data: Any) -> bool:
        """Show a guard's message and, if the profile counts this source, record a strike.

        The profile decides what happens at the limit: end the session, switch to guided mode,
        or only warn. Returns whether a strike was counted.
        """
        rules = self.security.strikes
        counted = source in rules.sources
        if counted:
            self.state.strikes += 1
            self.state.struck_this_turn = True
        count = self.state.strikes
        shown = f"{message} (strike {count} of {rules.limit})" if counted and rules.show_count else message
        self.emit("assistant", shown, code=code, source=source, strike=count if counted else None, **data)
        if not counted:
            return False
        consequence = {"end_session": "ends this session", "guided": "switches this session to guided mode",
                       "warn": "reaches this session's strike limit"}[rules.action]
        if count == rules.warn_at and count < rules.limit:
            self.emit("notice", f"One more unrelated or unsafe request {consequence}.", code="STRIKE_WARNING")
        if count == rules.limit:
            await self._strike_limit(rules.action, source)
        self.store.save(self.state)                 # a strike is never lost to a crash
        return True

    async def _strike_limit(self, action: str, source: str) -> None:
        if action == "end_session":
            self.state.ended = source
            self.state.pending_call, self.state.turn = None, []
            self.close_form()
            self.emit("notice", f"This session has ended after {self.state.strikes} strikes. Running jobs "
                                "continue and their files stay in the data root; start a new session to "
                                "continue.", code="SESSION_ENDED")
        elif action == "guided":
            switch = getattr(self.policy, "set_mode", None)
            if switch is not None and self.state.mode != "guided":
                await switch(self, "guided")
            self.state.mode = "guided"
            self.emit("notice", "Strike limit reached: this session continues in guided mode.",
                      code="STRIKE_LIMIT")
        else:
            self.emit("notice", "Strike limit reached; this profile only warns.", code="STRIKE_LIMIT")

    async def reopen(self) -> bool:
        """Reopen an ended session when the profile allows it; strikes start again from zero."""
        if self.state.ended is None:
            return True
        if self.security.strikes.reopen != "allow":
            self.emit("error", f"This session has ended and the {self.security.profile} profile does not "
                               "allow reopening it.", code="SESSION_ENDED")
            return False
        self.state.ended, self.state.strikes = None, 0
        self.store.save(self.state)
        self.emit("notice", "Session reopened; strikes start again from zero.", code="SESSION_REOPENED")
        return True

    async def send_text(self, text: str) -> None:
        text = text.strip()
        if not text or self._refuse_if_ended():
            return
        if len(text) > 4000:
            self.emit("error", "Messages are limited to 4,000 characters.", code="MESSAGE_TOO_LONG")
            return
        # Hidden characters, credentials and local paths never reach the event log or a model.
        text = safe_prompt(normalize_input(text), limit=4000)
        self.state.turn_origin = "text"
        status, categories = await self._moderation("input", [text])
        if status == "flagged":
            self.emit("user", WITHHELD)
            await self.strike("moderation", "That message can't be processed.", code="MODERATION_FLAG",
                              categories=list(categories))
            return
        self.emit("user", text)
        if self._moderation_notice(status):
            self.store.save(self.state)
            return
        await self._guard(self.policy.on_text(self, text), "message", {"text": text})

    async def answer(self, answer: Answer) -> None:
        if self._refuse_if_ended():
            return
        form = self.form
        if form is None or answer.interaction_id != form.id or answer.revision != form.revision:
            self.emit("error", "That form is no longer current; answer the latest one.", code="STALE_FORM")
            return
        if answer.text:
            answer = answer.model_copy(update={"text": safe_prompt(normalize_input(answer.text), limit=4000)})
            status, categories = await self._moderation("form_text", [answer.text or ""])
            if status == "flagged":
                self.emit("user", WITHHELD)
                await self.strike("moderation", "That answer can't be processed.", code="MODERATION_FLAG",
                                  categories=list(categories))
                return
            if self._moderation_notice(status):
                return
        said = answer_text(form, answer)
        self.state.turn_origin = "text" if answer.text else "answer"
        self.emit("user", said, answer=answer.model_dump(mode="json"))
        await self._guard(self.policy.on_answer(self, form, answer), "answer",
                          {"form": form.kind, "gate": form.gate, "answer": said})

    async def back(self) -> None:
        if self._refuse_if_ended():
            return
        current, *earlier = self.store.snapshots(self.id, 2)
        if not earlier:
            self.emit("error", "There is no earlier step to go back to.", code="NOTHING_TO_UNDO")
            return
        restored = earlier[0]
        # A new request clears job_ids, so started plans (which only grow) also guard Back.
        if (restored.facts.job_ids != self.facts.job_ids
                or restored.facts.started_plans != self.facts.started_plans):
            self.emit("error", "A weather job already started after that step; start a new request instead.",
                      code="JOB_STARTED")
            return
        self.store.drop_snapshot(self.id)
        # Back undoes choices, not results: uploaded and retrieved EPWs stay available.
        restored.facts.artifact_ids = list(self.facts.artifact_ids)
        restored.facts.finished_job_ids = list(self.facts.finished_job_ids)
        # Back undoes choices, never strikes.
        restored.strikes, restored.ended = self.state.strikes, self.state.ended
        restored.shown_notices = list(self.state.shown_notices)
        restored.revision = self.state.revision + 1
        if restored.form is not None:
            restored.form = restored.form.model_copy(update={"revision": restored.revision})
        self.state = restored
        self.store.save(self.state)
        self.emit("notice", "Went back to: " + (restored.form.prompt if restored.form else "the start"),
                  form=restored.form.model_dump(mode="json") if restored.form else None)

    async def set_mode(self, mode: str) -> None:
        """Switch between agent and guided mode; agent mode needs a policy with a model."""
        if self._refuse_if_ended():
            return
        switch = getattr(self.policy, "set_mode", None)
        if switch is None:
            if mode != self.state.mode:
                self.emit("error", "Agent mode needs a configured model (OPENAI_API_KEY).",
                          code="MODEL_UNAVAILABLE")
            return
        await self._guard(switch(self, mode), "mode", {"mode": mode})

    async def new_request(self) -> None:
        if self._refuse_if_ended():
            return
        self.facts.new_request()
        self.close_form()
        # A model question left open belongs to the old request.
        self.state.pending_call, self.state.turn = None, []
        events = self.events()
        self.state.turn_seq = events[-1].seq if events else 0
        await self._guard(self.policy.advance(self), "new_request")

    async def upload_epw(self, content: bytes, filename: str | None = None) -> None:
        if self._refuse_if_ended():
            return
        await self._guard(self._upload(content, filename), "upload",
                          {"filename": safe_prompt(filename or "", limit=200), "bytes": len(content)})

    async def _upload(self, content: bytes, filename: str | None) -> None:
        if not content or len(content) > MAX_UPLOAD:
            self.emit("error", "EPW uploads must be 1 byte to 5 MB.", code="RESOURCE_LIMIT")
            return
        status, categories = await self._moderation("upload_text", [*epw_text_fields(content), filename or ""])
        if status == "flagged":
            await self.strike("moderation", "That file's text can't be processed, so it was not uploaded.",
                              code="MODERATION_FLAG", categories=list(categories))
            return
        if self._moderation_notice(status):
            return
        result = await self.tool("epw_upload", content_base64=base64.b64encode(content).decode("ascii"),
                                 filename=filename)
        self.facts.artifact_ids.append(result.data["artifact_id"])
        self.emit("assistant", f"Registered your EPW ({result.data.get('rows')} rows) as artifact "
                               f"{result.data['artifact_id']}.", artifact_id=result.data["artifact_id"])
        on_upload = getattr(self.policy, "on_upload", None)
        if on_upload is not None:                 # e.g. an open upload form a model asked for
            await on_upload(self, result.data["artifact_id"])
        elif self.facts.geography is None and not self.facts.job_ids:
            self.facts.stage = "results"
            self.close_form()
            await self.policy.advance(self)

    async def follow_jobs(self, *, timeout: float = 600.0,
                          on_update: Callable[[], None] | None = None) -> None:
        """Follow submitted jobs until they finish (the host polls; a model never does)."""
        await self._guard(self._follow(timeout, on_update), "follow_jobs")

    async def _follow(self, timeout: float, on_update: Callable[[], None] | None) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen: dict[str, tuple] = {}
        pending = [job_id for job_id in self.facts.job_ids if job_id not in self.facts.finished_job_ids]
        if not pending:
            return
        while pending:
            for job_id in list(pending):
                job = (await self.port.call("job_inspect", job_id=job_id)).data
                snapshot = (job.get("state"), job.get("completed", 0), job.get("failed", 0))
                if seen.get(job_id) != snapshot:
                    seen[job_id] = snapshot
                    self.emit("job", f"Job {job_id[:8]} {job.get('state')}: {job.get('completed', 0)} of "
                                     f"{job.get('total', 0)} outputs done, {job.get('failed', 0)} failed",
                              job_id=job_id, state=job.get("state"), completed=job.get("completed", 0),
                              total=job.get("total", 0), failed=job.get("failed", 0))
                if job.get("state") in TERMINAL:
                    pending.remove(job_id)
                    await self._finished(job_id, job)
            if on_update is not None:
                on_update()
            if pending:
                if loop.time() > deadline:
                    self.emit("notice", "Jobs are still running; check again later.", job_ids=pending)
                    return
                await asyncio.sleep(self.poll_seconds)
        self.facts.stage = "results"
        self.close_form()
        await self.policy.advance(self)

    async def _finished(self, job_id: str, job: dict[str, Any]) -> None:
        weather = list((job.get("artifacts") or {}).get("weather", []))
        codes: set[str] = set()
        for artifact_id in weather[:20]:
            inspected = (await self.tool("artifact_inspect", artifact_id=artifact_id)).data
            codes.update(inspected.get("qc_issue_codes") or [])
        self.facts.finished_job_ids.append(job_id)
        self.facts.artifact_ids.extend(weather)
        message = (f"Job {job.get('state')}: {job.get('completed', 0)} of {job.get('total', 0)} outputs "
                   f"completed, {job.get('failed', 0)} failed; {len(weather)} EPW file(s).")
        message += " QC issue codes: " + ", ".join(sorted(codes)) + "." if codes else ""
        message += (" These EPWs are not certified simulation-ready (simulation_ready=false); "
                    "review QC before simulation." if weather else " No EPW was produced.")
        self.emit("assistant", message, job_id=job_id, artifact_ids=weather)
