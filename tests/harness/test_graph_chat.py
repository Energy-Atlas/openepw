import asyncio
from pathlib import Path

import pytest

from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.graph_chat import GraphChatSession
from openepw.harness.mcp_client import StdioMCPPort

CAMBRIDGE = {"id": "cambridge", "name": "Cambridge, Massachusetts, United States",
             "lat": 42.3736, "lon": -71.1097}
ALLSTON = {"id": "allston", "name": "Allston, Massachusetts, United States",
           "lat": 42.355, "lon": -71.132}


class Parser:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    def parse_many(self, text):
        self.calls.append(text)
        return self.turns.pop(0)


class Port:
    def __init__(self):
        self.calls = []

    async def call(self, name, **arguments):
        self.calls.append((name, arguments))
        if name == "weather_geocode":
            return {"candidates": [CAMBRIDGE, ALLSTON]}
        if name == "weather_discover":
            return {"availability": {"options": []}, "candidates": []}
        if name == "weather_plan":
            return {"plan_hash": "a" * 64, "output_count": 1, "estimated_calls": 1}
        if name == "plan_inspect":
            return {"kind": "weather", "selected_candidates": []}
        if name == "weather_submit":
            return {"id": "b" * 32, "state": "queued"}
        if name == "job_inspect":
            return {"id": "b" * 32, "state": "completed", "completed": 1,
                    "failed": 0, "artifacts": {"weather": ["c" * 32]}}
        if name == "artifact_inspect":
            return {"role": "weather", "simulation_ready": False,
                    "qc_issue_codes": ["MISSING_CRITICAL_VARIABLE"]}
        if name == "weather_assess":
            return {"options": [], "locations": [], "issues": [], "snapshots": []}
        raise AssertionError(name)


@pytest.mark.parametrize("building_count", [200, 2012])
@pytest.mark.parametrize("invented_product", ["historical", "tmy"])
def test_graph_rejects_model_invented_weather_years(
        tmp_path, building_count, invented_product):
    parser = Parser([AgentIntent(kind="weather", place="Singapore",
                                 product=invented_product, years=[2012, 2016])])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            assert "product" in (await chat.handle(
                f"I would like UBEM for {building_count} buildings in Singapore")).lower()
            assert chat.draft.years == []
            assert chat.draft.product is None

    asyncio.run(journey())
    assert not any(name == "weather_plan" for name, _ in port.calls)


def test_graph_routes_monthly_view_to_completed_artifacts_without_new_weather_plan(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="Singapore")])

    class ViewPort(Port):
        async def call(self, name, **arguments):
            if name == "weather_visualization_capabilities":
                self.calls.append((name, arguments))
                return {"families": [
                    {"family": "monthly_series", "status": "implemented"},
                    {"family": "wind_rose", "status": "planned"}],
                    "variables": {"dry_bulb": {"unit": "degC"},
                                      "ghi": {"unit": "Wh/m2"}}}
            if name == "weather_visualize":
                self.calls.append((name, arguments))
                return {"view_id": "d" * 64, "rows": [], "total_rows": 24,
                        "specs": [{"family": "monthly_series",
                                   "summary": "24 monthly points"}]}
            return await super().call(name, **arguments)

    port = ViewPort()
    artifacts = ("a" * 32, "b" * 32)

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            chat.chat.weather_artifacts = artifacts
            answer = await chat.handle("visualize monthly weather trend")
            assert "variable" in answer.lower()
            assert "dry_bulb" in answer
            assert "variable:dry_bulb" in [choice for choice, _ in chat.menu()]
            assert "variable" in (await chat.handle("you have them")).lower()
            answer = await chat.handle_choice("variable:dry_bulb")
            assert '"view_id"' in answer
            assert '"family": "monthly_series"' in answer
            assert "planned" in (await chat.handle("visualize wind rose")).lower()

    asyncio.run(journey())
    assert parser.calls == []
    assert not any(name in ("weather_plan", "weather_submit") for name, _ in port.calls)
    call = next(arguments for name, arguments in port.calls if name == "weather_visualize")
    assert call["request"] == {"artifact_ids": list(artifacts),
                               "family": "monthly_series", "variable": "dry_bulb"}


