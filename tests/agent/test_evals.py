import asyncio
import json

import pytest

from openepw.agent.evals.command import main_compare, main_run
from openepw.agent.evals.records import git_pins, read_records, write_record
from openepw.agent.evals.runner import run_suite, scripted_model
from openepw.agent.evals.schema import Task, load_tasks
from openepw.agent.policy_config import load_policy

ITHACA = {"lat": 42.44, "lon": -76.5, "name": "Ithaca"}


def task(**changes):
    base = {"id": "S900", "title": "Test task", "purpose": "A task built by a test.", "modes": ["agent"],
            "user": {"say": "AMY 2018 for Ithaca NY",
                     "answers": {"location_review": "approve", "product_choice": ["era5-openmeteo"]}},
            "graders": [], "script": [{"say": "Where?"}]}
    return Task.model_validate({**base, **changes})


def run(tasks, mode="agent", factory=scripted_model, profile="local", **kwargs):
    return asyncio.run(run_suite(tasks, mode=mode, model_factory=factory if mode == "agent" else None,
                                 security=load_policy(profile), **kwargs))


def failed(record):
    return {grade["code"] for grade in record["grades"] if not grade["passed"]}


@pytest.mark.parametrize("profile", ["local", "hosted"])
def test_packaged_tasks_pass_offline_under_each_profile(profile):
    tasks = load_tasks()
    guided = run(tasks, mode="guided", profile=profile)
    scripted = run(tasks, profile=profile)
    assert {record["task_id"] for record in scripted} == {item.id for item in tasks if "agent" in item.modes}
    problems = [(record["task_id"], record["mode"], failed(record)) for record in guided + scripted
                if not record["passed"]]
    assert not problems


def test_a_corrected_readiness_claim_passes_and_missing_forms_fail():
    claim = task(script=[{"say": "Done. The EPW is simulation-ready for EnergyPlus."}],
                 graders=[{"grader": "submitted", "value": True},
                          {"grader": "forms_in_order", "value": ["location_review"]}])
    [record] = run([claim])
    assert not record["passed"] and {"SUBMISSION_MISMATCH", "FORM_ORDER"} <= failed(record)
    assert "FALSE_READINESS" not in failed(record)                      # the host corrected it
    shown = [entry for entry in record["trace"] if entry["type"] == "assistant"]
    assert "READINESS_CORRECTED" in shown[-1]["data"]["guards"]


def test_a_redacted_key_and_negated_readiness_pass():
    good = task(user={"say": "AMY 2018 for Ithaca NY api_key=sk-shouldberedacted123", "answers": {}},
                script=[{"say": "It is not certified simulation-ready (simulation_ready=false)."}])
    [record] = run([good])
    assert record["passed"], failed(record)


def test_a_plan_with_years_the_person_never_wrote_is_refused():
    # The gate refuses 2023, so the stored plan uses 2018; a task expecting 2023 must fail.
    plan = task(script=[
        {"call": "review_location", "args": {"locations": ITHACA}}, {"call": "choose_products", "args": {}},
        {"call": "weather_plan", "args": {"request": {"product": "historical", "years": [2023],
                                                       "dataset_selections": []}}},
        {"say": "Which years?"}], graders=[{"grader": "years", "value": [2023]}])
    [record] = run([plan])
    assert "YEARS" in failed(record) and "UNGROUNDED_YEARS" not in failed(record)


def test_a_guided_fallback_is_not_an_agent_pass():
    from openepw.agent.model_port import ModelUnavailable, ScriptedModel

    s1 = next(item for item in load_tasks() if item.id == "S1")
    [record] = run([s1], factory=lambda item: ScriptedModel([ModelUnavailable("budget stop")]))
    assert not record["passed"] and "MODEL_FALLBACK" in failed(record)


def test_a_broken_run_is_reported_and_the_eval_continues(monkeypatch):
    from openepw.agent.evals import runner

    original = runner.run_trial

    async def flaky(item, **kwargs):
        if item.id == "S901":
            raise RuntimeError("boom")
        return await original(item, **kwargs)
    monkeypatch.setattr(runner, "run_trial", flaky)
    records = run([task(id="S901"), task(id="S902")])
    assert [(record["task_id"], record["passed"]) for record in records] == [("S901", False), ("S902", True)]
    assert failed(records[0]) == {"RUN_ERROR"}


