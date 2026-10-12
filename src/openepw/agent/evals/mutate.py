"""Mutation runs: switch off one guard at a time and check that the tasks covering it fail.

A mutation patches the running process only (no switches exist in the agent's code, profiles or
CLI). For each mutation, the tasks whose ``covers`` overlap the mutation's are run offline
(guided, and agent with each task's script) under the hosted profile. Tasks that still pass with
the guard off are reported; a mutation no task catches marks a guard the evals do not cover.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from unittest import mock

from ..policy_config import load_policy
from .runner import applies, run_suite, scripted_model
from .schema import Task

Write = Callable[[str], Any]


@dataclass(frozen=True)
class Mutation:
    name: str
    description: str
    covers: tuple[str, ...]
    patches: Callable[[], list[Any]] = field(repr=False)


def _links_off() -> list[Any]:
    return [mock.patch("openepw.agent.session.filter_links", lambda text, links: (text, False))]


def _outside_text_off() -> list[Any]:
    def keep(value: Any, max_chars: int = 0, key: str = "") -> Any:
        return value
    return [mock.patch(f"openepw.agent.{module}.{name}", keep) for module in ("tools", "policy_model", "host")
            for name in ("clean_external", "clean_tool_data")
            if _has(f"openepw.agent.{module}", name)]


def _normalisation_off() -> list[Any]:
    return [mock.patch("openepw.agent.session.normalize_input", lambda text: text)]


def _redaction_off() -> list[Any]:
    return [mock.patch("openepw.agent.session.safe_prompt", lambda text, limit=1000: text)]


def _moderation_off() -> list[Any]:
    async def unchecked(self: Any, kind: str, texts: list[str]) -> tuple[str, tuple[str, ...]]:
        return "ok", ()
    return [mock.patch("openepw.agent.session.AgentSession._moderation", unchecked)]


def _strike_limit_off() -> list[Any]:
    async def nothing(self: Any, action: str, source: str, *, first: bool) -> None:
        return None
    return [mock.patch("openepw.agent.session.AgentSession._strike_limit", nothing)]


def _strike_count_off() -> list[Any]:
    async def show_only(self: Any, source: str, message: str, *, code: str = "OUT_OF_SCOPE", **data: Any) -> bool:
        self.emit("assistant", message, code=code, source=source, strike=None, **data)
        return False
    return [mock.patch("openepw.agent.session.AgentSession.strike", show_only)]


def _short_message_rule_off() -> list[Any]:
    from ..policy_model import DECLINES

    async def always(s: Any, source: str, code: str) -> None:
        await s.strike(source, DECLINES["unrelated"], code=code)
    return [mock.patch("openepw.agent.policy_model.ModelPolicy._decline_unrelated", staticmethod(always))]


def _small_talk_off() -> list[Any]:
    return [mock.patch("openepw.agent.session.small_talk", lambda text: None)]


def _clamp_off() -> list[Any]:
    return [mock.patch("openepw.agent.policy_model.off_topic", lambda *args, **kwargs: False)]


def _readiness_off() -> list[Any]:
    return [mock.patch("openepw.agent.session.claims_ready", lambda text: False)]


def _years_gate_off() -> list[Any]:
    from .. import gates

    original = gates.check_plan_request

    def any_years(facts: Any, request: dict[str, Any]) -> dict[str, Any]:
        stated = sorted(set(facts.years) | set(request.get("years") or []))
        return original(facts.model_copy(update={"years": stated}), request)
    return [mock.patch("openepw.agent.policy_model.check_plan_request", any_years)]


def _host_tool_gate_off() -> list[Any]:
    from ...mcp.access import HOST_TOOLS, MODEL_TOOLS

    return [mock.patch("openepw.agent.policy_model.HOST_TOOLS", frozenset()),
            mock.patch("openepw.agent.policy_model.LEGACY_TOOLS", frozenset()),
            mock.patch("openepw.agent.policy_model.MODEL_TOOLS", frozenset(MODEL_TOOLS) | frozenset(HOST_TOOLS))]


def _approval_gate_off() -> list[Any]:
    from ..interactions import Answer
    from ..session import AgentSession

    original = AgentSession.answer

    async def text_runs(self: Any, answer: Answer) -> None:
        form = self.form
        if form is not None and form.kind == "plan_review" and answer.text:
            answer = Answer(interaction_id=answer.interaction_id, revision=answer.revision, approve=True)
        await original(self, answer)
    return [mock.patch("openepw.agent.session.AgentSession.answer", text_runs)]


def _has(module: str, name: str) -> bool:
    import importlib

    return hasattr(importlib.import_module(module), name)


MUTATIONS = [
    Mutation("links-off", "Model text keeps every link", ("guard.links",), _links_off),
    Mutation("outside-text-off", "Tool data reaches the model uncleaned", ("guard.outside-text",), _outside_text_off),
    Mutation("normalisation-off", "Typed text keeps hidden characters", ("guard.input-normalisation",),
             _normalisation_off),
    Mutation("redaction-off", "Typed keys and paths are not redacted", ("privacy.secrets",), _redaction_off),
    Mutation("moderation-off", "Moderation is skipped (as if every text passed)",
             ("guard.moderation", "guard.moderation-outage"), _moderation_off),
    Mutation("strike-limit-off", "Reaching the strike limit does nothing", ("guard.strikes",), _strike_limit_off),
    Mutation("strike-count-off", "Declines are shown but never counted", ("scope.decline", "guard.strikes"),
             _strike_count_off),
    Mutation("short-message-rule-off", "Short unrelated messages are counted", ("guard.short-messages",),
             _short_message_rule_off),
    Mutation("small-talk-off", "The host never answers small talk", ("scope.conversation",), _small_talk_off),
    Mutation("clamp-off", "Long off-topic replies are shown", ("guard.offtopic-clamp",), _clamp_off),
    Mutation("readiness-off", "Simulation-ready claims are not corrected", ("science.readiness",), _readiness_off),
    Mutation("years-gate-off", "Plans accept years the person never wrote", ("gate.years",), _years_gate_off),
    Mutation("host-tool-gate-off", "The model may call host-only tools", ("gate.host-tools",), _host_tool_gate_off),
    Mutation("approval-gate-off", "Text typed at the plan review counts as Run", ("gate.plan-approval",),
             _approval_gate_off),
]


@contextlib.contextmanager
def applied(mutation: Mutation) -> Iterator[None]:
    with contextlib.ExitStack() as stack:
        for patch in mutation.patches():
            stack.enter_context(patch)
        yield


async def _run(tasks: list[Task]) -> list[dict[str, Any]]:
    security = load_policy("hosted")
    records = await run_suite(tasks, mode="guided", security=security)
    records += await run_suite(tasks, mode="agent", model_factory=scripted_model, security=security)
    return records


async def run_mutations(tasks: list[Task], names: list[str] | None = None, *,
                        write: Write = print) -> list[dict[str, Any]]:
    """Each mutation's covering tasks with the guard off: which runs failed (caught it), which passed."""
    chosen = [mutation for mutation in MUTATIONS if not names or mutation.name in names]
    hosted = load_policy("hosted")
    agent_log = logging.getLogger("openepw.agent")
    level = agent_log.level
    agent_log.setLevel(logging.CRITICAL)                                # expected errors under mutation
    try:
        return await _mutations(tasks, chosen, hosted, write)
    finally:
        agent_log.setLevel(level)


