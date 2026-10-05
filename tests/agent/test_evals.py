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
    assert asyncio.run(main_eval(mode="agent", env_file=tmp_path / "none.env", write=output.append)) == 2
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
    asyncio.run(main_eval(mode="agent", scenario_ids=["S1", "S8", "S11", "S12"], max_cost=0.5, output=report))
    data = json.loads(report.read_text())
    assert data["runs"] == 4 and data["cost_usd"] < 0.5
