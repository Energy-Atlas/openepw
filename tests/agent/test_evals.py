import asyncio
import json

import pytest

from openepw.agent.evals.command import main_eval
from openepw.agent.evals.runner import load_scenarios, report_json, run_evals, scripted_model

ITHACA = {"lat": 42.44, "lon": -76.5, "name": "Ithaca"}


def evaluate(scenarios, mode, factory=None):
    return asyncio.run(run_evals(scenarios, mode=mode, model_factory=factory))


def test_every_packaged_scenario_passes_in_guided_mode():
    reports = evaluate(load_scenarios(), "guided")
    assert reports and all(report.pass_rate == 1.0 for report in reports), [
        (report.scenario, report.failures) for report in reports]


def test_scripted_agent_scenarios_pass():
    scenarios = load_scenarios()
    reports = evaluate(scenarios, "agent", lambda scenario: scripted_model(scenario) if "script" in scenario else None)
    assert {report.scenario for report in reports} == {item["id"] for item in scenarios if "script" in item}
    assert all(report.pass_rate == 1.0 for report in reports), [(report.scenario, report.failures) for report in reports]


def scenario(**changes):
    base = {"id": "T", "say": "AMY 2018 for Ithaca NY", "modes": ["agent"],
            "answers": {"location_review": "approve", "product_choice": ["era5-openmeteo"]}, "checks": {}}
    return {**base, **changes}


def test_checks_catch_readiness_claims_and_ungrounded_expectations():
    bad = scenario(script=[{"say": "Done. The EPW is simulation-ready for EnergyPlus."}],
                   checks={"submitted": True, "forms": ["location_review"]})
    [report] = evaluate([bad], "agent", scripted_model)
    assert report.pass_rate == 0 and {"FALSE_READINESS", "NOT_SUBMITTED", "FORM_ORDER"} <= set(report.failures)


def test_negated_readiness_and_redacted_keys_pass():
    good = scenario(say="AMY 2018 for Ithaca NY api_key=sk-shouldberedacted123",
                    script=[{"say": "It is not certified simulation-ready (simulation_ready=false)."}])
    [report] = evaluate([good], "agent", scripted_model)
    assert report.pass_rate == 1.0, report.failures


def test_a_plan_with_years_the_person_never_wrote_fails():
    # The gate refuses 2023, so the stored plan uses 2018; a scenario expecting 2023 must fail.
    plan = scenario(script=[
        {"call": "review_location", "args": {"locations": ITHACA}}, {"call": "choose_products", "args": {}},
        {"call": "weather_plan", "args": {"request": {"product": "historical", "years": [2023], "dataset_selections": []}}},
        {"say": "Which years?"}], checks={"years": [2023]})
    [report] = evaluate([plan], "agent", scripted_model)
    assert "YEARS" in report.failures and "UNGROUNDED_YEARS" not in report.failures


def test_report_json_totals():
    reports = evaluate([scenario(script=[{"say": "Where?"}])], "agent", scripted_model)
    summary = report_json(reports, mode="agent")
    assert summary["runs"] == 1 and summary["pass_rate"] == 1.0 and summary["scenarios"][0]["scenario"] == "T"