def test_visualization_choice_and_artifacts_survive_chat_restart(tmp_path):
    class ViewPort(Port):
        async def call(self, name, **arguments):
            self.calls.append((name, arguments))
            if name == "weather_visualization_capabilities":
                return {"variables": {"dry_bulb": {"unit": "degC"}}}
            if name == "weather_visualize":
                return {"view_id": "d" * 64, "rows": [], "total_rows": 12,
                        "specs": [{"family": "monthly_series"}]}
            raise AssertionError(name)

    port = ViewPort()
    parser = Parser()
    checkpoint = tmp_path / "chat.sqlite"

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    checkpoint) as chat:
            chat.chat.weather_artifacts = ("a" * 32,)
            assert "variable" in (await chat.handle("visualize monthly weather")).lower()
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    checkpoint) as chat:
            assert chat.chat.weather_artifacts == ("a" * 32,)
            assert "variable:dry_bulb" in [value for value, _ in chat.menu()]
            assert '"view_id"' in await chat.handle_choice("variable:dry_bulb")

    asyncio.run(journey())
    assert parser.calls == []
    assert [name for name, _ in port.calls].count("weather_visualize") == 1


def test_time_grounding_keeps_named_weather_range_but_not_building_count():
    intent = AgentIntent(kind="weather", product="historical",
                         years=[2012, 2021, 2022, 2023])
    grounded = GraphChatSession._ground_weather_time(
        intent, "UBEM for 2012 buildings, weather years 2021-2023")
    assert grounded.years == [2021, 2022, 2023]


def test_future_plot_request_stays_suspended(tmp_path):
    parser = Parser()
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            assert "FEATURE_SUSPENDED" in await chat.handle(
                "plot future weather for 2050")
            assert not chat.chat.pending_view_active

    asyncio.run(journey())
    assert parser.calls == []
    assert port.calls == []


def test_graph_remembers_location_product_and_year_across_restart(tmp_path):
    parser = Parser(
        [AgentIntent(kind="weather", place="Cambridge MA")],
        [AgentIntent(kind="unknown", product="amy")],
        [AgentIntent(kind="unknown", years=[2018])],
    )
    port = Port()
    checkpoint = tmp_path / "chat.sqlite"
    record = tmp_path / "last-run.json"

    async def journey():
        agent = ReferenceAgent(port, parser, record_path=record)
        async with GraphChatSession(agent, port, parser, checkpoint) as chat:
            assert "product" in (await chat.handle("Weather in Cambridge MA")).lower()
            assert "year" in (await chat.handle("AMY")).lower()
        agent = ReferenceAgent.restore(port, parser, record) if record.exists() else ReferenceAgent(
            port, parser, record_path=record)
        async with GraphChatSession(agent, port, parser, checkpoint) as chat:
            assert "Cambridge" in chat.draft.place
            assert chat.draft.product == "historical"
            assert "2018" not in await chat.handle("2018")
            assert len(chat.choices) == 2
            assert "completed" in await chat.handle("1")
            assert "MISSING_CRITICAL_VARIABLE" in await chat.handle("my downloaded file?")

    asyncio.run(journey())
    assert len(parser.calls) == 3
    assert [name for name, _ in port.calls].count("weather_geocode") == 1
    request = next(args["request"] for name, args in port.calls if name == "weather_plan")
    assert request["product"] == "historical"
    assert request["years"] == [2018]
    assert request["locations"]["id"] == CAMBRIDGE["id"]


def test_graph_extracts_all_fields_and_runs_two_requests_in_one_turn(tmp_path):
    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018]),
                     AgentIntent(kind="weather", product="tmyx")])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            answer = await chat.handle("Get 2018 historical and TMYx at 42.37, -71.1")
            assert answer.count("[completed]") == 2

    asyncio.run(journey())
    requests = [args["request"] for name, args in port.calls if name == "weather_plan"]
    assert len(parser.calls) == 1
    assert [item["product"] for item in requests] == ["historical", "tmyx"]
    assert requests[0]["years"] == [2018]
    assert "years" not in requests[1]
    assert requests[1]["locations"] == {"lat": 42.37, "lon": -71.1}


