"""Metrics over trial records, and the comparison of two eval runs.

Per task: pass rate, pass@k (at least one of k trials passed), pass^k (all k passed), each
grader's failures, and distributions of steps, tool calls, tokens, cost and time. Per suite and
tag: the trial pass rate with a Wilson 95% interval. A comparison lists tasks that newly fail,
are fixed, are flaky (mixed results), were added or removed, and grader codes that changed.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

Z95 = 1.959964


def wilson(passed: int, total: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for a pass rate (0..1); (0, 1) with no trials."""
    if total == 0:
        return 0.0, 1.0
    rate = passed / total
    centre = rate + z * z / (2 * total)
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    denominator = 1 + z * z / total
    return round(max(0.0, (centre - margin) / denominator), 3), round(min(1.0, (centre + margin) / denominator), 3)


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile (share in 0..1); 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def _spread(values: list[float]) -> dict[str, float]:
    return {"p50": round(percentile(values, 0.5), 3), "p95": round(percentile(values, 0.95), 3),
            "mean": round(sum(values) / len(values), 3) if values else 0.0}


def task_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One task's trials (same task, mode and profile)."""
    first = records[0]
    passed = sum(1 for record in records if record.get("passed"))
    graders: dict[str, dict[str, Any]] = {}
    hard: dict[str, int] = {}
    soft: dict[str, int] = {}
    for record in records:
        for verdict in record.get("grades") or []:
            entry = graders.setdefault(verdict["grader"], {"code": verdict["code"], "severity": verdict["severity"],
                                                           "trials": 0, "failed": 0})
            entry["trials"] += 1
            if not verdict["passed"]:
                entry["failed"] += 1
                bucket = hard if verdict["severity"] == "hard" else soft
                bucket[verdict["code"]] = bucket.get(verdict["code"], 0) + 1
    codes: dict[str, int] = {}
    for record in records:
        for code, count in (record.get("metrics") or {}).get("codes", {}).items():
            codes[code] = codes.get(code, 0) + count
    metric = [record.get("metrics") or {} for record in records]
    return {"task_id": first["task_id"], "title": first.get("title", ""), "suite": first.get("suite", "regression"),
            "tags": first.get("tags", []), "mode": first["mode"], "profile": first.get("profile"),
            "task_hash": first.get("task_hash"), "trials": len(records), "passed": passed,
            "pass_rate": round(passed / len(records), 3), "pass_at_k": passed > 0, "pass_all_k": passed == len(records),
            "status": "pass" if passed == len(records) else ("fail" if passed == 0 else "flaky"),
            "hard_failures": hard, "soft_failures": soft, "graders": graders,
            "model_steps": _spread([float(item.get("model_steps", 0)) for item in metric]),
            "tool_calls": _spread([float(item.get("tool_calls", 0)) for item in metric]),
            "seconds": _spread([float(item.get("seconds", 0.0)) for item in metric]),
            "input_tokens": sum(int(item.get("input_tokens", 0)) for item in metric),
            "output_tokens": sum(int(item.get("output_tokens", 0)) for item in metric),
            "cost_usd": round(sum(float(item.get("cost_usd", 0.0)) for item in metric), 6),
            "codes": codes, "strikes_mean": round(sum(int(item.get("strikes", 0)) for item in metric) / len(metric), 2),
            "fallbacks": sum(1 for item in metric if item.get("fallback"))}