def test_the_eval_command_needs_a_key_for_live_runs_and_writes_reports(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = []
    assert asyncio.run(main_eval(mode="agent", live=True, env_file=tmp_path / "none.env",
                                 write=output.append)) == 2
    report = tmp_path / "report.json"
    code = asyncio.run(main_eval(mode="agent", scripted=True, scenario_ids=["s11", "S1"], output=report,
                                 write=output.append))
    data = json.loads(report.read_text())
    assert code == 0 and data["runs"] == 2 and data["model"] == "scripted"
    assert asyncio.run(main_eval(scenario_ids=["nope"], write=output.append)) == 2


@pytest.mark.live
def test_live_agent_evals_with_a_budget_cap(tmp_path):
    """OPENEPW_RUN_LIVE=1 and an OpenAI key: a few agent scenarios against the real model."""
    report = tmp_path / "live.json"
    asyncio.run(main_eval(mode="agent", live=True, scenario_ids=["S1", "S8", "S11", "S12"], max_cost=0.5,
                          output=report))
    data = json.loads(report.read_text())
    assert data["runs"] == 4 and data["cost_usd"] < 0.5


def test_the_stub_geocoder_narrows_by_region_like_the_real_search():
    from openepw.agent.evals.stubs import geocode_results

    def names(query):
        return [row["name"].split(",")[1].strip() for row in geocode_results(query)["results"]]

    assert names("Springfield, MO") == ["Missouri"] and names("Springfield, Massachusetts") == ["Massachusetts"]
    assert len(names("Springfield")) == 3 and names("Ithaca NY") == [] and names("Ithaca") == ["New York"]


def test_readiness_claims_need_a_negation_next_to_them():
    from openepw.agent.evals.runner import claims_ready

    for text in ("The EPW is simulation-ready.", "The EPW is ready for simulation.",
                 "No QC issues, so the EPW is simulation-ready.", "Not only done: it is simulation-ready."):
        assert claims_ready(text), text
    for text in ("It is not certified simulation-ready (simulation_ready=false).",
                 "simulation_ready=false; review QC.", "The file is not simulation-ready.",
                 "Outputs record `simulation_ready=false`."):
        assert not claims_ready(text), text


def check(events, facts=None, mode="guided", scenario=None):
    from types import SimpleNamespace

    from openepw.agent.evals.runner import _check
    from openepw.agent.interactions import Event
    from openepw.agent.state import Facts

    session = SimpleNamespace(events=lambda: [Event(seq=index + 1, **event) for index, event in enumerate(events)],
                              facts=facts or Facts())
    return _check(scenario or {"id": "T"}, session, None, mode=mode)


RUN = {"type": "user", "text": "Run", "data": {"answer": {"approve": True}}}
SUBMIT = {"type": "tool", "text": "weather_submit", "data": {"tool": "weather_submit", "phase": "call"}}


def test_every_submission_needs_its_own_run_approval():
    assert "SUBMIT_WITHOUT_APPROVAL" not in check([RUN, SUBMIT, SUBMIT])        # one run, two plans
    assert "SUBMIT_WITHOUT_APPROVAL" in check([RUN, SUBMIT, {"type": "user", "text": "hi"}, SUBMIT])
    assert "SUBMIT_WITHOUT_APPROVAL" in check([SUBMIT])


def test_option_labels_do_not_count_as_written_years():
    from openepw.agent.state import Facts

    label = {"type": "user", "text": "ERA5 (1940-2024)", "data": {"answer": {"choice_ids": ["x"]}}}
    assert "UNGROUNDED_YEARS" in check([label], Facts(years=[2020]))
    typed = {"type": "user", "text": "2020", "data": {"answer": {"text": "2020"}}}
    assert "UNGROUNDED_YEARS" not in check([label, typed], Facts(years=[2020]))


def test_a_guided_fallback_is_not_an_agent_pass():
    from openepw.agent.model_port import ModelUnavailable, ScriptedModel

    s1 = next(item for item in load_scenarios() if item["id"] == "S1")
    [report] = evaluate([s1], "agent", lambda scenario: ScriptedModel([ModelUnavailable("budget stop")]))
    assert report.pass_rate == 0 and "MODEL_FALLBACK" in report.failures


def test_a_broken_run_is_reported_and_the_eval_continues(tmp_path):
    broken = scenario(id="BROKEN")
    del broken["say"]
    good = scenario(id="GOOD", script=[{"say": "Where?"}])
    reports = evaluate([broken, good], "agent", scripted_model)
    assert [(report.scenario, report.passed) for report in reports] == [("BROKEN", 0), ("GOOD", 1)]
    assert reports[0].failures == {"RUN_ERROR": 1}


def test_an_exhausted_budget_stops_the_eval():
    from openepw.agent.model_port import ScriptedModel, say

    class Budgeted(ScriptedModel):
        max_cost_usd = 0.01
        usage = {"estimated_usd": 0.02}

    first, second = scenario(id="A"), scenario(id="B")
    reports = evaluate([first, second], "agent", lambda item: Budgeted([say("Where?")]))
    assert [report.scenario for report in reports] == ["A"]


def test_failed_transcripts_never_carry_a_key(tmp_path):
    leaky = scenario(script=[{"say": "Your key api_key=sk-evaltestLEAK1234567890 is set."}])
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps({"scenarios": [leaky]}), encoding="utf-8")
    report = tmp_path / "report.json"
    asyncio.run(main_eval(mode="agent", scripted=True, scenarios_file=path, output=report, write=lambda line: None))
    text = report.read_text()
    assert "SECRET_LEAK" in text and "sk-evaltestLEAK" not in text


def test_live_agent_evals_need_the_live_flag(tmp_path):
    output = []
    assert asyncio.run(main_eval(mode="agent", write=output.append)) == 2 and "--live" in output[-1]
