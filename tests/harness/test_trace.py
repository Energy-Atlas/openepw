"""LangSmith console traces contain useful steps without provider payloads."""

import asyncio
import json

from openepw.harness.agent import AgentIntent, AgentResult
from openepw.harness.chat import ChatSession, load_trace_key
from openepw.harness.trace import LangSmithTrace, TracingIntentParser, TracingMCPPort


class CaptureClient:
    def __init__(self):
        self.created = []
        self.updated = []

    def create_run(self, **fields):
        self.created.append(fields)

    def update_run(self, **fields):
        self.updated.append(fields)


class Model:
    def parse(self, prompt):
        return AgentIntent(kind="weather", lat=42.44, lon=-76.5,
                           product="historical", years=[2024])


class Port:
    async def call(self, name, **arguments):
        assert name == "weather_plan"
        return {"plan_hash": "a" * 64, "output_count": 1,
                "private_provider_payload": "topsecret"}

    async def upload_file(self, path):
        raise AssertionError("unused")

    async def read_artifact(self, artifact_id):
        raise AssertionError("unused")


class Agent:
    def __init__(self, port):
        self.mcp = port
        self.model = None
        self.plan_hash = None
        self.job_id = None

    async def run(self, prompt, *, auto_submit=False, baseline_override=None):
        self.model.parse(prompt)
        planned = await self.mcp.call(
            "weather_plan", request={"secret": "topsecret", "year": 2024})
        self.plan_hash = planned["plan_hash"]
        return AgentResult("review_required", "Plan ready", self.plan_hash)


def test_trace_captures_turn_model_and_mcp_without_raw_tool_payload():
    client = CaptureClient()
    tracer = LangSmithTrace("fake-key", project="openepw-test", client=client)
    port = TracingMCPPort(Port(), tracer)
    model = TracingIntentParser(Model(), tracer)
    chat = ChatSession(Agent(port), port, model, auto_submit=False, tracer=tracer)

    answer = asyncio.run(chat.handle(
        "Get Ithaca 2024 historical weather LANGSMITH_API_KEY=oneoffcredential"))

    assert "review_required" in answer
    assert [run["name"] for run in client.created] == [
        "openepw.chat.turn", "openepw.intent", "mcp.weather_plan"]
    assert len(client.updated) == 3
    recorded = json.dumps([client.created, client.updated], default=str)
    assert "topsecret" not in recorded
    assert "oneoffcredential" not in recorded
    assert "private_provider_payload" not in recorded
    assert "Ithaca 2024" in recorded
    assert "historical" in recorded
    assert "openepw-test" in recorded


def test_trace_key_loader_reads_existing_env_without_changing_it(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = b'LANGSMITH_API_KEY="lsv2-local-test"\nANOTHER=untouched\n'
    path.write_bytes(original)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert load_trace_key(path) == "lsv2-local-test"
    assert path.read_bytes() == original
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-shell-test")
    assert load_trace_key(path) == "lsv2-shell-test"
    assert path.read_bytes() == original
