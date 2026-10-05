import asyncio
import json

import httpx
import pytest

from openepw.agent.model_port import (
    ModelReply,
    ModelUnavailable,
    OpenAIModel,
    ScriptedModel,
    call,
    load_openai_key,
    say,
)

TOOLS = [{"name": "weather_geocode", "description": "Find a place.",
          "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}]
KEY = "sk-test-key-not-real-0000"


def openai(handler, tmp_path, **options):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIModel(KEY, ledger_path=tmp_path / "usage.json", client=client, **options)


def completed(output, input_tokens=1000, output_tokens=100):
    return httpx.Response(200, json={"status": "completed", "output": output,
                                     "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}})


def test_scripted_model_replays_steps_and_records_requests():
    model = ScriptedModel([call("weather_geocode", {"query": "Ithaca"}), say("Done."), ModelUnavailable("x")])
    first = asyncio.run(model.respond("system", [{"type": "user", "text": "hi"}], TOOLS))
    assert first.tool_calls[0].name == "weather_geocode" and json.loads(first.tool_calls[0].arguments)
    assert asyncio.run(model.respond("system", [], TOOLS)).text == "Done."
    with pytest.raises(ModelUnavailable):
        asyncio.run(model.respond("system", [], TOOLS))
    assert model.requests[0]["items"][0]["text"] == "hi" and model.requests[0]["tools"] == ["weather_geocode"]


def test_openai_request_shape_and_tool_call_parsing(tmp_path):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["Authorization"]
        return completed([{"type": "reasoning", "id": "rs_1", "encrypted_content": "e"},
                          {"type": "function_call", "id": "fc_1", "call_id": "call_1",
                           "name": "weather_geocode", "arguments": "{\"query\": \"Ithaca\"}"}])

    model = openai(handler, tmp_path)
    items = [{"type": "user", "text": "Ithaca"}, {"type": "note", "text": "state"},
             {"type": "assistant", "text": None, "raw": [{"type": "function_call", "call_id": "c0"}],
              "tool_calls": []},
             {"type": "tool_result", "call_id": "c0", "name": "weather_geocode", "output": "{}"}]
    reply = asyncio.run(model.respond("rules", items, TOOLS))
    body = seen["body"]
    assert body["instructions"] == "rules" and body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"] and body["parallel_tool_calls"] is False
    assert body["tools"][0] == {"type": "function", "name": "weather_geocode", "description": "Find a place.",
                                "parameters": TOOLS[0]["parameters"], "strict": False}
    assert body["input"] == [{"role": "user", "content": "Ithaca"}, {"role": "developer", "content": "state"},
                             {"type": "function_call", "call_id": "c0"},
                             {"type": "function_call_output", "call_id": "c0", "output": "{}"}]
    assert KEY not in json.dumps(body) and seen["auth"] == "Bearer " + KEY
    assert reply.tool_calls[0].id == "call_1" and reply.text is None
    assert [item["type"] for item in reply.item()["raw"]] == ["reasoning", "function_call"]


def test_openai_text_reply_and_usage_ledger(tmp_path):
    model = openai(lambda request: completed([{"type": "message", "content": [
        {"type": "output_text", "text": "Approve the location first."}]}]), tmp_path)
    reply = asyncio.run(model.respond("rules", [{"type": "user", "text": "hi"}], TOOLS))
    assert reply.text == "Approve the location first." and reply.cost_usd > 0
    ledger = json.loads((tmp_path / "usage.json").read_text())
    assert ledger["calls"] == 1 and ledger["input_tokens"] == 1000
    again = openai(lambda request: completed([]), tmp_path)
    assert again.usage["calls"] == 1                       # the ledger is shared across runs


def test_openai_budget_stop_and_call_limit(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return completed([])

    with pytest.raises(ModelUnavailable, match="budget"):
        asyncio.run(openai(handler, tmp_path, max_cost_usd=0.0).respond("rules", [], TOOLS))
    limited = openai(handler, tmp_path, max_calls=0)
    with pytest.raises(ModelUnavailable, match="limit"):
        asyncio.run(limited.respond("rules", [], TOOLS))
    assert calls == []


@pytest.mark.parametrize("response", [
    httpx.Response(401, json={"error": {"message": "bad key sk-test-key-not-real-0000"}}),
    httpx.Response(200, json={"status": "incomplete", "output": []}),
    httpx.Response(200, content=b"not json"),
])
def test_openai_failures_are_model_unavailable_without_the_body(tmp_path, response):
    with pytest.raises(ModelUnavailable) as error:
        asyncio.run(openai(lambda request: response, tmp_path).respond("rules", [], TOOLS))
    assert KEY not in str(error.value)


def test_transport_errors_are_model_unavailable(tmp_path):
    def handler(request):
        raise httpx.ConnectError("offline")

    with pytest.raises(ModelUnavailable):
        asyncio.run(openai(handler, tmp_path).respond("rules", [], TOOLS))


def test_a_missing_key_is_model_unavailable():
    with pytest.raises(ModelUnavailable):
        OpenAIModel("")


def test_the_key_comes_from_the_environment_or_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nOPENAI_API_KEY='sk-from-file'\n", encoding="utf-8")
    assert load_openai_key(env) == "sk-from-file"
    assert load_openai_key(tmp_path / "missing.env") is None
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    assert load_openai_key(env) == "sk-from-env"


def test_reply_items_round_trip():
    reply = ModelReply(text="ok", raw=[{"type": "message"}])
    assert reply.item() == {"type": "assistant", "text": "ok", "raw": [{"type": "message"}], "tool_calls": []}
