"""`openepw eval`: run tasks and write records, a summary and a report; compare runs; lint and
catalogue the tasks; check that the graders catch disabled guards (mutate)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..model_port import DEFAULT_MODEL, ModelPort, OpenAIModel, load_openai_key
from ..moderation import OpenAIModeration
from ..policy_config import SecurityPolicy, load_policy
from .metrics import compare, compare_text, load_summary, summarize
from .records import new_run_id, run_pins, scrub, write_record
from .report import write_report
from .runner import run_suite, scripted_model
from .schema import Task, TaskError, load_tasks, tasks_hash

Write = Callable[[str], Any]


def select(tasks: list[Task], ids: list[str] | None) -> list[Task]:
    if not ids:
        return tasks
    wanted = {item.upper() for item in ids}
    return [task for task in tasks if task.id.upper() in wanted]


def latest_run(evals_dir: Path, *, mode: str, model: str, profile: str, tasks_hash: str, providers: str,
               exclude: str = "") -> Path | None:
    """The newest earlier run of the same tasks, mode, model, profile and providers (the default
    baseline), so a subset run never becomes the baseline of a full run or the reverse."""
    candidates = []
    for summary in evals_dir.glob("*/summary.json"):
        try:
            pins = json.loads(summary.read_text(encoding="utf-8")).get("pins", {})
        except (OSError, ValueError):
            continue
        wanted = (mode, model, profile, tasks_hash, providers)
        found = (pins.get("mode"), pins.get("model"), pins.get("profile"), pins.get("tasks_hash"), pins.get("providers"))
        if found == wanted and pins.get("run_id") != exclude:
            candidates.append((pins.get("started_at") or "", summary.parent))
    return max(candidates)[1] if candidates else None


async def main_run(*, mode: str = "guided", scripted: bool = False, live: bool = False,
                   task_ids: list[str] | None = None, trials: int | None = None, model: str | None = None,
                   max_cost: float = 1.0, live_providers: bool = False, tasks_path: Path | None = None,
                   evals_dir: Path = Path(".local/openepw/evals"), output_dir: Path | None = None,
                   baseline: Path | None = None, env_file: str | Path | None = ".env", write: Write = print,
                   security: SecurityPolicy | None = None) -> int:
    """Returns 0 when every trial passed, 1 when any failed, 2 when the eval could not start."""
    try:
        tasks = select(load_tasks(tasks_path), task_ids)
    except TaskError as error:
        write(f"Task error: {error}")
        return 2
    if not tasks:
        write("No tasks matched.")
        return 2
    factory: Callable[[Task], ModelPort | None] | None = None
    live_model: OpenAIModel | None = None
    if mode == "agent" and scripted:
        factory = scripted_model
    elif mode == "agent" and not live:
        write("Agent-mode evals call the OpenAI API: add --live (spend capped by --max-cost) "
              "or use --scripted to run offline.")
        return 2
    elif mode == "agent":
        key = load_openai_key(env_file)
        if not key:
            write("Live agent evals need OPENAI_API_KEY (environment or .env); use --scripted to run offline.")
            return 2
        live_model = OpenAIModel(key, model=model or DEFAULT_MODEL, max_cost_usd=max_cost)
        shared = live_model

        def factory(task: Task) -> ModelPort | None:
            return shared
    label = "scripted" if scripted else (live_model.name if live_model else "none")
    security = security or load_policy("local")
    moderation = None                                   # offline: each trial uses the stub
    if live_model is not None and security.moderation.enabled:
        moderation = OpenAIModeration(load_openai_key(env_file) or "", model=security.moderation.model)

    def count(task: Task) -> int:
        if trials is not None:
            return trials
        return task.live_trials() if live_model is not None else 1
    trial_policy = (f"{trials} per task" if trials is not None
                    else "live: 3 per task, 5 for safety tasks" if live_model is not None else "1 per task (offline)")
    run_id = new_run_id(mode, label)
    pins = run_pins(run_id=run_id, mode=mode, model=label, providers="live" if live_providers else "stubbed",
                    security=security, tasks_hash=tasks_hash(tasks), trials=trial_policy)
    folder = output_dir or evals_dir / run_id
    if (folder / "trials.jsonl").exists():
        write(f"{folder} already holds a run (trials.jsonl); choose another --output-dir.")
        return 2
    folder.mkdir(parents=True, exist_ok=True)
    git = pins["git"]
    write(f"openepw eval · {run_id} · model {label} · trials {trial_policy} · providers {pins['providers']} · "
          f"profile {security.profile} ({security.digest}) · commit {str(git['commit'])[:12]}"
          + (" (uncommitted changes)" if git.get("dirty") else ""))

    def show(record: dict[str, Any]) -> None:
        write_record(folder / "trials.jsonl", record)
        failed = [grade["code"] for grade in record["grades"] if not grade["passed"]]
        status = "pass" if record["passed"] else "FAIL " + ",".join(failed)
        if record.get("status") == "provider_error":
            status = "PROVIDER ERROR (not counted)"
        elif record.get("retried_after"):
            status += f" (retried after a {record['retried_after']} error)"
        soft = [grade["code"] for grade in record["grades"] if not grade["passed"] and grade["severity"] == "soft"]
        if record["passed"] and soft:
            status = "pass (soft: " + ",".join(soft) + ")"
        metric = record["metrics"]
        write(f"{record['task_id']:4} #{record['trial']} {record['mode']:6} {status:40} steps={metric['model_steps']:<2} "
              f"{metric['seconds']:6.1f}s ${metric['cost_usd']:.4f}")
    records = await run_suite(tasks, mode=mode, model_factory=factory, trials=count, live_providers=live_providers,
                              security=security, moderation=moderation, pins=pins, on_record=show)
    if not records:
        write(f"No task applies to {mode} mode under the {security.profile} profile"
              + (" (or no task has a script)." if scripted else "."))
        return 2
    summary = summarize(records, pins)
    (folder / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    base = baseline or latest_run(evals_dir, mode=mode, model=label, profile=security.profile,
                                  tasks_hash=pins["tasks_hash"], providers=pins["providers"], exclude=run_id)
    diff = None
    if base is not None:
        try:
            diff = compare(load_summary(base), summary)
        except (OSError, ValueError, KeyError) as error:
            write(f"Baseline {base} could not be read ({type(error).__name__}); no comparison.")
    report = write_report(folder / "report.html", summary, [scrub(record) for record in records], diff,
                          {task.id: task.purpose for task in tasks})
    totals = summary["totals"]
    write(f"{totals['passed']}/{totals['trials']} trials passed; {totals['tasks_all_passed']}/{totals['tasks']} tasks "
          f"passed every trial; estimated model cost ${totals['cost_usd']:.4f}")
    if totals.get("provider_errors") or totals.get("retried"):
        write(f"Provider errors: {totals['provider_errors']} trial(s) not counted; {totals['retried']} retried once.")
    if diff:
        for line in compare_text(diff):
            write(line)
    write(f"Records, summary and report: {folder} (open {report.name})")
    return 0 if totals["trials"] and totals["passed"] == totals["trials"] else 1


def main_compare(baseline: Path, current: Path, *, write: Write = print) -> int:
    try:
        diff = compare(load_summary(baseline), load_summary(current))
    except (OSError, ValueError, KeyError) as error:
        write(f"Cannot compare: {type(error).__name__}: {error}")
        return 2
    for line in compare_text(diff):
        write(line)
    return 1 if diff["newly_failing"] else 0


def main_lint(*, tasks_path: Path | None = None, write: Write = print) -> int:
    from .catalog import lint

    try:
        tasks = load_tasks(tasks_path)
    except TaskError as error:
        write(f"Task error: {error}")
        return 2
    issues = lint(tasks)
    for issue in issues:
        write(f"{issue.level}: {issue.where}: {issue.message}")
    errors = sum(1 for issue in issues if issue.level == "error")
    write(f"{len(tasks)} tasks; {errors} error(s), {len(issues) - errors} warning(s).")
    return 1 if errors else 0


def main_catalog(*, tasks_path: Path | None = None, output_dir: Path, results: Path | None = None,
                 write: Write = print) -> int:
    from .catalog import write_catalog

    try:
        tasks = load_tasks(tasks_path)
    except TaskError as error:
        write(f"Task error: {error}")
        return 2
    try:
        summary = load_summary(results) if results else None
    except (OSError, ValueError) as error:
        write(f"Cannot read results {results}: {type(error).__name__}")
        return 2
    paths = write_catalog(tasks, output_dir, summary)
    write("Catalogue: " + ", ".join(str(path) for path in paths))
    return 0


async def main_mutate(*, tasks_path: Path | None = None, mutation_names: list[str] | None = None,
                      write: Write = print) -> int:
    from .mutate import run_mutations

    try:
        tasks = load_tasks(tasks_path)
    except TaskError as error:
        write(f"Task error: {error}")
        return 2
    results = await run_mutations(tasks, mutation_names, write=write)
    uncovered = [result["mutation"] for result in results if not result["caught_by"]]
    write(f"{len(results)} mutation(s); {len(results) - len(uncovered)} caught"
          + (f"; NOT caught: {', '.join(uncovered)}" if uncovered else "."))
    return 1 if uncovered else 0
