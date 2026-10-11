"""Run eval tasks through AgentSession and grade each trial from its record.

Each trial runs on a fresh data root with the real session, MCP server and job runner (weather
providers stubbed unless asked otherwise). The simulated person types the task's messages and
answers forms by the task's answer policy. The trial's record (pins, trace ending in the
outcome) is graded by the registry's always-on graders and the task's own graders.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from ...jobs.worker import JobRunner
from ..guided import GuidedPolicy
from ..interactions import Answer, Interaction
from ..mcp_port import ApprovalBook, InProcessMCP
from ..model_port import ModelPort, ModelReply, ScriptedModel, Step, ToolCall
from ..moderation import ModerationPort, StubModeration
from ..policy_config import SecurityPolicy, load_policy
from ..policy_model import ModelPolicy
from ..session import AgentSession, Policy
from ..store import SessionStore
from .graders import Context, grade
from .records import metrics, outcome, short_hash, trace_entries
from .schema import Task, task_hash
from .stubs import stub_service, synthetic_epw

logger = logging.getLogger("openepw.agent.evals")


def scripted_model(task: Task) -> ScriptedModel | None:
    """A ScriptedModel from the task's script (None when the task has no offline solution).

    ``$artifact`` in a step's arguments becomes the last artifact id the conversation mentions,
    read from what the model was sent, as a real model would.
    """
    if task.script is None:
        return None
    steps: list[Step] = []
    for index, step in enumerate(task.script):
        if step.say is not None:
            steps.append(ModelReply(text=step.say))
            continue
        arguments = json.dumps(step.args)
        if "$artifact" in arguments:
            steps.append(_reading_step(f"call_{index}", str(step.call), arguments))
        else:
            steps.append(ModelReply(tool_calls=[ToolCall(f"call_{index}", str(step.call), arguments)]))
    return ScriptedModel(steps)


def _reading_step(call_id: str, name: str, arguments: str) -> Step:
    def step(system: str, items: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        found = re.findall(r"artifact ([0-9a-f]{32})", json.dumps(items))
        filled = arguments.replace("$artifact", found[-1] if found else "")
        return ModelReply(tool_calls=[ToolCall(call_id, name, filled)])
    return step


class RecordingModel:
    """Wraps a model and records each call for the trace: what was sent, the reply and its cost."""

    def __init__(self, model: ModelPort):
        self.model = model
        self.name = model.name
        self.calls: list[dict[str, Any]] = []
        self.position: Callable[[], int] = lambda: 0

    @property
    def usage(self) -> dict[str, Any]:
        return getattr(self.model, "usage", {})

    async def respond(self, system: str, items: list[dict[str, Any]],
                      tools: list[dict[str, Any]]) -> ModelReply:
        before = dict(self.usage)
        after_seq = self.position()
        reply = await self.model.respond(system, items, tools)
        usage = self.usage

        def delta(key: str) -> float:
            return float(usage.get(key, 0) or 0) - float(before.get(key, 0) or 0)
        # Provider "raw" items (encrypted reasoning) are left out, as the tracer does.
        sent = [{key: value for key, value in item.items() if key != "raw"} for item in json.loads(json.dumps(items))]
        self.calls.append({"after": after_seq, "data": {
            "system_sha256": short_hash(system), "tools_sha256": short_hash(tools),
            "tools": [tool.get("name") for tool in tools], "items": sent,
            "reply": {"text": reply.text, "tool_calls": [{"name": call.name, "arguments": call.arguments}
                                                         for call in reply.tool_calls]},
            "input_tokens": int(delta("input_tokens")), "output_tokens": int(delta("output_tokens")),
            "cost_usd": round(delta("estimated_usd"), 6)}})
        return reply


def _answer(form: Interaction, answers: Mapping[Any, Any]) -> Answer | str | None:
    """The task's answer to the open form: an Answer, text to type, or None to stop."""
    base = {"interaction_id": form.id, "revision": form.revision}
    policy = answers.get(form.kind)
    if policy is None:
        return None
    if isinstance(policy, str) and policy.startswith("say:"):
        return policy[4:].strip()                         # the person types this instead
    if form.kind in ("location_review", "plan_review"):
        return Answer(**base, approve=True) if policy in ("approve", "run") else None
    if form.kind in ("product_choice", "choice"):
        ids = [option.id for option in form.options]
        wanted = [item for item in (policy if isinstance(policy, list) else []) if item in ids]
        chosen = wanted or ids[:1]
        return Answer(**base, choice_ids=chosen if form.multi else chosen[:1]) if chosen else None
    return str(policy)                                    # text and map_input forms: type it


def _moderation_for(task: Task, moderation: ModerationPort | None) -> ModerationPort:
    """The task's moderation: a stub outage or stub flags on request, else the given port (the
    real endpoint in live runs), else the offline stub."""
    if task.setup.moderation == "unavailable":
        return StubModeration(unavailable=True)
    if task.setup.moderation == "stub" or moderation is None:
        return StubModeration()
    return moderation


async def _answer_forms(session: AgentSession, task: Task, follow_seconds: float) -> None:
    """Answer the forms that follow one message, as the task's person would."""
    for _ in range(task.user.max_interactions):
        if session.state.ended is not None:
            return
        running = [job for job in session.facts.job_ids if job not in session.facts.finished_job_ids]
        if running and session.form is None:
            await session.follow_jobs(timeout=follow_seconds)
            if [job for job in session.facts.job_ids if job not in session.facts.finished_job_ids]:
                return
            continue
        form = session.form
        if form is None or form.gate == "next_steps":
            return
        reply = _answer(form, task.user.answers)
        if reply is None:
            return
        if isinstance(reply, Answer):
            await session.answer(reply)
        else:
            await session.answer(Answer(interaction_id=form.id, revision=form.revision, text=reply))