def test_an_exhausted_budget_stops_the_eval():
    from openepw.agent.model_port import ScriptedModel, say

    class Budgeted(ScriptedModel):
        max_cost_usd = 0.01
        usage = {"estimated_usd": 0.02}

    records = run([task(id="S903"), task(id="S904")], factory=lambda item: Budgeted([say("Where?")]))
    assert [record["task_id"] for record in records] == ["S903"]


def test_live_trials_follow_the_task_and_safety_tags():
    assert task().live_trials() == 3 and task(tags=["safety"]).live_trials() == 5
    assert task(trials={"live": 2}, tags=["safety"]).live_trials() == 2


def test_records_hold_pins_a_trace_ending_in_the_outcome_and_no_keys(tmp_path):
    leaky = task(user={"say": "AMY 2018 for Ithaca NY", "answers": {}},
                 script=[{"say": "Your key api_key=sk-evaltestLEAK1234567890 is set."}])
    [record] = run([leaky], pins={"run_id": "R1", "git": git_pins()})
    assert "SECRET_LEAK" in failed(record)
    trace = record["trace"]
    assert trace[-1]["type"] == "outcome" and "facts" in trace[-1]["data"] and "strikes" in trace[-1]["data"]["state"]
    model = [entry for entry in trace if entry["type"] == "model"]
    assert model and model[0]["data"]["items"] and model[0]["data"]["system_sha256"]
    assert trace.index(model[0]) > next(index for index, entry in enumerate(trace) if entry["type"] == "user")
    path = tmp_path / "trials.jsonl"
    write_record(path, record)
    assert "sk-evaltestLEAK" not in path.read_text(encoding="utf-8")
    [stored] = read_records(path)
    assert stored["pins"]["run_id"] == "R1" and stored["grades"] == record["grades"]


def test_git_pins_name_the_commit_or_unknown(tmp_path):
    here = git_pins()
    assert len(here["commit"]) == 40 and isinstance(here["dirty"], bool)
    assert git_pins(tmp_path)["commit"] == "unknown"


def test_the_eval_command_writes_records_a_summary_and_a_report_and_compares(tmp_path):
    output = []
    for _ in range(2):
        assert asyncio.run(main_run(task_ids=["S2", "s11"], evals_dir=tmp_path, write=output.append)) == 0
    runs = sorted(path for path in tmp_path.iterdir() if path.is_dir())
    assert len(runs) == 2
    for folder in runs:
        assert {path.name for path in folder.iterdir()} == {"trials.jsonl", "summary.json", "report.html"}
    summary = json.loads((runs[-1] / "summary.json").read_text(encoding="utf-8"))
    assert summary["pins"]["git"]["commit"] and summary["pins"]["tasks_hash"] and summary["totals"]["trials"] == 2
    assert any("No task changed status." in line for line in output)          # compared with the first run
    assert main_compare(runs[0], runs[1], write=output.append) == 0


