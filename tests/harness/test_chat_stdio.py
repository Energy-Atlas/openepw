"""Terminal conversation state over the real MCP stdio client."""

import asyncio
import json
import sys
from pathlib import Path

from openepw.artifacts.store import ArtifactStore
from openepw.epw import read_epw
from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.chat import ChatSession
from openepw.harness.mcp_client import StdioMCPPort

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_future import signal


class TwoTurns:
    def __init__(self, signals_id):
        self.intents = [
            AgentIntent(kind="weather", lat=42.44, lon=-76.5,
                        product="historical", years=[2024], provider="station"),
            AgentIntent(kind="future", method="morph", climate_scenario="ssp245",
                        climate_period=(2036, 2065), reference_period=(1985, 2014),
                        signals_artifact_id=signals_id),
        ]
        self.prompts = []

    def parse(self, prompt):
        self.prompts.append(prompt)
        return self.intents.pop(0)


def test_real_stdio_chat_weather_then_future_followup_and_save(tmp_path):
    source = Path(__file__).parents[1] / "pilot" / "fixture_server.py"
    signals = ArtifactStore(tmp_path).write(
        "signals", "signals.json",
        json.dumps([signal().model_dump(mode="json")]).encode(), "signals")
    model = TwoTurns(signals.id)
    record = tmp_path / "harness" / "chat-last-run.json"
    saved = tmp_path / "output.epw"

    async def journey():
        async with StdioMCPPort(tmp_path, server_args=[
            str(source), "--data-root", str(tmp_path), "--mode", "general",
        ]) as mcp:
            agent = ReferenceAgent(mcp, model, record_path=record)
            chat = ChatSession(agent, mcp, model)
            first = await chat.handle("Historical 2024 at Ithaca")
            assert "[completed]" in first
            assert len(chat.weather_artifacts) == 1
            prior_id = chat.weather_artifacts[0]
            second = await chat.handle("Use that EPW for SSP245 future morph, 2036-2065")
            assert "[completed]" in second
            assert "baseline origin weather_output" in second
            assert prior_id not in model.prompts[1]
            assert "saved" in await chat.handle(f"/save last {saved}")
            assert len(read_epw(saved).data) == 8784
            assert "Historical 2024 at Ithaca" not in record.read_text()

    asyncio.run(journey())


def test_real_stdio_cambridge_choice_resumes_one_weather_job(tmp_path):
    source = Path(__file__).parents[1] / "pilot" / "fixture_server.py"

    class OneTurn:
        def __init__(self):
            self.calls = 0

        def parse(self, prompt):
            self.calls += 1
            return AgentIntent(kind="weather", place="Cambridge, MA",
                               product="historical", years=[2024])

    async def journey():
        async with StdioMCPPort(tmp_path, server_args=[
            str(source), "--data-root", str(tmp_path), "--mode", "cambridge",
        ]) as mcp:
            model = OneTurn()
            chat = ChatSession(ReferenceAgent(mcp, model), mcp, model)
            choice = await chat.handle("Historical 2024 Cambridge MA")
            assert "1. Cambridge, Massachusetts, United States" in choice
            result = await chat.handle("1")
            assert "[completed]" in result
            assert model.calls == 1

    asyncio.run(journey())
