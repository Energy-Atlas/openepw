"""Lint and catalogue the eval tasks.

Lint finds problems the schema cannot: agent tasks without an offline solution, tasks without
coverage, graders without pass and fail fixtures, code checks that name codes the agent never
emits or that a profile cannot emit, checks that cannot apply in the task's modes, and model-input
exclusions with no proof that the data reached the model. The catalogue is a Markdown and HTML
description of every task, a grader glossary and a coverage matrix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from importlib import resources
from pathlib import Path
from typing import Any

from ..policy_config import load_policy
from .graders import REGISTRY
from .schema import Task, coverage_items

# Codes a profile setting decides; a check for them under the wrong profile can never pass or fail.
PROFILE_CODES = {
    "STRIKE_LIMIT": ("strikes.action is warn", lambda policy: policy.strikes.action == "warn"),
    "SESSION_ENDED": ("strikes.action is end_session", lambda policy: policy.strikes.action == "end_session"),
    "MODERATION_FLAG": ("moderation is enabled", lambda policy: policy.moderation.enabled),
    "MODERATION_UNAVAILABLE": ("moderation is enabled", lambda policy: policy.moderation.enabled),
    "KNOWLEDGE_ANSWER": ("knowledge answers are on", lambda policy: policy.scope.knowledge_answers),
}


@dataclass(frozen=True)
class Issue:
    level: str                       # error | warning
    where: str
    message: str


@lru_cache(maxsize=1)
def emitted_codes() -> frozenset[str]:
    """Event codes the agent package can record (read from its source) plus MCP error codes."""
    root = Path(str(resources.files("openepw.agent")))
    codes: set[str] = set()
    for path in root.glob("*.py"):
        codes |= set(re.findall(r"""code=["']([A-Z][A-Z_]+)["']""", path.read_text(encoding="utf-8")))
    from ..session import GUARD_CODES

    codes |= set(GUARD_CODES) | {"GATE_REQUIRED", "TOOL_NOT_ALLOWED", "USE_ASK_TOOL", "INTERNAL_ERROR", "STALE_FORM",
                                 "RUN_ERROR"}
    return frozenset(codes)


@lru_cache(maxsize=1)
def fixtures() -> list[dict[str, Any]]:
    import yaml

    text = resources.files("openepw.agent.evals").joinpath("grader_fixtures.yaml").read_text(encoding="utf-8")
    return list(yaml.safe_load(text)["fixtures"])


def fixture_counts() -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {name: {"pass": 0, "fail": 0} for name in REGISTRY}
    for item in fixtures():
        counts.setdefault(item["grader"], {"pass": 0, "fail": 0})[item["expect"]] += 1
    return counts


def known_tools() -> frozenset[str]:
    from ...mcp.access import HOST_TOOLS, LEGACY_TOOLS, MODEL_TOOLS
    from ..tools import ASK_TOOLS, LOOKUP_TOOLS, SCOPE_TOOLS

    return frozenset(MODEL_TOOLS | HOST_TOOLS | LEGACY_TOOLS | set(ASK_TOOLS) | set(LOOKUP_TOOLS) | set(SCOPE_TOOLS))


FORM_KINDS = frozenset({"text", "choice", "location_review", "product_choice", "map_input", "upload", "plan_review",
                        "request_summary"})


def lint(tasks: list[Task]) -> list[Issue]:
    issues: list[Issue] = []
    for item in fixtures():
        if item["grader"] in REGISTRY and not run_fixture(item)[0]:
            issues.append(Issue("error", f"grader_fixtures.yaml: {item['grader']}",
                                f"a fixture expected to {item['expect']} does not ({item.get('note') or 'no note'})"))
    for name, count in fixture_counts().items():
        if name not in REGISTRY:
            issues.append(Issue("error", f"grader_fixtures.yaml: {name}", "fixture for an unknown grader"))
        elif not (count["pass"] and count["fail"]):
            issues.append(Issue("error", f"grader {name}", f"needs a passing and a failing fixture (has {count})"))
    policies = {name: load_policy(name) for name in ("local", "hosted")}
    known = emitted_codes()
    for task in tasks:
        where = f"{task.id} ({Path(task.source).name})"
        if "agent" in task.modes and task.script is None:
            issues.append(Issue("error", where, "agent task without a script: no offline proof it can be solved"))
        if not task.covers:
            issues.append(Issue("warning", where, "covers nothing (add coverage ids)"))
        if not task.modes or not task.profiles:
            issues.append(Issue("error", where, "no modes or no profiles: the task never runs"))
        if not task.graders:
            issues.append(Issue("warning", where, "no graders of its own (only the always-on ones judge it)"))
        names = {use.grader for use in task.graders}
        if "model_input_excludes" in names and "model_input_contains" not in names:
            issues.append(Issue("warning", where, "model_input_excludes without model_input_contains: nothing proves "
                                                  "the data reached the model"))
        for use in task.graders:
            grader = REGISTRY[use.grader]
            if not set(grader.modes) & set(task.modes):
                issues.append(Issue("warning", where, f"{use.grader} applies only in {', '.join(grader.modes)} mode"))
            if use.mode and use.mode not in task.modes:
                issues.append(Issue("warning", where, f"{use.grader} is for {use.mode} mode, which the task "
                                                      "does not run in"))
            if use.profile and use.profile not in task.profiles:
                issues.append(Issue("warning", where, f"{use.grader} is for profile {use.profile}, which the task "
                                                      "does not run under"))
            if use.grader in ("tools_in_order", "tools_absent"):
                unknown = [tool for tool in use.value or [] if tool not in known_tools()]
                if unknown:
                    issues.append(Issue("error", where, f"{use.grader}: unknown tool(s) {', '.join(unknown)}"))
            if use.grader in ("forms_in_order", "forms_absent"):
                unknown = [kind for kind in use.value or [] if kind not in FORM_KINDS]
                if unknown:
                    issues.append(Issue("error", where, f"{use.grader}: unknown form kind(s) {', '.join(unknown)}"))
            if use.grader not in ("codes_present", "codes_absent"):
                continue
            for code in use.value or []:
                if code not in known:
                    issues.append(Issue("error", where, f"{use.grader}: the agent never records code {code}"))
                    continue
                if code not in PROFILE_CODES:
                    continue
                needs, possible = PROFILE_CODES[code]
                for profile in ([use.profile] if use.profile else task.profiles):
                    if not possible(policies[profile]):
                        level = "error" if use.grader == "codes_present" else "warning"
                        effect = "can never pass" if level == "error" else "can never fail (dead check)"
                        issues.append(Issue(level, where, f"{use.grader} {code} under {profile} {effect}: "
                                                          f"needs {needs}"))
    return issues


def _value(value: Any) -> str:
    return "" if value is None else (", ".join(map(str, value)) if isinstance(value, list) else str(value))


def _conversation(task: Task) -> list[str]:
    lines = [f"Says: {task.user.say}"] + [f"Then says: {text}" for text in task.user.then]
    lines += [f"At {kind}: {_value(answer) if answer is not None else 'stops'}" for kind, answer in task.user.answers.items()]
    if task.setup.upload:
        lines.insert(0, f"Uploads {task.setup.upload.filename} with city: {task.setup.upload.city}")
    if task.setup.moderation != "default":
        lines.insert(0, f"Moderation: {task.setup.moderation}")
    if task.setup.fail_near:
        lines.insert(0, f"Provider outage near: {task.setup.fail_near}")
    return lines


def _graders(task: Task) -> list[tuple[str, str, str, str]]:
    rows = []
    for use in task.graders:
        grader = REGISTRY[use.grader]
        rows.append((grader.code, grader.description, _value(use.value), (use.severity or grader.severity)
                     + (f", {use.profile} only" if use.profile else "")))
    return rows


def _status(summary: dict[str, Any] | None) -> dict[str, str]:
    if not summary:
        return {}
    return {task["task_id"]: f"{task['status']} ({task['passed']}/{task['trials']})" for task in summary["tasks"]}


def markdown(tasks: list[Task], summary: dict[str, Any] | None = None) -> str:
    status = _status(summary)
    always = [grader for grader in REGISTRY.values() if grader.always]
    lines = ["# Agent eval tasks", "", f"{len(tasks)} tasks. Every trial is also graded by the always-on graders: "
             + ", ".join(f"`{grader.code}`" for grader in always) + ".", ""]
    if summary:
        lines += [f"Pass rates from run `{summary['pins'].get('run_id')}`.", ""]
    lines += ["| Task | Title | Suite | Tags | Modes | Covers | Last run |", "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| [{task.id}](#{task.id.lower()}) | {task.title} | {task.suite} | {', '.join(task.tags)} | "
              f"{', '.join(task.modes)} | {', '.join(task.covers)} | {status.get(task.id, '—')} |" for task in tasks]
    for task in tasks:
        lines += ["", f"## {task.id}", "", f"**{task.title}**", "", task.purpose, "",
                  f"Suite {task.suite}; tags {', '.join(task.tags) or '—'}; modes {', '.join(task.modes)}; profiles "
                  f"{', '.join(task.profiles)}; live trials {task.live_trials()}; offline solution: "
                  f"{'yes' if task.script is not None else 'no'}.", "", "Conversation:", ""]
        lines += [f"- {line}" for line in _conversation(task)]
        lines += ["", "| Code | Checks | Value | Severity |", "| --- | --- | --- | --- |"]
        lines += [f"| `{code}` | {text} | {value} | {severity} |" for code, text, value, severity in _graders(task)]
    counts = fixture_counts()
    lines += ["", "## Grader glossary", "", "| Code | Grader | Checks | Why | Severity | Runs | Value | Fixtures |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| `{grader.code}` | {grader.name} | {grader.description} | {grader.why} | {grader.severity} | "
              f"{'always' if grader.always else 'when listed'} ({', '.join(grader.modes)}) | {grader.value_text()} | "
              f"{counts.get(grader.name, {}).get('pass', 0)} pass, {counts.get(grader.name, {}).get('fail', 0)} fail |"
              for grader in REGISTRY.values()]
    lines += ["", "## Coverage", "", "| Covers | Rule | Source | Tasks |", "| --- | --- | --- | --- |"]
    for item, info in coverage_items().items():
        covering = [task.id for task in tasks if item in task.covers]
        lines.append(f"| `{item}` | {info['text']} | {info.get('source', '')} | {', '.join(covering) or '**none**'} |")
    return "\n".join(lines) + "\n"


def html(tasks: list[Task], summary: dict[str, Any] | None = None) -> str:
    from .report import CSS

    status = _status(summary)
    rows = "".join(f"<tr><td><a href=#{escape(task.id)}>{escape(task.id)}</a></td><td>{escape(task.title)}</td>"
                   f"<td>{escape(task.suite)}</td><td>{escape(', '.join(task.tags))}</td><td>{escape(', '.join(task.modes))}"
                   f"</td><td>{escape(', '.join(task.covers))}</td><td>{escape(status.get(task.id, '—'))}</td></tr>"
                   for task in tasks)
    sections = []
    for task in tasks:
        graders = "".join(f"<tr><td><code>{escape(code)}</code></td><td>{escape(text)}</td><td>{escape(value)}</td>"
                          f"<td>{escape(severity)}</td></tr>" for code, text, value, severity in _graders(task))
        sections.append(
            f"<section id={escape(task.id)}><h3>{escape(task.id)} — {escape(task.title)}</h3><p>{escape(task.purpose)}</p>"
            f"<p class=muted>Suite {escape(task.suite)} · tags {escape(', '.join(task.tags) or '—')} · modes "
            f"{escape(', '.join(task.modes))} · profiles {escape(', '.join(task.profiles))} · live trials "
            f"{task.live_trials()} · offline solution {'yes' if task.script is not None else 'no'}</p><ul>"
            + "".join(f"<li>{escape(line)}</li>" for line in _conversation(task))
            + f"</ul><table><tr><th>Code</th><th>Checks</th><th>Value</th><th>Severity</th></tr>{graders}</table></section>")
    counts = fixture_counts()
    glossary = "".join(
        f"<tr><td><code>{escape(grader.code)}</code></td><td>{escape(grader.name)}</td><td>{escape(grader.description)}"
        f"</td><td>{escape(grader.why)}</td><td>{grader.severity}</td><td>{'always' if grader.always else 'listed'} "
        f"({escape(', '.join(grader.modes))})</td><td>{counts.get(grader.name, {}).get('pass', 0)}/"
        f"{counts.get(grader.name, {}).get('fail', 0)}</td></tr>" for grader in REGISTRY.values())
    coverage = "".join(
        f"<tr><td><code>{escape(item)}</code></td><td>{escape(info['text'])}</td><td>{escape(info.get('source', ''))}</td>"
        f"<td>{', '.join(f'<a href=#{escape(task.id)}>{escape(task.id)}</a>' for task in tasks if item in task.covers) or '<b class=fail>none</b>'}"
        f"</td></tr>" for item, info in coverage_items().items())
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>Agent eval tasks</title><style>{CSS}</style></head>"
            f"<body><main><h1>Agent eval tasks</h1><p class=muted>{len(tasks)} tasks</p><div class=wrap><table><tr>"
            f"<th>Task</th><th>Title</th><th>Suite</th><th>Tags</th><th>Modes</th><th>Covers</th><th>Last run</th></tr>"
            f"{rows}</table></div><h2>Tasks</h2>{''.join(sections)}<h2>Grader glossary</h2><div class=wrap><table><tr>"
            f"<th>Code</th><th>Grader</th><th>Checks</th><th>Why</th><th>Severity</th><th>Runs</th>"
            f"<th>Fixtures pass/fail</th></tr>{glossary}</table></div><h2>Coverage</h2><div class=wrap><table><tr>"
            f"<th>Covers</th><th>Rule</th><th>Source</th><th>Tasks</th></tr>{coverage}</table></div></main></body></html>")


def write_catalog(tasks: list[Task], folder: Path, summary: dict[str, Any] | None = None) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    md, page = folder / "catalog.md", folder / "catalog.html"
    md.write_text(markdown(tasks, summary), encoding="utf-8")
    page.write_text(html(tasks, summary), encoding="utf-8")
    return [md, page]


def run_fixture(item: dict[str, Any]) -> tuple[bool, Any]:
    """Grade one fixture with its grader alone; (expectation met, verdict)."""
    from .graders import Context, View

    context = item.get("context") or {}
    grader = REGISTRY[item["grader"]]
    ctx = Context(mode=context.get("mode", "agent"), links=load_policy(context.get("profile", "hosted")).links)
    passed, evidence, detail = grader.check(View(item["record"]), grader.validate(item.get("value")), ctx)
    return passed == (item["expect"] == "pass"), (passed, evidence, detail)
