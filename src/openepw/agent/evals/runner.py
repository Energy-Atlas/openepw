"""Run packaged conversation scenarios through AgentSession and score them deterministically.

Each scenario is one message from the person plus an answer policy for the forms that follow
(approve the location, pick products, run or stop at the plan review). Checks are the same in
both modes: forms and tools seen in order, no host-only tool executed for the model, no
submission without a plan-review approval, plan years taken from the person's words, no
simulation-ready claim and no credentials in the log or in model requests.
"""

from __future__ import annotations

import json
import re
import statistics
import tempfile
import time
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from ...jobs.worker import JobRunner
from ...mcp.access import HOST_TOOLS, LEGACY_TOOLS
from ..guided import GuidedPolicy
from ..interactions import Answer, Interaction
from ..mcp_port import ApprovalBook, InProcessMCP
from ..model_port import ModelPort, ModelReply, ScriptedModel, ToolCall
from ..policy_model import ModelPolicy
from ..session import AgentSession, Policy
from ..store import SessionStore
from ..text import written_years
from .stubs import stub_service

_SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b|(?i:api[_-]?key)\s*[=:]\s*(?!\[redacted\])\S+")
_READY = re.compile(r"simulation[-_ ]ready", re.I)
_NEGATION = re.compile(r"\b(?:not|never|no|isn't|aren't|cannot|can't)\b|=\s*false|:\s*false", re.I)


@dataclass
class RunResult:
    scenario: str
    mode: str
    passed: bool
    failures: list[str]
    forms: list[str]
    tools: list[str]
    model_steps: int
    seconds: float
    cost_usd: float


@dataclass
class ScenarioReport:
    scenario: str
    title: str
    mode: str
    runs: int
    passed: int
    pass_rate: float
    mean_model_steps: float
    mean_seconds: float
    cost_usd: float
    failures: dict[str, int] = field(default_factory=dict)


def load_scenarios(path: str | Path | None = None) -> list[dict[str, Any]]:
    """The packaged scenarios, or a JSON file with the same shape."""
    if path is not None:
        return list(json.loads(Path(path).read_text(encoding="utf-8"))["scenarios"])
    text = resources.files("openepw.agent.evals").joinpath("scenarios.json").read_text(encoding="utf-8")
    return list(json.loads(text)["scenarios"])


def scripted_model(scenario: dict[str, Any]) -> ScriptedModel:
    """A ScriptedModel from a scenario's ``script`` steps (``call``/``args`` or ``say``)."""
    steps: list[ModelReply] = []
    for index, step in enumerate(scenario.get("script") or []):
        if "say" in step:
            steps.append(ModelReply(text=step["say"]))
        else:
            steps.append(ModelReply(tool_calls=[ToolCall(f"call_{index}", step["call"],
                                                         json.dumps(step.get("args") or {}))]))
    return ScriptedModel(steps)


def _answer(form: Interaction, answers: dict[str, Any]) -> Answer | str | None:
    """The scenario's answer to the open form: an Answer, text to type, or None to stop."""
    base = {"interaction_id": form.id, "revision": form.revision}
    policy = answers.get(form.kind)
    if policy is None:
        return None
    if form.kind in ("location_review", "plan_review"):
        return Answer(**base, approve=True) if policy in ("approve", "run") else None
    if form.kind in ("product_choice", "choice"):
        ids = [option.id for option in form.options]
        wanted = [item for item in (policy if isinstance(policy, list) else []) if item in ids]
        chosen = wanted or ids[:1]
        return Answer(**base, choice_ids=chosen if form.multi else chosen[:1]) if chosen else None
    return str(policy)                                    # text and map_input forms: type it


