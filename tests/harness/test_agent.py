import asyncio
import json

from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.mcp_client import MCPToolFailure
from openepw.harness.rubric import Case, RunRecord, score


class StubModel:
    def __init__(self, intent):
        self.intent = intent

    def parse(self, prompt):
        assert "sk-test-secret" not in prompt
        return self.intent


class StubMCP:
    def __init__(self, *, ambiguous=False, gap=False, partial=False):
        self.calls = []
        self.ambiguous = ambiguous
        self.gap = gap
        self.partial = partial

    async def call(self, name, **arguments):
        self.calls.append((name, arguments))
        if name == "weather_geocode":
            return {"candidates": [
                {"lat": 42, "lon": -76, "name": "Ithaca, NY"},
                *([{"lat": 41, "lon": -70, "name": "Ithaca, elsewhere"}]
                  if self.ambiguous else []),
            ]}
        if name == "weather_discover":
            return {"availability": {"options": [
                {"eligibility": {"status": "supported"}},
                {"eligibility": {"status": "unknown"}},
            ]}}
        if name == "weather_plan":
            return {"plan_hash": "a" * 64, "kind": "weather", "output_count": 1,
                    "issues": [], "estimated_calls": 1}
        if name == "plan_inspect":
            return {"kind": "weather", "request": {"product": "historical"},
                    "selected_candidates": [{"source": {
                        "provider": "station", "dataset": "synthetic"},
                        "selection_reasons": ["requested provider"]}]}
        if name == "weather_submit":
            return {"id": "b" * 32, "state": "queued"}
        if name == "job_inspect":
            return {"id": "b" * 32, "state": (
                        "partially_completed" if self.partial else "completed"),
                    "completed": 1, "failed": int(self.partial),
                    "batch_rows": ([{"occurrence_index": 0, "status": "succeeded"},
                                    {"occurrence_index": 1, "status": "unsupported",
                                     "issue_codes": ["OUTSIDE_COVERAGE"]}]
                                   if self.partial else []), "errors": [],
                    "artifacts": {"weather": ["c" * 32], "weather_count": 1}}
        if name == "artifact_inspect":
            return {"artifact_id": "c" * 32, "simulation_ready": False,
                    "qc_issue_codes": (["MISSING_CRITICAL_VARIABLE"] if self.gap else []),
                    "role": "weather"}
        raise AssertionError(name)


def test_agent_clarifies_ambiguous_place_without_plan():
    mcp = StubMCP(ambiguous=True)
    model = StubModel(AgentIntent(kind="weather", place="Ithaca",
                                  product="historical", years=[2024]))
    result = asyncio.run(ReferenceAgent(mcp, model).run("Ithaca 2024"))
    assert result.status == "needs_clarification"
    assert "Ithaca" in result.message
    assert [name for name, _ in mcp.calls] == ["weather_geocode"]


def test_agent_submits_exact_plan_hash_and_explains_gap(tmp_path):
    mcp = StubMCP(gap=True)
    model = StubModel(AgentIntent(kind="weather", lat=42, lon=-76,
                                  product="historical", years=[2024]))
    record = tmp_path / "run.json"
    result = asyncio.run(ReferenceAgent(mcp, model, record_path=record).run(
        "Ithaca 2024 OPENAI_API_KEY=sk-test-secret", auto_submit=True))
    assert result.status == "completed"
    assert "unknown" in result.message.lower()
    assert "gap" in result.message.lower()
    assert "simulation_ready=false" in result.message
    assert ("weather_submit", {"plan_hash": "a" * 64}) in mcp.calls
    rubric = score(
        Case("G", required_tools=("weather_discover", "weather_plan",
                                  "weather_submit", "job_inspect",
                                  "artifact_inspect"),
             required_terms=("gap", "simulation_ready=false")),
        RunRecord(
            tools=[name for name, _ in mcp.calls], explanation=result.message,
            plan_hash=result.plan_hash, submitted_hash="a" * 64,
            simulation_ready=False),
    )
    assert rubric.passed
    saved = record.read_text()
    assert "sk-test-secret" not in saved
    assert "Ithaca 2024" not in saved
    assert "OPENAI_API_KEY" not in saved
    assert json.loads(saved)["job_id"] == "b" * 32


def test_agent_explains_partial_batch_without_source_switch():
    mcp = StubMCP(partial=True)
    model = StubModel(AgentIntent(kind="weather", lat=42, lon=-76,
                                  product="published"))
    result = asyncio.run(ReferenceAgent(mcp, model).run("Published batch",
                                                       auto_submit=True))
    assert result.status == "partially_completed"
    assert "1 unsupported" in result.message
    assert "OUTSIDE_COVERAGE" in result.message
    assert not any(name == "job_retry_failed" for name, _ in mcp.calls)


def test_unsupported_future_method_is_blocked_without_substitution():
    class RefusingMCP:
        async def call(self, name, **arguments):
            assert name == "future_plan"
            raise MCPToolFailure("UNSUPPORTED_SCENARIO", "Method does not support SSP245")

    model = StubModel(AgentIntent(
        kind="future", baseline_artifact_id="a" * 32, method="climate_profile",
        climate_scenario="ssp245", climate_period=(2045, 2054)))
    result = asyncio.run(ReferenceAgent(RefusingMCP(), model).run(
        "Hourly profile SSP245", auto_submit=True))
    assert result.status == "blocked"
    assert "UNSUPPORTED_SCENARIO" in result.message


def test_unprobed_nsrdb_actual_year_stays_unknown():
    class UnknownMCP(StubMCP):
        async def call(self, name, **arguments):
            if name == "weather_discover":
                self.calls.append((name, arguments))
                return {"availability": {"options": [
                    {"eligibility": {"status": "unknown"}}]}}
            if name == "weather_plan":
                self.calls.append((name, arguments))
                return {"plan_hash": "a" * 64, "kind": "weather",
                        "output_count": 0, "issues": [{"code": "UNVERIFIED_FOOTPRINT"}]}
            return await super().call(name, **arguments)

    mcp = UnknownMCP()
    model = StubModel(AgentIntent(kind="weather", lat=40, lon=-105,
                                  product="historical", years=[2023],
                                  provider="nsrdb"))
    result = asyncio.run(ReferenceAgent(mcp, model).run(
        "NSRDB actual year 2023", auto_submit=True))
    assert result.status == "no_executable_output"
    assert "unknown" in result.message.lower()
    assert not any(name == "weather_submit" for name, _ in mcp.calls)


def test_cmip6_license_does_not_hide_unknown_window():
    class WindowMCP:
        async def call(self, name, **arguments):
            assert name == "future_plan"
            return {"plan_hash": "d" * 64, "kind": "future",
                    "baseline_ref": {"origin": "user_provided"},
                    "output_count": 1, "issues": [],
                    "warnings": ["Model license allowed; climate window unknown"]}

    model = StubModel(AgentIntent(
        kind="future", baseline_artifact_id="a" * 32, method="morph",
        climate_scenario="ssp245", climate_period=(2036, 2065),
        reference_period=(1985, 2014)))
    result = asyncio.run(ReferenceAgent(WindowMCP(), model).run(
        "CMIP6 SSP245 future", auto_submit=False))
    assert result.status == "review_required"
    assert "climate window unknown" in result.message