def test_graph_menu_has_other_and_does_not_call_model_for_location_choice(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="Cambridge MA",
                                 product="historical", years=[2018])])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            assert "1." in await chat.handle("Historical 2018 for Cambridge MA")
            menu = chat.menu()
            assert menu[-1][0] == "other"
            assert menu[0][1] == CAMBRIDGE["name"]
            assert "completed" in await chat.handle_choice(menu[0][0])

    asyncio.run(journey())
    assert len(parser.calls) == 1


def test_graph_product_menu_selection_preserves_place_without_model_call(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="Cambridge MA")],
                    [AgentIntent(kind="unknown", years=[2018])])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            assert "product" in await chat.handle("Weather for Cambridge MA")
            assert ("product:historical", "Actual year (AMY)") in chat.menu()
            assert not any(value == "product:amy" for value, _ in chat.menu())
            assert "year" in await chat.handle_choice("product:historical")
            assert "1." in await chat.handle("2018")
            assert "completed" in await chat.handle_choice("location:cambridge")

    asyncio.run(journey())
    assert len(parser.calls) == 2
    request = next(args["request"] for name, args in port.calls if name == "weather_plan")
    assert request["product"] == "historical"
    assert request["years"] == [2018]


def test_graph_retains_year_given_while_location_choice_is_pending(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="Cambridge MA",
                                 product="historical")],
                    [AgentIntent(kind="unknown", years=[2018])])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            assert "year" in await chat.handle("Historical Cambridge MA")
            assert "1." in await chat.handle("2018")
            assert "completed" in await chat.handle_choice("location:cambridge")

    asyncio.run(journey())
    request = next(args["request"] for name, args in port.calls if name == "weather_plan")
    assert request["years"] == [2018]


def test_graph_uses_real_stdio_mcp_and_resumes_artifact_after_restart(tmp_path):
    server = Path(__file__).parents[1] / "pilot" / "fixture_server.py"
    parser = Parser([AgentIntent(kind="weather", lat=42.44, lon=-76.5,
                                 product="historical", years=[2024],
                                 provider="station")])
    record = tmp_path / "harness" / "last-run.json"
    checkpoint = tmp_path / "harness" / "chat.sqlite"

    async def journey():
        async with StdioMCPPort(tmp_path, server_args=[
                str(server), "--data-root", str(tmp_path), "--mode", "general",
        ]) as mcp:
            agent = ReferenceAgent(mcp, parser, record_path=record)
            async with GraphChatSession(agent, mcp, parser, checkpoint) as chat:
                assert "[completed]" in await chat.handle("Ithaca historical 2024")
                assert len(chat.chat.weather_artifacts) == 1
            agent = ReferenceAgent.restore(mcp, parser, record)
            async with GraphChatSession(agent, mcp, parser, checkpoint) as chat:
                assert "job_id:" in await chat.handle("my download status?")
                assert "simulation_ready=" in await chat.handle("my downloaded file?")

    asyncio.run(journey())
    assert len(parser.calls) == 1


def test_graph_reuses_explicit_same_location_after_completed_request(tmp_path):
    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018])],
                    [AgentIntent(kind="weather", product="tmyx")])
    port = Port()
    checkpoint = tmp_path / "chat.sqlite"

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    checkpoint) as chat:
            assert "completed" in await chat.handle("Historical 2018 at 42.37, -71.1")
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    checkpoint) as chat:
            assert "completed" in await chat.handle("Get TMYx for the same location")

    asyncio.run(journey())
    requests = [args["request"] for name, args in port.calls if name == "weather_plan"]
    assert requests[1]["locations"] == {"lat": 42.37, "lon": -71.1}


def test_explicit_retrieval_with_options_phrase_executes_after_extraction(tmp_path):
    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018], action="retrieve")])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            return await chat.handle("Get 2018 historical weather; what do you have?")

    answer = asyncio.run(journey())
    assert "[completed]" in answer
    assert "job_id:" in answer
    assert [name for name, _ in port.calls].count("weather_submit") == 1


