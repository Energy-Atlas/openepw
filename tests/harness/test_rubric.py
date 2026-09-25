from openepw.harness.rubric import Case, RunRecord, score


def test_noaa_gap_is_critical_failure_if_called_ready():
    case = Case("G", required_tools=("weather_plan", "weather_submit",
                                     "job_inspect", "artifact_inspect"),
                required_terms=("gap", "simulation_ready=false"))
    run = RunRecord(tools=["weather_plan", "weather_submit", "job_inspect",
                           "artifact_inspect"],
                    explanation="The gap EPW is simulation-ready.",
                    plan_hash="abc", submitted_hash="abc",
                    simulation_ready=False)
    result = score(case, run)
    assert not result.passed
    assert "FALSE_READINESS" in result.critical_failures


def test_plan_hash_and_secret_redaction_are_required():
    case = Case("A", required_tools=("weather_plan", "weather_submit"))
    run = RunRecord(tools=["weather_plan", "weather_submit"],
                    explanation="OPENAI_API_KEY=sk-test-secret",
                    plan_hash="a", submitted_hash="b")
    result = score(case, run)
    assert not result.passed
    assert {"PLAN_HASH_CHANGED", "SECRET_LEAK"} <= set(result.critical_failures)


def test_valid_uncertain_explanation_passes():
    case = Case("unknown", required_tools=("weather_assess",),
                required_terms=("unknown", "eligible"))
    run = RunRecord(tools=["weather_assess"],
                    explanation="Coverage is unknown; eligible only to try retrieval.")
    assert score(case, run).passed
