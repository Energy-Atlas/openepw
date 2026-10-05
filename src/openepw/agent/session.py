"""One conversation: inputs, forms, tool calls, Back, uploads and job following."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from typing import Any, Callable, Protocol

from ..models import OpenEPWError
from .gates import GateRequired
from .interactions import Answer, Event, Interaction
from .mcp_port import ApprovalBook, MCPPort, ToolFailure, ToolResult
from .state import Facts, SessionState
from .store import SessionStore

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
                 state: SessionState, policy: Policy, *, poll_seconds: float = 0.5):
        self.store = store
        self.port = port
        self.approvals = approvals
        self.state = state
        self.policy = policy
        self.poll_seconds = poll_seconds

    @classmethod
    def start(cls, store: SessionStore, port: MCPPort, approvals: ApprovalBook, policy: Policy,
              **options: Any) -> AgentSession:
        return cls(store, port, approvals, store.create(), policy, **options)

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

    async def tool(self, name: str, **arguments: Any) -> ToolResult:
        self.emit("tool", name, tool=name, phase="call")
        result = await self.port.call(name, **arguments)
        self.emit("tool", result.text, tool=name, phase="result")
        return result

    async def _guard(self, work: Any) -> None:
        try:
            await work
        except ToolFailure as failure:
            self.emit("error", f"{failure.code}: {failure.message}", code=failure.code,
                      retryable=failure.retryable)
        except GateRequired as gate:
            self.emit("error", str(gate), code="GATE_REQUIRED", need=gate.need)
        except OpenEPWError as error:
            self.emit("error", f"{error.issue.code}: {error.issue.message}", code=error.issue.code,
                      retryable=error.issue.retryable)
        except Exception:
            # The exception text may carry payloads, so only a correlation id reaches the person.
            correlation_id = uuid.uuid4().hex[:12]
            logger.exception("agent turn failed (correlation id %s)", correlation_id)
            self.emit("error", f"INTERNAL_ERROR: Something went wrong; the form is kept "
                               f"(correlation id {correlation_id}).",
                      code="INTERNAL_ERROR", correlation_id=correlation_id)
        finally:
            self.store.save(self.state)

    async def begin(self) -> None:
        if self.form is None:
            await self._guard(self.policy.advance(self))

    async def send_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if len(text) > 4000:
            self.emit("error", "Messages are limited to 4,000 characters.", code="MESSAGE_TOO_LONG")
            return
        self.emit("user", text)
        await self._guard(self.policy.on_text(self, text))

    async def answer(self, answer: Answer) -> None:
        form = self.form
        if form is None or answer.interaction_id != form.id or answer.revision != form.revision:
            self.emit("error", "That form is no longer current; answer the latest one.", code="STALE_FORM")
            return
        self.emit("user", answer_text(form, answer), answer=answer.model_dump(mode="json"))
        await self._guard(self.policy.on_answer(self, form, answer))

    async def back(self) -> None:
        current, *earlier = self.store.snapshots(self.id, 2)
        if not earlier:
            self.emit("error", "There is no earlier step to go back to.", code="NOTHING_TO_UNDO")
            return
        restored = earlier[0]
        if restored.facts.job_ids != self.facts.job_ids:
            self.emit("error", "A weather job already started after that step; start a new request instead.",
                      code="JOB_STARTED")
            return
        self.store.drop_snapshot(self.id)
        # Back undoes choices, not results: uploaded and retrieved EPWs stay available.
        restored.facts.artifact_ids = list(self.facts.artifact_ids)
        restored.facts.finished_job_ids = list(self.facts.finished_job_ids)
        restored.revision = self.state.revision + 1
        if restored.form is not None:
            restored.form = restored.form.model_copy(update={"revision": restored.revision})
        self.state = restored
        self.store.save(self.state)
        self.emit("notice", "Went back to: " + (restored.form.prompt if restored.form else "the start"),
                  form=restored.form.model_dump(mode="json") if restored.form else None)

    async def new_request(self) -> None:
        self.facts.new_request()
        self.close_form()
        await self._guard(self.policy.advance(self))

    async def upload_epw(self, content: bytes, filename: str | None = None) -> None:
        await self._guard(self._upload(content, filename))

    async def _upload(self, content: bytes, filename: str | None) -> None:
        if not content or len(content) > MAX_UPLOAD:
            self.emit("error", "EPW uploads must be 1 byte to 5 MB.", code="RESOURCE_LIMIT")
            return
        result = await self.tool("epw_upload", content_base64=base64.b64encode(content).decode("ascii"),
                                 filename=filename)
        self.facts.artifact_ids.append(result.data["artifact_id"])
        self.emit("assistant", f"Registered your EPW ({result.data.get('rows')} rows) as artifact "
                               f"{result.data['artifact_id']}.", artifact_id=result.data["artifact_id"])
        if self.facts.geography is None and not self.facts.job_ids:
            self.facts.stage = "results"
            self.close_form()
            await self.policy.advance(self)

    async def follow_jobs(self, *, timeout: float = 600.0,
                          on_update: Callable[[], None] | None = None) -> None:
        """Follow submitted jobs until they finish (the host polls; a model never does)."""
        await self._guard(self._follow(timeout, on_update))

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