def test_manual_batch_waits_for_submission_before_next_request(tmp_path):
    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018]),
                     AgentIntent(kind="weather", product="tmyx")])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite", auto_submit=False) as chat:
            assert "review_required" in await chat.handle("Historical 2018 and TMYx")
            assert [name for name, _ in port.calls].count("weather_plan") == 1
            answer = await chat.handle("/submit")
            assert "[completed]" in answer
            assert "review_required" in answer

    asyncio.run(journey())
    assert [name for name, _ in port.calls].count("weather_plan") == 2


def test_new_request_in_status_sentence_is_not_swallowed(tmp_path):
    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018])],
                    [AgentIntent(kind="weather", product="tmyx")])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            await chat.handle("Get historical 2018 at 42.37, -71.1")
            return await chat.handle("Tell me my download status and get TMYx "
                                     "for the same location")

    assert "[completed]" in asyncio.run(journey())
    names = [name for name, _ in port.calls]
    assert names.count("weather_submit") == 2
    assert names.count("job_inspect") >= 3


def test_status_lookup_does_not_erase_incomplete_new_request(tmp_path):
    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018])],
                    [AgentIntent(kind="weather", place="Cambridge MA",
                                 product="historical")],
                    [AgentIntent(kind="unknown", years=[2019])])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            await chat.handle("Get historical 2018 at 42.37, -71.1")
            assert "year" in await chat.handle("Get historical weather in Cambridge MA")
            assert "job_id:" in await chat.handle("my download status?")
            assert chat.draft.place == "Cambridge MA"
            assert "1." in await chat.handle("2019")
            assert "completed" in await chat.handle_choice("location:cambridge")

    asyncio.run(journey())
    requests = [args["request"] for name, args in port.calls if name == "weather_plan"]
    assert requests[-1]["years"] == [2019]


def test_status_lookup_preserves_a_new_plan_awaiting_submission(tmp_path):
    class DistinctPort(Port):
        async def call(self, name, **arguments):
            if name == "weather_plan":
                self.calls.append((name, arguments))
                index = sum(tool == "weather_plan" for tool, _ in self.calls)
                return {"plan_hash": str(index) * 64, "output_count": 1,
                        "estimated_calls": 1}
            if name == "job_inspect":
                self.calls.append((name, arguments))
                return {"id": "b" * 32, "plan_hash": "1" * 64,
                        "state": "completed", "completed": 1,
                        "failed": 0, "artifacts": {"weather": []}}
            return await super().call(name, **arguments)

    parser = Parser([AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2018])],
                    [AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                 product="historical", years=[2019])])
    port = DistinctPort()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite", auto_submit=False) as chat:
            await chat.handle("Get 2018 historical")
            await chat.handle("/submit")
            assert "review_required" in await chat.handle("Get 2019 historical")
            assert "job_id:" in await chat.handle("my download status?")
            await chat.handle("/submit")

    asyncio.run(journey())
    submitted = [args["plan_hash"] for name, args in port.calls if name == "weather_submit"]
    assert submitted == ["1" * 64, "2" * 64]


def test_empty_extraction_uses_no_second_model_call(tmp_path):
    parser = Parser([])
    port = Port()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            return await chat.handle("hello")

    assert "needs_clarification" in asyncio.run(journey())
    assert parser.calls == ["hello"]


def test_geocode_retries_us_state_abbreviation_with_comma(tmp_path):
    class SearchPort(Port):
        async def call(self, name, **arguments):
            if name == "weather_geocode":
                self.calls.append((name, arguments))
                if arguments["query"] == "Cambridge MA":
                    return {"candidates": []}
                if arguments["query"] == "Cambridge, MA":
                    return {"candidates": [CAMBRIDGE, ALLSTON]}
                raise AssertionError(arguments)
            return await super().call(name, **arguments)

    parser = Parser([AgentIntent(kind="weather", place="Cambridge MA",
                                 product="amy", years=[2018])])
    port = SearchPort()

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser,
                                    tmp_path / "chat.sqlite") as chat:
            assert "1." in await chat.handle("Cambridge MA AMY 2018")
            assert "completed" in await chat.handle_choice("location:cambridge")

    asyncio.run(journey())
    assert [args["query"] for name, args in port.calls if name == "weather_geocode"] == [
        "Cambridge MA", "Cambridge, MA"]