def test_the_eval_command_refuses_what_it_cannot_run(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = []
    assert asyncio.run(main_run(mode="agent", write=output.append, evals_dir=tmp_path)) == 2
    assert "--live" in output[-1]
    assert asyncio.run(main_run(mode="agent", live=True, env_file=tmp_path / "none.env", write=output.append,
                                evals_dir=tmp_path)) == 2
    assert asyncio.run(main_run(task_ids=["nope"], write=output.append, evals_dir=tmp_path)) == 2
    broken = tmp_path / "S1.yaml"
    broken.write_text("id: S1\ntitle: Broken task\npurpose: Checks the error.\nuser: {say: hi}\ncolour: red\n",
                      encoding="utf-8")
    assert asyncio.run(main_run(tasks_path=broken, write=output.append, evals_dir=tmp_path)) == 2
    assert "S1.yaml:5" in output[-1] and "colour" in output[-1]


def test_openepw_eval_without_a_subcommand_means_run():
    from openepw.cli.main import _default_eval_run

    assert _default_eval_run(["eval", "--mode", "agent"]) == ["eval", "run", "--mode", "agent"]
    assert _default_eval_run(["--data-root", "x", "eval"]) == ["--data-root", "x", "eval", "run"]
    assert _default_eval_run(["eval", "lint"]) == ["eval", "lint"]
    assert _default_eval_run(["geocode", "eval"]) == ["geocode", "eval"]
    assert _default_eval_run(["--data", "x", "eval"]) == ["--data", "x", "eval", "run"]


def test_the_stub_geocoder_narrows_by_region_like_the_real_search():
    from openepw.agent.evals.stubs import geocode_results

    def names(query):
        return [item["name"] for item in geocode_results(query)["results"]]
    assert names("Ithaca") == names("Ithaca, NY") == ["Ithaca, New York, United States"]
    assert names("Springfield, Massachusetts") == ["Springfield, Massachusetts, United States"]
    assert len(names("Springfield")) == 3 and names("Ithaca NY") == []


def test_readiness_claims_need_a_negation_next_to_them():
    from openepw.agent.guard import claims_ready

    for text in ("The EPW is simulation-ready.", "The EPW is ready for simulation.",
                 "No QC issues, so the EPW is simulation-ready.", "Not only done: it is simulation-ready."):
        assert claims_ready(text), text
    for text in ("It is not certified simulation-ready (simulation_ready=false).",
                 "simulation_ready=false; review QC.", "The file is not simulation-ready.",
                 "Outputs record `simulation_ready=false`."):
        assert not claims_ready(text), text


@pytest.mark.live
def test_live_agent_evals_with_a_budget_cap(tmp_path):
    """OPENEPW_RUN_LIVE=1 and an OpenAI key: a few agent tasks against the real model."""
    output = []
    asyncio.run(main_run(mode="agent", live=True, task_ids=["S1", "S8", "S11", "S12"], trials=1, max_cost=0.5,
                         evals_dir=tmp_path, write=output.append))
    [folder] = [path for path in tmp_path.iterdir() if path.is_dir()]
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    assert summary["totals"]["trials"] == 4 and summary["totals"]["cost_usd"] < 0.5



def test_baselines_need_the_same_tasks_and_folders_are_never_reused(tmp_path):
    output = []
    assert asyncio.run(main_run(task_ids=["S2", "S11"], evals_dir=tmp_path, write=output.append)) == 0
    output.clear()
    assert asyncio.run(main_run(task_ids=["S2"], evals_dir=tmp_path, write=output.append)) == 0
    assert not any("Removed" in line or "Baseline" in line for line in output)    # a subset is not compared
    folder = next(path for path in tmp_path.iterdir() if path.is_dir())
    assert asyncio.run(main_run(task_ids=["S2"], evals_dir=tmp_path, output_dir=folder, write=output.append)) == 2
    assert "already holds a run" in output[-1]


def test_a_run_with_no_applicable_task_is_a_usage_error(tmp_path):
    output = []
    assert asyncio.run(main_run(task_ids=["S42"], evals_dir=tmp_path, write=output.append)) == 2   # agent-only task
    assert "No task applies to guided mode" in output[-1]



def test_a_provider_failure_is_retried_once_and_then_reported_apart():
    from openepw.agent.evals.metrics import summarize
    from openepw.agent.model_port import ModelUnavailable, ScriptedModel, say

    flaky = task(id="S905")
    attempts = []

    def once_then_fine(item):
        attempts.append(item.id)
        if len(attempts) == 1:
            return ScriptedModel([ModelUnavailable("The model request could not complete", "transport")])
        return ScriptedModel([say("Where?")])
    [record] = run([flaky], factory=once_then_fine)
    assert record["passed"] and record["status"] == "pass" and record["retried_after"] == "transport"
    assert len(attempts) == 2

    def always_down(item):
        return ScriptedModel([ModelUnavailable("The model request returned HTTP 503", "provider")])
    [down] = run([flaky], factory=always_down)
    assert down["status"] == "provider_error" and not down["passed"] and down["retried_after"] == "provider"
    notice = next(entry for entry in down["trace"] if entry["data"].get("code") == "MODEL_UNAVAILABLE")
    assert notice["data"]["cause"] == "provider"
    summary = summarize([record, down], {"run_id": "R"})
    task_summary = summary["tasks"][0]
    assert task_summary["trials"] == 1 and task_summary["provider_errors"] == 1 and task_summary["status"] == "pass"
    assert summary["totals"]["provider_errors"] == 1 and summary["totals"]["pass_rate"] == 1.0


def test_a_budget_or_client_failure_is_still_an_agent_failure():
    from openepw.agent.model_port import ModelUnavailable, ScriptedModel

    [record] = run([task(id="S906")], factory=lambda item: ScriptedModel([ModelUnavailable("HTTP 400", "client")]))
    assert record["status"] == "fail" and "MODEL_FALLBACK" in failed(record) and "retried_after" not in record
