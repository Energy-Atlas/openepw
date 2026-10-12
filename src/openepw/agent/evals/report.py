"""A self-contained HTML report of one eval run (no scripts, no external files; works offline).

Order of reading: what was tested (pins), totals, the comparison with the baseline (newly
failing first), suites and tags, failures grouped by grader, the task table, and a page section
per task with each trial's verdicts and its trace, the deciding entries highlighted.
"""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from .graders import REGISTRY

MODEL_ITEMS_CHARS = 4000             # model input shown per call in the report (the record has it all)

CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#deded8;--card:#ffffff;--pass:#1f7a3a;--fail:#b3261e;
--flaky:#9a6200;--soft:#5b5bd6;--hl:#fff3c4;--code:#f2f2ee}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;
--line:#34332f;--card:#1f1f1d;--pass:#5fc27e;--fail:#ff8a80;--flaky:#f2b84b;--soft:#a5a5ff;--hl:#4a4020;--code:#262624}}
:root[data-theme="dark"]{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--card:#1f1f1d;--pass:#5fc27e;
--fail:#ff8a80;--flaky:#f2b84b;--soft:#a5a5ff;--hl:#4a4020;--code:#262624}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;margin:0}
main{max-width:1100px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border-bottom:1px solid var(--line);padding:4px 6px;
text-align:left;vertical-align:top}th{color:var(--muted);font-weight:600}
.wrap{overflow-x:auto}.muted{color:var(--muted)}code,pre{background:var(--code);border-radius:4px}
code{padding:0 3px}pre{padding:8px;white-space:pre-wrap;word-break:break-word;max-height:360px;overflow:auto}
.cards{display:flex;flex-wrap:wrap;gap:10px}.card{background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:8px 12px;min-width:140px}.card b{display:block;font-size:20px}
.pill{border-radius:10px;padding:0 8px;font-size:12px;font-weight:600;border:1px solid currentColor}
.pass{color:var(--pass)}.fail{color:var(--fail)}.flaky{color:var(--flaky)}.soft{color:var(--soft)}
.provider_error{color:var(--muted)}
.hl{background:var(--hl)}details{margin:4px 0}summary{cursor:pointer}
ol.trace{padding-left:0;list-style:none;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
ol.trace li{padding:2px 4px;border-left:3px solid transparent}ol.trace li.hl{border-left-color:var(--fail)}
"""


def _status(status: str) -> str:
    label = "provider error" if status == "provider_error" else status
    return f'<span class="pill {escape(status)}">{escape(label)}</span>'


def _rate(group: dict[str, Any]) -> str:
    rate = group.get("pass_rate")
    low, high = group.get("interval95", [0, 1])
    return "—" if rate is None else f"{rate:.0%} <span class=muted>({low:.0%}–{high:.0%})</span>"


def _pins(pins: dict[str, Any]) -> str:
    git = pins.get("git") or {}
    commit = str(git.get("commit") or "unknown")
    dirty = " <span class=fail>(uncommitted changes, diff " + escape(str(git.get("diff_sha256"))) + ")</span>" \
        if git.get("dirty") else ""
    rows = [("Run", pins.get("run_id")), ("Started", pins.get("started_at")),
            ("Commit", f"{escape(commit[:12])} on {escape(str(git.get('branch')))}{dirty}"),
            ("Mode", pins.get("mode")), ("Model", pins.get("model")), ("Trials", pins.get("trials")),
            ("Providers", pins.get("providers")),
            ("Profile", f"{pins.get('profile')} (digest {pins.get('profile_digest')})"),
            ("Tasks hash", pins.get("tasks_hash")), ("System prompt", ", ".join(pins.get("system_sha256") or []) or "—"),
            ("Tool list", ", ".join(pins.get("tools_sha256") or []) or "—"),
            ("openepw / Python", f"{pins.get('package_version')} / {pins.get('python')}")]
    body = "".join(f"<tr><th>{escape(name)}</th><td>{value if name == 'Commit' else escape(str(value))}</td></tr>"
                   for name, value in rows)
    return f'<div class=wrap><table>{body}</table></div>'


def _comparison(diff: dict[str, Any] | None) -> str:
    if not diff:
        return "<p class=muted>No baseline: this is the first run of its kind, or none was given.</p>"
    parts = [f"<p>Baseline <code>{escape(str(diff['baseline']))}</code>: pass rate "
             f"{escape(str(diff['pass_rate'][0]))} → {escape(str(diff['pass_rate'][1]))}.</p>"]
    for label, field, css in (("Newly failing", "newly_failing", "fail"), ("Flaky", "flaky", "flaky"),
                              ("Still failing", "still_failing", "fail"), ("Fixed", "fixed", "pass"),
                              ("Task definition changed", "task_changed", "muted"), ("Added", "added", "muted"),
                              ("Removed", "removed", "muted")):
        if diff.get(field):
            links = ", ".join(escape(task) if field == "removed" else f'<a href="#{escape(task)}">{escape(task)}</a>'
                              for task in diff[field])
            parts.append(f"<p><b class={css}>{label}:</b> {links}</p>")
    if diff.get("pin_changes"):
        rows = "".join(f"<tr><td>{escape(name)}</td><td>{escape(str(old))}</td><td>{escape(str(new))}</td></tr>"
                       for name, (old, new) in diff["pin_changes"].items())
        parts.append(f"<table><tr><th>Changed</th><th>Baseline</th><th>Now</th></tr>{rows}</table>")
    return "".join(parts)


def _groups(title: str, groups: dict[str, Any]) -> str:
    rows = "".join(f"<tr><td>{escape(name)}</td><td>{group['tasks_all_passed']}/{group['tasks']}</td>"
                   f"<td>{group['passed']}/{group['trials']}</td><td>{_rate(group)}</td></tr>"
                   for name, group in groups.items())
    return (f"<h3>{escape(title)}</h3><table><tr><th>{escape(title[:-1])}</th><th>Tasks all passing</th>"
            f"<th>Trials passed</th><th>Pass rate (95% interval)</th></tr>{rows}</table>")


def _failures(tasks: list[dict[str, Any]]) -> str:
    by_code: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for severity, field in (("hard", "hard_failures"), ("soft", "soft_failures")):
            for code, count in task[field].items():
                entry = by_code.setdefault(code, {"severity": severity, "count": 0, "tasks": []})
                entry["count"] += count
                entry["tasks"].append(task["task_id"])
    if not by_code:
        return "<p class=pass>No grader failed.</p>"
    describe = {grader.code: grader.description for grader in REGISTRY.values()}
    rows = "".join(
        f"<tr><td><code>{escape(code)}</code></td><td class={'fail' if item['severity'] == 'hard' else 'soft'}>"
        f"{item['severity']}</td><td>{item['count']}</td><td>{escape(describe.get(code, 'the trial crashed'))}</td>"
        f"<td>{', '.join(f'<a href=#{escape(task)}>{escape(task)}</a>' for task in sorted(set(item['tasks'])))}</td></tr>"
        for code, item in sorted(by_code.items(), key=lambda pair: (pair[1]["severity"], -pair[1]["count"])))
    return (f"<div class=wrap><table><tr><th>Code</th><th>Severity</th><th>Failures</th><th>Checks</th>"
            f"<th>Tasks</th></tr>{rows}</table></div>")


def _task_table(tasks: list[dict[str, Any]]) -> str:
    rows = "".join(
        f"<tr><td><a href=#{escape(task['task_id'])}>{escape(task['task_id'])}</a></td><td>{escape(task['title'])}</td>"
        f"<td>{escape(', '.join(task['tags']))}</td><td>{task['passed']}/{task['trials']}</td>"
        f"<td>{_status(task['status'])}</td><td>{task['model_steps']['p50']:g} / {task['model_steps']['p95']:g}</td>"
        f"<td>{task['seconds']['p50']:.1f} / {task['seconds']['p95']:.1f}</td><td>${task['cost_usd']:.4f}</td></tr>"
        for task in tasks)
    return (f"<div class=wrap><table><tr><th>Task</th><th>Title</th><th>Tags</th><th>Passed</th><th>Status</th>"
            f"<th>Steps p50/p95</th><th>Seconds p50/p95</th><th>Cost</th></tr>{rows}</table></div>")


def _entry(index: int, entry: dict[str, Any], highlight: set[int]) -> str:
    kind = entry.get("type", "")
    data = entry.get("data") or {}
    css = ' class="hl"' if index in highlight else ""
    if kind == "model":
        reply = data.get("reply") or {}
        calls = ", ".join(call.get("name", "") for call in reply.get("tool_calls") or [])
        said = escape((reply.get("text") or "")[:300])
        items = json.dumps(data.get("items") or [], ensure_ascii=False, indent=1)
        cut = "" if len(items) <= MODEL_ITEMS_CHARS else f"\n… ({len(items) - MODEL_ITEMS_CHARS} more characters in the record)"
        return (f"<li{css}>#{index} <b>model</b> → {escape(calls) or 'text'} {said} "
                f"<span class=muted>{data.get('input_tokens', 0)}+{data.get('output_tokens', 0)} tokens, "
                f"${float(data.get('cost_usd') or 0):.4f}</span><details><summary>what the model was sent</summary>"
                f"<pre>{escape(items[:MODEL_ITEMS_CHARS] + cut)}</pre></details></li>")
    if kind == "outcome":
        return (f"<li{css}>#{index} <b>outcome</b><details><summary>facts, strikes, jobs</summary>"
                f"<pre>{escape(json.dumps(data, ensure_ascii=False, indent=1))}</pre></details></li>")
    label = kind
    if kind == "tool":
        label = f"tool {data.get('phase')} {data.get('tool')} by {data.get('by', 'host')}"
    elif kind == "form":
        form = data.get("form") or {}
        label = f"form {form.get('kind')} ({form.get('gate')})"
    codes = [code for code in [data.get("code"), *data.get("guards", [])] if code]
    tail = f" <code>{escape(' '.join(codes))}</code>" if codes else ""
    return f"<li{css}>#{index} <b>{escape(label)}</b>{tail} {escape((entry.get('text') or '')[:500])}</li>"


def _trial(record: dict[str, Any]) -> str:
    grades = record.get("grades") or []
    failed = [grade for grade in grades if not grade["passed"]]
    highlight = {index for grade in failed for index in grade.get("evidence", [])}
    rows = "".join(
        f"<tr><td><code>{escape(grade['code'])}</code></td><td>{escape(grade['grader'])}</td>"
        f"<td class={'pass' if grade['passed'] else ('fail' if grade['severity'] == 'hard' else 'soft')}>"
        f"{'pass' if grade['passed'] else 'fail'} ({grade['severity']})</td><td>{escape(grade.get('detail', ''))}"
        f"{' — entries ' + ', '.join(f'#{index}' for index in grade.get('evidence', [])) if not grade['passed'] and grade.get('evidence') else ''}"
        f"</td></tr>" for grade in sorted(grades, key=lambda grade: grade["passed"]))
    metric = record.get("metrics") or {}
    trace = "".join(_entry(index, entry, highlight) for index, entry in enumerate(record.get("trace") or []))
    status = record.get("status") or ("pass" if record.get("passed") else "fail")
    retried = (f" (retried after a {escape(str(record['retried_after']))} error)"
               if record.get("retried_after") else "")
    return (f"<details{' open' if failed and not record.get('passed') else ''}><summary>Trial {record.get('trial')} "
            f"{_status(status)}{retried} <span class=muted>{metric.get('model_steps', 0)} steps, "
            f"{metric.get('seconds', 0):.1f}s, "
            f"${float(metric.get('cost_usd') or 0):.4f}</span></summary>"
            f"<table><tr><th>Code</th><th>Grader</th><th>Verdict</th><th>Detail and evidence</th></tr>{rows}</table>"
            f"<details><summary>Trace ({len(record.get('trace') or [])} entries)</summary><ol class=trace>{trace}</ol>"
            f"</details></details>")


def render(summary: dict[str, Any], records: list[dict[str, Any]], diff: dict[str, Any] | None = None,
           purposes: dict[str, str] | None = None) -> str:
    pins, totals, tasks = summary["pins"], summary["totals"], summary["tasks"]
    sections = []
    for task in tasks:
        trials = [record for record in records if record["task_id"] == task["task_id"]
                  and record["mode"] == task["mode"]]
        purpose = (purposes or {}).get(task["task_id"])
        sections.append(
            f"<section id={escape(task['task_id'])}><h3>{escape(task['task_id'])} — {escape(task['title'])} "
            f"{_status(task['status'])}</h3>" + (f"<p class=muted>{escape(purpose)}</p>" if purpose else "")
            + f"<p class=muted>pass@{task['trials']}: {'yes' if task['pass_at_k'] else 'no'} · "
            f"pass^{task['trials']}: {'yes' if task['pass_all_k'] else 'no'} · strikes (mean) {task['strikes_mean']}"
            f" · guard codes {escape(', '.join(f'{code}×{count}' for code, count in task['codes'].items()) or 'none')}</p>"
            + "".join(_trial(record) for record in trials) + "</section>")
    cards = (f"<div class=cards><div class=card>Pass rate<b>{_rate(totals)}</b></div>"
             f"<div class=card>Tasks all passing<b>{totals['tasks_all_passed']}/{totals['tasks']}</b></div>"
             f"<div class=card>Trials passed<b>{totals['passed']}/{totals['trials']}</b></div>"
             f"<div class=card>Model cost<b>${totals['cost_usd']:.4f}</b></div>"
             f"<div class=card>Tokens<b>{totals['input_tokens'] + totals['output_tokens']:,}</b></div>"
             f"<div class=card>Provider errors<b>{totals.get('provider_errors', 0)}</b><span class=muted>"
             f"{totals.get('retried', 0)} retried; left out of pass rates</span></div></div>")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>openepw eval report</title><style>{CSS}</style>"
            f"</head><body><main><h1>openepw eval report</h1><p class=muted>{escape(str(pins.get('run_id')))}</p>"
            f"<h2>What was tested</h2>{_pins(pins)}<h2>Totals</h2>{cards}"
            f"<h2>Compared with the baseline</h2>{_comparison(diff)}"
            f"<h2>Suites and tags</h2>{_groups('Suites', summary['suites'])}{_groups('Tags', summary['tags'])}"
            f"<h2>Failures by grader</h2>{_failures(tasks)}<h2>Tasks</h2>{_task_table(tasks)}"
            f"<h2>Task details</h2>{''.join(sections)}"
            f"<p class=muted>Hard graders fail a trial; soft graders are tracked only. Reading rule: a hard failure "
            f"is an agent or guard bug; a soft drop means read the traces; flaky means run more trials; a failure "
            f"that looks wrong means suspect the grader and check its fixtures.</p></main></body></html>")


def write_report(path: Path, summary: dict[str, Any], records: list[dict[str, Any]],
                 diff: dict[str, Any] | None = None, purposes: dict[str, str] | None = None) -> Path:
    path.write_text(render(summary, records, diff, purposes), encoding="utf-8")
    return path
