"""The eval framework itself: task schema, grader fixtures, metrics, comparison, report, lint,
catalogue and mutation runs."""

import asyncio

import pytest

from openepw.agent.evals.catalog import fixture_counts, fixtures, lint, run_fixture, write_catalog
from openepw.agent.evals.graders import REGISTRY
from openepw.agent.evals.metrics import (
    compare,
    compare_text,
    percentile,
    summarize,
    task_summary,
    wilson,
)
from openepw.agent.evals.mutate import MUTATIONS, run_mutations
from openepw.agent.evals.report import render
from openepw.agent.evals.schema import TaskError, coverage_items, load_task, load_tasks

GOOD = "id: S1\ntitle: A good task\npurpose: Proves loading works.\nuser: {say: hi}\n"


def write(tmp_path, text, name="S1.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_packaged_tasks_validate_and_lint_clean():
    tasks = load_tasks()
    assert len(tasks) >= 36 and [task.id for task in tasks] == sorted((task.id for task in tasks),
                                                                     key=lambda item: int(item[1:]))
    assert lint(tasks) == []


@pytest.mark.parametrize("extra, message", [
    ("colour: red\n", "S1.yaml:5: colour"),
    ("graders:\n- {grader: nope}\n", "S1.yaml:6: unknown grader 'nope'"),
    ("graders:\n- {grader: strikes, value: many}\n", "S1.yaml:6: strikes: bad value"),
    ("graders:\n- {grader: no_tools, value: [x]}\n", "takes no value"),
    ("graders:\n- {grader: no_secret_leak}\n", "always runs"),
    ("covers: [made.up]\n", "unknown coverage id(s) made.up"),
    ("script:\n- {say: x, call: y}\n", "either call (with args) or say"),
])
def test_task_errors_name_the_file_and_line(tmp_path, extra, message):
    with pytest.raises(TaskError) as error:
        load_task(write(tmp_path, GOOD + extra))
    assert message in str(error.value)


def test_duplicate_task_ids_are_refused(tmp_path):
    write(tmp_path, GOOD, "a.yaml")
    write(tmp_path, GOOD, "b.yaml")
    with pytest.raises(TaskError, match="also used by"):
        load_tasks(tmp_path)


def test_every_grader_has_a_passing_and_a_failing_fixture():
    counts = fixture_counts()
    assert set(counts) == set(REGISTRY)
    assert all(count["pass"] and count["fail"] for count in counts.values()), counts


@pytest.mark.parametrize("item", fixtures(), ids=lambda item: f"{item['grader']}-{item['expect']}")
def test_grader_fixtures_hold(item):
    ok, verdict = run_fixture(item)
    assert ok, (item.get("note"), verdict)


def test_every_grader_explains_itself():
    for grader in REGISTRY.values():
        assert grader.code.isupper() and grader.description and grader.why and grader.severity in ("hard", "soft")


def record(task_id, passed, trial=1, codes=(), cost=0.01, steps=2):
    grades = [{"grader": "submitted", "code": "SUBMISSION_MISMATCH", "severity": "hard", "passed": passed,
               "evidence": [], "detail": ""}]
    return {"task_id": task_id, "title": task_id, "suite": "regression", "tags": ["safety"], "trial": trial,
            "mode": "agent", "profile": "hosted", "task_hash": "h" + task_id, "passed": passed, "grades": grades,
            "trace": [], "metrics": {"seconds": 1.0, "model_steps": steps, "tool_calls": 1, "input_tokens": 10,
                                     "output_tokens": 5, "cost_usd": cost, "codes": dict.fromkeys(codes, 1),
                                     "strikes": 0, "fallback": False}}


def test_wilson_and_percentiles():
    assert wilson(0, 0) == (0.0, 1.0)
    low, high = wilson(10, 10)
    assert 0.72 < low < 0.73 and high == 1.0
    low, high = wilson(5, 10)
    assert 0.23 < low < 0.24 and 0.76 < high < 0.77
    assert percentile([], 0.5) == 0.0 and percentile([3, 1, 2], 0.5) == 2 and percentile([1, 2, 3, 4], 0.95) == 4


def test_task_metrics_distinguish_pass_flaky_and_fail():
    flaky = task_summary([record("S1", True, 1), record("S1", False, 2), record("S1", True, 3)])
    assert (flaky["status"], flaky["pass_at_k"], flaky["pass_all_k"], flaky["pass_rate"]) == ("flaky", True, False, 0.667)
    assert flaky["hard_failures"] == {"SUBMISSION_MISMATCH": 1} and flaky["cost_usd"] == 0.03
    assert task_summary([record("S2", False)])["status"] == "fail"


def summary_of(*records, run_id="R"):
    return summarize(list(records), {"run_id": run_id, "git": {"commit": run_id}, "model": "m", "profile": "hosted"})


def test_summaries_group_by_suite_and_tag_with_intervals():
    summary = summary_of(record("S1", True), record("S2", False))
    assert summary["totals"]["passed"] == 1 and summary["totals"]["trials"] == 2
    assert summary["tags"]["safety"]["interval95"][0] < 0.5 < summary["tags"]["safety"]["interval95"][1]
    assert summary["suites"]["regression"]["tasks_all_passed"] == 1


def test_comparison_lists_what_changed():
    before = summary_of(record("S1", True), record("S2", True), record("S3", False), record("S4", True), run_id="A")
    after = summary_of(record("S1", False), record("S2", True), record("S2", False, 2), record("S3", True),
                       record("S5", True), run_id="B")
    diff = compare(before, after)
    assert diff["newly_failing"] == ["S1", "S2"] and diff["fixed"] == ["S3"] and diff["flaky"] == ["S2"]
    assert diff["added"] == ["S5"] and diff["removed"] == ["S4"] and diff["pin_changes"]["commit"] == ["A", "B"]
    text = "\n".join(compare_text(diff))
    assert "Newly failing: S1, S2" in text and "Fixed: S3" in text


def test_the_report_escapes_text_and_links_tasks():
    bad = record("S1", False)
    bad["trace"] = [{"type": "assistant", "text": "<script>alert(1)</script>"},
                    {"type": "outcome", "data": {"facts": {}, "state": {}}}]
    bad["grades"][0]["evidence"] = [0]
    page = render(summary_of(bad), [bad], purposes={"S1": "Purpose <b>here</b>"})
    assert "<script>alert" not in page and "&lt;script&gt;" in page and "Purpose &lt;b&gt;here" in page
    assert 'href=#S1' in page and 'class="hl"' in page and "SUBMISSION_MISMATCH" in page


LINT_TASKS = {
    "S1.yaml": GOOD + "modes: [agent]\n",
    "S2.yaml": GOOD.replace("S1", "S2") + "covers: [guard.strikes]\nmodes: [agent]\nscript: []\ngraders:\n"
               "- {grader: codes_present, value: [STRIKE_LIMIT], profile: hosted}\n"
               "- {grader: codes_absent, value: [NOT_A_CODE]}\n"
               "- {grader: model_input_excludes, value: [x]}\n",
    "S3.yaml": GOOD.replace("S1", "S3") + "covers: [scope.knowledge]\nmodes: [guided]\n"
               "graders:\n- {grader: knowledge_answer_labelled}\n",
}


def test_lint_finds_planted_problems(tmp_path):
    for name, text in LINT_TASKS.items():
        write(tmp_path, text, name)
    messages = [f"{issue.level} {issue.where} {issue.message}" for issue in lint(load_tasks(tmp_path))]
    joined = "\n".join(messages)
    assert "error S1 (S1.yaml) agent task without a script" in joined
    assert "warning S1 (S1.yaml) covers nothing" in joined
    assert "codes_present STRIKE_LIMIT under hosted can never pass" in joined
    assert "never records code NOT_A_CODE" in joined
    assert "model_input_excludes without model_input_contains" in joined
    assert "knowledge_answer_labelled applies only in agent mode" in joined


def test_the_catalogue_lists_every_task_grader_and_coverage_id(tmp_path):
    tasks = load_tasks()
    md, page = write_catalog(tasks, tmp_path)
    text = md.read_text(encoding="utf-8")
    assert all(f"## {task.id}" in text for task in tasks)
    assert all(f"`{grader.code}`" in text for grader in REGISTRY.values())
    assert all(f"`{item}`" in text for item in coverage_items())
    assert "**none**" not in text                                   # every coverage id has a task
    assert "<h1>Agent eval tasks</h1>" in page.read_text(encoding="utf-8")


def test_every_mutation_names_known_coverage_with_covering_tasks():
    tasks = load_tasks()
    for mutation in MUTATIONS:
        assert set(mutation.covers) <= set(coverage_items()), mutation.name
        assert any(set(task.covers) & set(mutation.covers) for task in tasks), mutation.name


def test_disabled_guards_are_caught_by_their_tasks():
    names = ["links-off", "readiness-off", "years-gate-off", "small-talk-off", "approval-gate-off"]
    results = asyncio.run(run_mutations(load_tasks(), names, write=lambda line: None))
    assert sorted(result["mutation"] for result in results) == sorted(names)
    assert all(result["caught_by"] for result in results), [(r["mutation"], r["still_passing"]) for r in results]
