"""LangSmith tracing follows the env file, for the agent chat and the web chat; nothing is sent."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from harness import Harness

from openepw.agent.model_port import ScriptedModel, call
from openepw.agent.policy_model import ModelPolicy
from openepw.agent.tracing import (
    LangSmithTracer,
    NullTracer,
    TracingSettings,
    langchain_tracing,
    summarize_arguments,
    tracing_settings,
)
from openepw.epw.writer import epw_bytes

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic  # noqa: E402

langsmith = pytest.importorskip("langsmith")
KEY = "lsv2_pt_test_not_real_0000"
ON = TracingSettings(True, "openepw-test", "on (project openepw-test)", None, KEY)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY",
                 "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


class Recording(langsmith.Client):
    """A LangSmith client that keeps runs in memory instead of sending them."""

    def __init__(self, fail=False):
        super().__init__(api_key=KEY, api_url="https://langsmith.invalid", auto_batch_tracing=False)
        self.created, self.updated, self.fail = [], [], fail

    def create_run(self, *args, **kwargs):
        if self.fail:
            raise ConnectionError("offline")
        self.created.append(kwargs)

    def update_run(self, *args, **kwargs):
        self.updated.append(kwargs)


def env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_env_file_decides_and_the_environment_overrides(tmp_path, monkeypatch):
    assert not tracing_settings(env(tmp_path, ""), default_project="p").enabled
    off = tracing_settings(env(tmp_path, f"LANGSMITH_TRACING=false\nLANGSMITH_API_KEY={KEY}\n"), default_project="p")
    assert not off.enabled and off.reason == "LANGSMITH_TRACING is not true"
    missing = tracing_settings(env(tmp_path, "LANGSMITH_TRACING=true\n"), default_project="p")
    assert not missing.enabled and "LANGSMITH_API_KEY is missing" in missing.reason
    on = tracing_settings(env(tmp_path, f"LANGSMITH_TRACING=true\nLANGSMITH_API_KEY='{KEY}'\n"
                                        "LANGSMITH_PROJECT=mine\n"), default_project="p")
    assert on.enabled and on.project == "mine" and on.api_key == KEY
    assert KEY not in on.reason and KEY not in repr(on)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")             # an exported variable wins
    assert not tracing_settings(env(tmp_path, f"LANGSMITH_TRACING=true\nLANGSMITH_API_KEY={KEY}\n"),
                                default_project="p").enabled


def test_tracing_is_off_without_the_langsmith_package(tmp_path, monkeypatch):
    import openepw.agent.tracing as tracing

    monkeypatch.setattr(tracing.importlib.util, "find_spec", lambda name: None)
    settings = tracing_settings(env(tmp_path, f"LANGSMITH_TRACING=true\nLANGSMITH_API_KEY={KEY}\n"),
                                default_project="p")
    assert not settings.enabled and "not installed" in settings.reason


def test_trace_arguments_never_carry_file_bytes_keys_or_paths():
    summary = summarize_arguments({"content_base64": "QUJD" * 1000, "filename": r"C:\Users\me\site.epw",
                                   "query": "Ithaca api_key=sk-abcdefghijklmnop"})
    text = json.dumps(summary)
    assert summary["content_base64"] == "[omitted]" and "QUJD" not in text
    assert "sk-abcdefghijklmnop" not in text and "site.epw" not in text


def runs(client):
    return {run["name"]: run for run in client.created}


def test_an_agent_turn_is_one_trace_with_model_and_tool_runs(tmp_path):
    client = Recording()
    tracer = LangSmithTracer(ON, client=client)
    model = ScriptedModel([call("weather_geocode", {"query": "Ithaca, NY"}),
                           call("review_location", {"locations": {"lat": 42.44, "lon": -76.5, "name": "Ithaca"}})])

    async def main():
        async with Harness(tmp_path, policy=ModelPolicy(model), tracer=tracer) as h:
            await h.say("AMY 2018 for Ithaca NY api_key=sk-abcdefghijklmnop")
            assert h.form.gate == "review_location"

    asyncio.run(main())
    named = runs(client)
    turn = named["openepw.agent.message"]
    assert turn["session_name"] == "openepw-test" and turn["inputs"]["text"].endswith("[redacted]")
    assert named["model"]["parent_run_id"] == turn["id"] and named["model"]["run_type"] == "llm"
    assert named["model.weather_geocode"]["parent_run_id"] == turn["id"]
    assert named["weather_geocode"]["parent_run_id"] == named["model.weather_geocode"]["id"]
    assert named["weather_locations_review"]["parent_run_id"] == named["model.review_location"]["id"]
    sent = json.dumps(client.created + client.updated, default=str)
    assert "sk-abcdefghijklmnop" not in sent and "encrypted_content" not in sent
    turn_end = next(run for run in client.updated if run.get("run_id", run.get("id")) == turn["id"]
                    or run.get("outputs", {}).get("form"))
    assert "review_location" in json.dumps(turn_end, default=str)


def test_uploads_are_traced_without_the_file(tmp_path):
    client = Recording()

    async def main():
        async with Harness(tmp_path, tracer=LangSmithTracer(ON, client=client)) as h:
            await h.session.upload_epw(epw_bytes(synthetic(2023, 8760)), "site.epw")

    asyncio.run(main())
    named = runs(client)
    assert named["epw_upload"]["inputs"]["arguments"]["content_base64"] == "[omitted]"
    assert len(json.dumps(client.created, default=str)) < 20_000


def test_a_failing_trace_never_stops_the_chat(tmp_path):
    tracer = LangSmithTracer(ON, client=Recording(fail=True))

    async def main():
        async with Harness(tmp_path, tracer=tracer) as h:
            await h.say("AMY 2018 for Ithaca NY")
            assert h.form.gate == "review_location"

    asyncio.run(main())
    assert tracer.failed


def test_the_cli_says_whether_tracing_is_on(tmp_path):
    from openepw.agent.cli import chat_tracer

    tracer, notice = chat_tracer(env(tmp_path, ""))
    assert isinstance(tracer, NullTracer) and not tracer.enabled and notice is None
    tracer, notice = chat_tracer(env(tmp_path, "LANGSMITH_TRACING=true\n"))
    assert not tracer.enabled and "LANGSMITH_API_KEY is missing" in notice
    tracer, notice = chat_tracer(env(tmp_path, f"LANGSMITH_TRACING=true\nLANGSMITH_API_KEY={KEY}\n"))
    try:
        assert tracer.enabled and "openepw-agent" in notice and KEY not in notice
    finally:
        tracer.close()


def test_the_web_chat_parser_follows_the_settings_not_langchains_environment(monkeypatch):
    from langchain_core.runnables import RunnableLambda
    from langsmith.utils import tracing_is_enabled

    from openepw.harness.graph_model import LangChainTurnParser

    seen = []

    def fake(messages):
        seen.append(tracing_is_enabled())
        return {"raw": None, "parsed": {"requests": []}, "parsing_error": None}

    monkeypatch.setenv("LANGSMITH_TRACING", "true")              # LangChain alone would trace
    monkeypatch.setenv("LANGSMITH_API_KEY", KEY)
    off = TracingSettings(False, "p", "LANGSMITH_TRACING is not true")
    LangChainTurnParser("", structured_model=RunnableLambda(fake), tracing=off).parse_many("Ithaca")
    client = Recording()
    on = LangChainTurnParser("", structured_model=RunnableLambda(fake), tracing=ON, trace_client=client)
    on.parse_many("Ithaca")
    assert seen == [False, True] and client.created
    assert (client.created[0].get("session_name") or client.created[0].get("project_name")) == "openepw-test"


def test_create_app_reads_tracing_from_its_env_file(tmp_path, monkeypatch):
    import openepw.harness.graph_model as graph_model
    from openepw.api.app import create_app
    from openepw.config import RuntimeConfig
    from openepw.service import WeatherService

    captured = {}

    class Parser:
        def __init__(self, key, **options):
            captured.update(options, key=key)

    monkeypatch.setattr(graph_model, "LangChainTurnParser", Parser)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    path = env(tmp_path, f"OPENAI_API_KEY=sk-test-not-real\nLANGSMITH_TRACING=true\nLANGSMITH_API_KEY={KEY}\n")
    create_app(WeatherService(RuntimeConfig(data_root=tmp_path / "data")), env_file=path)
    assert captured["tracing"].enabled and captured["tracing"].project == "openepw-web-chat"


def test_no_settings_leaves_langchain_alone():
    with langchain_tracing(None):
        pass                                                      # no langsmith import needed
