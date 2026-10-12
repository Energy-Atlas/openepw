"""Graph think/gate nodes: place lists preview without confirmation, sets ask first."""

import asyncio
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from test_graph_chat import Parser, Port  # noqa: E402
from test_places_service import Http  # noqa: E402

from openepw.config import RuntimeConfig  # noqa: E402
from openepw.harness.agent import AgentIntent, ReferenceAgent  # noqa: E402
from openepw.harness.graph_chat import GraphChatSession  # noqa: E402
from openepw.mcp.server import create_server  # noqa: E402
from openepw.service import WeatherService  # noqa: E402


class PlacePort(Port):
    """Stub weather tools; place tools run through the real MCP server contract."""

    def __init__(self, tmp_path):
        super().__init__()
        self.server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path), http=Http()))

    async def call(self, name, **arguments):
        if name.startswith("weather_place"):
            self.calls.append((name, arguments))
            return (await self.server.call_tool(name, arguments)).structuredContent
        return await super().call(name, **arguments)


def _names(port):
    return [name for name, _ in port.calls]


def test_place_list_previews_without_confirmation_and_text_edits_it(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="Boston; Denver; Nowhereville",
                                 product="historical", years=[2018])])
    port = PlacePort(tmp_path)

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser, tmp_path / "chat.sqlite") as chat:
            reply = await chat.handle("Boston; Denver; Nowhereville 2018 historical")
            assert "1. Boston, Massachusetts, United States" in reply and "2 matches" in reply
            assert "2. Denver, Colorado, United States" in reply
            assert "Nowhereville" in reply and "not found" in reply
            assert [(item["lat"], item["lon"]) for item in chat.draft.locations] == [(42.36, -71.06), (39.74, -104.98)]
            assert chat.draft.product == "historical" and chat.draft.years == [2018]
            assert chat.choices == ()
            edited = await chat.handle("remove 3")
            assert "Nowhereville" not in edited and len(chat.draft.locations) == 2
            edited = await chat.handle("replace 1 with Denver")
            assert [item["name"] for item in chat.draft.locations][0] == "Denver, Colorado, United States"

    asyncio.run(journey())
    assert "weather_geocode" not in _names(port)
    assert "weather_plan" not in _names(port)          # the preview is shown before any planning
    assert len(parser.calls) == 1                      # edits are handled without the model


def test_coordinate_lists_become_points(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="40,-105; 41,-100")])
    port = PlacePort(tmp_path)

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser, tmp_path / "chat.sqlite") as chat:
            reply = await chat.handle("40,-105; 41,-100")
            assert "1. 40.0000, -105.0000" in reply and "2. 41.0000, -100.0000" in reply
            assert len(chat.draft.locations) == 2

    asyncio.run(journey())


def test_descriptive_sets_ask_then_preview_from_the_reply(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="all cities in Texas", product="tmy")])
    port = PlacePort(tmp_path)

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser, tmp_path / "chat.sqlite") as chat:
            asked = await chat.handle("TMY for all cities in Texas")
            assert "minimum population" in asked and "How many" in asked
            assert chat.draft is None or not chat.draft.locations
            reply = await chat.handle("over 100k, top 2")
            assert "1. Houston, Texas, United States" in reply and "2. Dallas, Texas, United States" in reply
            assert "GeoNames" in reply
            assert [item["name"] for item in chat.draft.locations] == [
                "Houston, Texas, United States", "Dallas, Texas, United States"]
            assert chat.draft.product == "tmy"

    asyncio.run(journey())
    assert len(parser.calls) == 1                      # the clarification reply skipped the model
    assert "weather_plan" not in _names(port)


def test_reset_clears_pending_place_state(tmp_path):
    parser = Parser([AgentIntent(kind="weather", place="all cities in Texas")], [])
    port = PlacePort(tmp_path)

    async def journey():
        async with GraphChatSession(ReferenceAgent(port, parser), port, parser, tmp_path / "chat.sqlite") as chat:
            await chat.handle("all cities in Texas")
            await chat.handle("/reset")
            await chat.handle("over 100k, top 2")

    asyncio.run(journey())
    assert "weather_place_set" not in _names(port)