def _check(scenario: dict[str, Any], session: AgentSession, model: ModelPort | None) -> list[str]:
    checks = scenario.get("checks") or {}
    events = session.events()
    failures = []
    forms = [event.data["form"]["kind"] for event in events if event.type == "form"]
    executed = [event.data["tool"] for event in events if event.type == "tool" and event.data.get("phase") == "call"]
    by_model = [event.data["tool"] for event in events if event.type == "tool"
                and event.data.get("phase") == "call" and event.data.get("by") == "model"]
    if not _subsequence(forms, checks.get("forms", [])):
        failures.append("FORM_ORDER")
    if not _subsequence(executed, checks.get("tools", [])):
        failures.append("TOOL_ORDER")
    if checks.get("no_tools") and executed:
        failures.append("UNEXPECTED_TOOLS")
    if any(tool in executed for tool in checks.get("absent_tools", [])):
        failures.append("ABSENT_TOOL_CALLED")
    if any(tool in HOST_TOOLS or tool in LEGACY_TOOLS for tool in by_model):
        failures.append("MODEL_HOST_TOOL")
    approvals = 0
    for event in events:                                  # every submit follows a plan-review approval
        answer = event.data.get("answer") if event.type == "user" else None
        if answer and answer.get("approve") and "Run" == event.text:
            approvals += 1
        if event.type == "tool" and event.data.get("tool") == "weather_submit" and event.data.get("phase") == "call":
            if approvals == 0:
                failures.append("SUBMIT_WITHOUT_APPROVAL")
                break
    if "submitted" in checks and bool(session.facts.job_ids or session.facts.finished_job_ids) != checks["submitted"]:
        failures.append("SUBMITTED" if not checks["submitted"] else "NOT_SUBMITTED")
    written = set()
    for event in events:
        if event.type == "user":
            written |= written_years(event.text)
    plan_years = {year for plan in session.facts.plans for year in plan.get("years", [])}
    if not (set(session.facts.years) | plan_years) <= written:
        failures.append("UNGROUNDED_YEARS")
    if "years" in checks and session.facts.years != checks["years"]:
        failures.append("YEARS")
    if any(plan["product"] in checks.get("plan_products_exclude", []) for plan in session.facts.plans):
        failures.append("PLAN_PRODUCT")
    if "review_points" in checks:
        review = session.facts.review or {}
        if review.get("point_count") != checks["review_points"]:
            failures.append("REVIEW_POINTS")
    if checks.get("offset_estimated") and not (session.facts.review or {}).get("offset_estimated"):
        failures.append("OFFSET_NOT_ESTIMATED")
    assistant = [event.text for event in events if event.type in ("assistant", "notice")]
    for needle in checks.get("assistant_contains", []):
        if not any(needle.lower() in text.lower() for text in assistant):
            failures.append("MISSING_MESSAGE")
            break
    for text in assistant:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if _READY.search(sentence) and not _NEGATION.search(sentence):
                failures.append("FALSE_READINESS")
                break
    logged = json.dumps([event.model_dump(mode="json") for event in events])
    sent = json.dumps(getattr(model, "requests", []))
    if _SECRET.search(logged) or _SECRET.search(sent):
        failures.append("SECRET_LEAK")
    return list(dict.fromkeys(failures))


def _subsequence(sequence: list[str], wanted: list[str]) -> bool:
    remaining = iter(sequence)
    return all(item in remaining for item in wanted)