def _group(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    trials = sum(task["trials"] for task in tasks)
    passed = sum(task["passed"] for task in tasks)
    low, high = wilson(passed, trials)
    return {"tasks": len(tasks), "tasks_all_passed": sum(1 for task in tasks if task["pass_all_k"]),
            "trials": trials, "passed": passed, "pass_rate": round(passed / trials, 3) if trials else None,
            "interval95": [low, high]}


def summarize(records: list[dict[str, Any]], pins: dict[str, Any]) -> dict[str, Any]:
    """The run summary written beside the trial records."""
    by_task: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for record in records:
        by_task.setdefault((record["task_id"], record["mode"], str(record.get("profile"))), []).append(record)
    tasks = [task_summary(items) for items in by_task.values()]
    suites: dict[str, list[dict[str, Any]]] = {}
    tags: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        suites.setdefault(task["suite"], []).append(task)
        for tag in task["tags"] or ["untagged"]:
            tags.setdefault(tag, []).append(task)
    def model_hashes(name: str) -> list[str]:
        # Calls offered no tools (the summary after a run) are left out of the tool-list hashes.
        return sorted({str(value) for record in records for entry in record.get("trace", [])
                       if entry.get("type") == "model" and (value := (entry.get("data") or {}).get(name))
                       and (name != "tools_sha256" or (entry.get("data") or {}).get("tools"))})
    hashes, tool_hashes = model_hashes("system_sha256"), model_hashes("tools_sha256")
    return {"pins": {**pins, "system_sha256": hashes, "tools_sha256": tool_hashes},
            "totals": {**_group(tasks), "cost_usd": round(sum(task["cost_usd"] for task in tasks), 6),
                       "input_tokens": sum(task["input_tokens"] for task in tasks),
                       "output_tokens": sum(task["output_tokens"] for task in tasks)},
            "suites": {name: _group(items) for name, items in sorted(suites.items())},
            "tags": {name: _group(items) for name, items in sorted(tags.items())},
            "tasks": sorted(tasks, key=lambda task: (int(task["task_id"][1:]), task["mode"]))}


def load_summary(path: str | Path) -> dict[str, Any]:
    """A summary from a run folder or a summary.json path."""
    file = Path(path)
    if file.is_dir():
        file = file / "summary.json"
    return dict(json.loads(file.read_text(encoding="utf-8")))


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """What changed from a baseline run to the current one."""
    def key(task: dict[str, Any]) -> tuple[str, str, str]:
        return task["task_id"], task["mode"], str(task.get("profile"))
    before = {key(task): task for task in baseline.get("tasks", [])}
    after = {key(task): task for task in current.get("tasks", [])}
    newly_failing, fixed, flaky, still_failing, changed_task = [], [], [], [], []
    for item, task in after.items():
        old = before.get(item)
        if task["status"] == "flaky":
            flaky.append(task["task_id"])
        if old is None:
            continue
        if old.get("task_hash") != task.get("task_hash"):
            changed_task.append(task["task_id"])
        if old["pass_all_k"] and not task["pass_all_k"]:
            newly_failing.append(task["task_id"])
        elif not old["pass_all_k"] and task["pass_all_k"]:
            fixed.append(task["task_id"])
        elif not task["pass_all_k"]:
            still_failing.append(task["task_id"])
    codes_before: dict[str, int] = {}
    codes_after: dict[str, int] = {}
    for tasks, counts in ((baseline.get("tasks", []), codes_before), (current.get("tasks", []), codes_after)):
        for task in tasks:
            for code, count in {**task.get("hard_failures", {}), **task.get("soft_failures", {})}.items():
                counts[code] = counts.get(code, 0) + count
    grader_changes = {code: [codes_before.get(code, 0), codes_after.get(code, 0)]
                      for code in sorted(set(codes_before) | set(codes_after))
                      if codes_before.get(code, 0) != codes_after.get(code, 0)}
    pins_before, pins_after = baseline.get("pins", {}), current.get("pins", {})
    pin_changes = {name: [pins_before.get(name), pins_after.get(name)]
                   for name in ("model", "profile", "profile_digest", "tasks_hash", "system_sha256", "tools_sha256",
                                "providers", "mode")
                   if pins_before.get(name) != pins_after.get(name)}
    commit_before = (pins_before.get("git") or {}).get("commit")
    commit_after = (pins_after.get("git") or {}).get("commit")
    if commit_before != commit_after:
        pin_changes["commit"] = [commit_before, commit_after]
    return {"baseline": pins_before.get("run_id"), "current": pins_after.get("run_id"),
            "pin_changes": pin_changes, "newly_failing": newly_failing, "fixed": fixed, "flaky": flaky,
            "still_failing": still_failing, "task_changed": changed_task,
            "added": sorted({item[0] for item in after} - {item[0] for item in before}),
            "removed": sorted({item[0] for item in before} - {item[0] for item in after}),
            "grader_changes": grader_changes,
            "pass_rate": [baseline.get("totals", {}).get("pass_rate"), current.get("totals", {}).get("pass_rate")]}


def compare_text(diff: dict[str, Any]) -> list[str]:
    lines = [f"Baseline {diff['baseline']} → current {diff['current']}: pass rate "
             f"{diff['pass_rate'][0]} → {diff['pass_rate'][1]}"]
    for name, (old, new) in diff["pin_changes"].items():
        lines.append(f"  changed {name}: {old} → {new}")
    for label, field in (("Newly failing", "newly_failing"), ("Flaky", "flaky"), ("Still failing", "still_failing"),
                         ("Fixed", "fixed"), ("Task definition changed", "task_changed"), ("Added", "added"),
                         ("Removed", "removed")):
        if diff[field]:
            lines.append(f"{label}: {', '.join(diff[field])}")
    for code, (old, new) in diff["grader_changes"].items():
        lines.append(f"  {code}: {old} → {new} failures")
    if len(lines) == 1 + len(diff["pin_changes"]):
        lines.append("No task changed status.")
    return lines