async def run_trial(task: Task, *, mode: str, model: ModelPort | None, data_root: Path,
                    security: SecurityPolicy | None = None, moderation: ModerationPort | None = None,
                    live_providers: bool = False, follow_seconds: float = 120.0, trial: int = 1,
                    pins: dict[str, Any] | None = None) -> dict[str, Any]:
    """One graded trial of one task on a fresh data root."""
    from ...config import RuntimeConfig
    from ...mcp.server import create_server
    from ...service import WeatherService

    security = security or load_policy("local")
    service = (WeatherService(RuntimeConfig(data_root=data_root)) if live_providers
               else stub_service(data_root, fail_near=task.setup.fail_near))
    runner = JobRunner(service)
    runner.recover()
    approvals = ApprovalBook()
    store = SessionStore(data_root / "agent" / "sessions.sqlite")
    recorder = RecordingModel(model) if mode == "agent" and model is not None else None
    policy: Policy = GuidedPolicy() if mode == "guided" else ModelPolicy(recorder)  # type: ignore[arg-type]
    started = time.monotonic()
    try:
        async with InProcessMCP(create_server(service, runner=runner), approvals) as port:
            session = AgentSession.start(store, port, approvals, policy, poll_seconds=0.2, security=security,
                                         moderation=_moderation_for(task, moderation))
            if recorder is not None:
                recorder.position = lambda: (events[-1].seq if (events := session.events()) else 0)
            await session.begin()
            if task.setup.upload:                        # e.g. text planted in an EPW header
                await session.upload_epw(synthetic_epw(task.setup.upload.city), task.setup.upload.filename)
            for text in [task.user.say, *task.user.then]:
                if session.state.ended is not None:
                    break
                await session.send_text(text)
                await _answer_forms(session, task, follow_seconds)
            trace = trace_entries(session.events(), recorder.calls if recorder else []) + [outcome(session)]
    finally:
        runner.close()
    seconds = time.monotonic() - started
    record = {"run_id": (pins or {}).get("run_id"), "task_id": task.id, "task_hash": task_hash(task),
              "title": task.title, "suite": task.suite, "tags": task.tags, "trial": trial, "mode": mode,
              "profile": security.profile, "pins": pins or {}, "trace": trace}
    verdicts = grade(record, task.graders_for(security.profile),
                     Context(mode=mode, links=security.links, max_steps=getattr(policy, "max_steps", 8)))
    record["grades"] = [verdict.as_dict() for verdict in verdicts]
    record["passed"] = all(verdict.passed for verdict in verdicts if verdict.severity == "hard")
    record["metrics"] = metrics(trace, seconds)
    return record


def error_record(task: Task, *, mode: str, profile: str, trial: int, pins: dict[str, Any] | None,
                 error: BaseException, seconds: float) -> dict[str, Any]:
    """A run that crashed: reported as RUN_ERROR, so one broken trial never ends the eval."""
    return {"run_id": (pins or {}).get("run_id"), "task_id": task.id, "task_hash": task_hash(task),
            "title": task.title, "suite": task.suite, "tags": task.tags, "trial": trial, "mode": mode,
            "profile": profile, "pins": pins or {},
            "trace": [{"type": "error", "text": f"run error: {type(error).__name__}", "data": {"code": "RUN_ERROR"}}],
            "grades": [{"grader": "run", "code": "RUN_ERROR", "severity": "hard", "passed": False,
                        "evidence": [0], "detail": type(error).__name__}],
            "passed": False, "metrics": metrics([], seconds)}


def applies(task: Task, mode: str, profile: str) -> bool:
    return mode in task.modes and profile.split("+")[0] in task.profiles


async def run_suite(tasks: list[Task], *, mode: str,
                    model_factory: Callable[[Task], ModelPort | None] | None = None,
                    trials: Callable[[Task], int] = lambda task: 1, live_providers: bool = False,
                    security: SecurityPolicy | None = None, moderation: ModerationPort | None = None,
                    pins: dict[str, Any] | None = None,
                    on_record: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Every applicable task, each for its number of trials, on fresh temporary data roots."""
    security = security or load_policy("local")
    records: list[dict[str, Any]] = []
    for task in tasks:
        if not applies(task, mode, security.profile):
            continue
        if mode == "agent" and model_factory is None:
            raise ValueError("Agent-mode evals need a model")
        for trial in range(1, trials(task) + 1):
            model = model_factory(task) if model_factory else None
            if mode == "agent" and model is None:
                break                                     # e.g. no script for this task
            started = time.monotonic()
            try:
                with tempfile.TemporaryDirectory(prefix="openepw-eval-", ignore_cleanup_errors=True) as root:
                    record = await run_trial(task, mode=mode, model=model, data_root=Path(root), security=security,
                                             moderation=moderation, live_providers=live_providers, trial=trial,
                                             pins=pins)
            except Exception as error:
                logger.exception("eval trial %s/%s failed", task.id, trial)
                record = error_record(task, mode=mode, profile=security.profile, trial=trial, pins=pins,
                                      error=error, seconds=time.monotonic() - started)
            records.append(record)
            if on_record:
                on_record(record)
            if over_budget(model):
                return records                            # later trials would only test guided mode
    return records


def over_budget(model: ModelPort | None) -> bool:
    """True once a budgeted model has spent its limit (its next call would be refused)."""
    inner = getattr(model, "model", model)
    usage, limit = getattr(inner, "usage", None), getattr(inner, "max_cost_usd", None)
    if not usage or limit is None:
        return False
    return float(usage.get("estimated_usd", 0.0)) >= limit * 0.98