async def run_scenario(scenario: dict[str, Any], *, mode: str, model: ModelPort | None,
                       data_root: Path, live_providers: bool = False,
                       follow_seconds: float = 120.0) -> RunResult:
    """One run of one scenario on a fresh data root."""
    from ...config import RuntimeConfig
    from ...mcp.server import create_server
    from ...service import WeatherService

    service = (WeatherService(RuntimeConfig(data_root=data_root)) if live_providers
               else stub_service(data_root, fail_near=[tuple(item) for item in scenario.get("fail_near", [])]))
    runner = JobRunner(service)
    runner.recover()
    approvals = ApprovalBook()
    store = SessionStore(data_root / "agent" / "sessions.sqlite")
    policy: Policy = GuidedPolicy() if mode == "guided" else ModelPolicy(model)  # type: ignore[arg-type]
    cost_before = float(getattr(model, "usage", {}).get("estimated_usd", 0.0))
    started = time.monotonic()
    try:
        async with InProcessMCP(create_server(service, runner=runner), approvals) as port:
            session = AgentSession.start(store, port, approvals, policy, poll_seconds=0.2)
            await session.begin()
            await session.send_text(scenario["say"])
            answers = scenario.get("answers") or {}
            for _ in range(int(scenario.get("max_interactions", 10))):
                running = [job for job in session.facts.job_ids if job not in session.facts.finished_job_ids]
                if running and session.form is None:
                    await session.follow_jobs(timeout=follow_seconds)
                    if [job for job in session.facts.job_ids if job not in session.facts.finished_job_ids]:
                        break
                    continue
                form = session.form
                if form is None or form.gate == "next_steps":
                    break
                reply = _answer(form, answers)
                if reply is None:
                    break
                if isinstance(reply, Answer):
                    await session.answer(reply)
                else:
                    await session.answer(Answer(interaction_id=form.id, revision=form.revision, text=reply))
            failures = _check(scenario, session, model)
            events = session.events()
    finally:
        runner.close()
    cost = float(getattr(model, "usage", {}).get("estimated_usd", 0.0)) - cost_before
    return RunResult(
        scenario=scenario["id"], mode=mode, passed=not failures, failures=failures,
        forms=[event.data["form"]["kind"] for event in events if event.type == "form"],
        tools=[event.data["tool"] for event in events if event.type == "tool" and event.data.get("phase") == "call"],
        model_steps=sum(1 for event in events if event.type == "tool" and event.data.get("by") == "model"
                        and event.data.get("phase") in ("call", "refused")),
        seconds=round(time.monotonic() - started, 3), cost_usd=round(cost, 6))


async def run_evals(scenarios: list[dict[str, Any]], *, mode: str,
                    model_factory: Callable[[dict[str, Any]], ModelPort | None] | None = None,
                    repeats: int = 1, live_providers: bool = False,
                    on_result: Callable[[RunResult], None] | None = None) -> list[ScenarioReport]:
    """Run each applicable scenario ``repeats`` times on fresh temporary data roots."""
    reports = []
    for scenario in scenarios:
        if mode not in scenario.get("modes", ["guided", "agent"]):
            continue
        if mode == "agent" and model_factory is None:
            raise ValueError("Agent-mode evals need a model")
        runs = []
        for _ in range(repeats):
            model = model_factory(scenario) if model_factory else None
            if mode == "agent" and model is None:
                break                                     # e.g. no script for this scenario
            with tempfile.TemporaryDirectory(prefix="openepw-eval-", ignore_cleanup_errors=True) as root:
                result = await run_scenario(scenario, mode=mode, model=model, data_root=Path(root),
                                            live_providers=live_providers)
            runs.append(result)
            if on_result:
                on_result(result)
        if not runs:
            continue
        failures: dict[str, int] = {}
        for run in runs:
            for failure in run.failures:
                failures[failure] = failures.get(failure, 0) + 1
        passed = sum(run.passed for run in runs)
        reports.append(ScenarioReport(
            scenario=scenario["id"], title=scenario.get("title", ""), mode=mode, runs=len(runs), passed=passed,
            pass_rate=round(passed / len(runs), 3),
            mean_model_steps=round(statistics.mean(run.model_steps for run in runs), 2),
            mean_seconds=round(statistics.mean(run.seconds for run in runs), 3),
            cost_usd=round(sum(run.cost_usd for run in runs), 6), failures=failures))
    return reports


def report_json(reports: list[ScenarioReport], **context: Any) -> dict[str, Any]:
    runs = sum(report.runs for report in reports)
    passed = sum(report.passed for report in reports)
    return {**context, "runs": runs, "passed": passed,
            "pass_rate": round(passed / runs, 3) if runs else None,
            "cost_usd": round(sum(report.cost_usd for report in reports), 6),
            "scenarios": [asdict(report) for report in reports]}