async def _mutations(tasks: list[Task], chosen: list[Mutation], hosted: Any, write: Write) -> list[dict[str, Any]]:
    results = []
    for mutation in chosen:
        covering = [task for task in tasks if set(task.covers) & set(mutation.covers)
                    and any(applies(task, mode, hosted.profile) for mode in ("guided", "agent"))]
        baseline = {(record["task_id"], record["mode"]): record["passed"] for record in await _run(covering)}
        with applied(mutation):
            mutated = await _run(covering)
        caught, missed, crashed = [], [], []
        for record in mutated:
            item = f"{record['task_id']}/{record['mode']}"
            if not baseline.get((record["task_id"], record["mode"]), False):
                continue                                  # failing without the mutation: no evidence
            if record["passed"]:
                missed.append(item)
            elif any(grade["code"] == "RUN_ERROR" for grade in record["grades"]):
                crashed.append(item)                      # a crash shows a broken patch, not coverage
            else:
                failed = sorted({grade["code"] for grade in record["grades"] if not grade["passed"]})
                caught.append(f"{item} ({', '.join(failed)})")
        results.append({"mutation": mutation.name, "description": mutation.description,
                        "covers": list(mutation.covers), "tasks": [task.id for task in covering],
                        "caught_by": caught, "still_passing": missed, "crashed": crashed})
        write(f"{mutation.name:24} {'caught' if caught else 'NOT CAUGHT':10} by {len(caught)} run(s)"
              + (f": {'; '.join(caught)}" if caught else "")
              + (f" | still passing: {', '.join(missed)}" if missed else "")
              + (f" | CRASHED: {', '.join(crashed)}" if crashed else ""))
    return results
