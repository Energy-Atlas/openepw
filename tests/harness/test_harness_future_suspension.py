"""The console cannot route future requests into removed MCP tools."""

import asyncio

from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.chat import ChatSession


class Port:
    def __init__(self):
        self.calls = []

    async def call(self, name, **arguments):
        self.calls.append((name, arguments))
        raise AssertionError("A suspended future request must not reach MCP")


class FutureModel:
    def parse(self, prompt):
        return AgentIntent(kind="future", method="morph",
                           climate_scenario="ssp245", climate_period=(2036, 2065))


def test_future_agent_request_is_blocked_without_mcp_call():
    port = Port()
    model = FutureModel()
    agent = ReferenceAgent(port, model)
    result = asyncio.run(agent.run_intent(model.parse("future"), auto_submit=True))
    assert result.status == "blocked"
    assert "FEATURE_SUSPENDED" in result.message
    assert port.calls == []


def test_ambiguous_future_followup_does_not_ask_for_baseline():
    port = Port()
    model = FutureModel()
    chat = ChatSession(ReferenceAgent(port, model), port, model)
    chat.weather_artifacts = ("a" * 32, "b" * 32)
    answer = asyncio.run(chat.handle("Use that EPW for future weather"))
    assert "FEATURE_SUSPENDED" in answer
    assert "/baseline" not in answer
    assert port.calls == []


def test_saved_future_plan_cannot_be_submitted():
    port = Port()
    agent = ReferenceAgent(port, FutureModel())
    agent.plan_hash = "a" * 64
    result = asyncio.run(agent.submit_plan("future"))
    assert result.status == "blocked"
    assert "FEATURE_SUSPENDED" in result.message
    assert port.calls == []
