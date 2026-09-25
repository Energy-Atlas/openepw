import json

import httpx
import pytest

from openepw.harness.model import ModelUnavailable, OpenAIIntentParser


def test_bounded_model_parser_redacts_prompt_and_records_only_usage(tmp_path):
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer sk-test-secret"
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps({
                    "kind": "weather", "place": "Ithaca", "product": "historical",
                    "years": [2024],
                })}]}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        })

    ledger = tmp_path / "cost.json"
    model = OpenAIIntentParser(
        "sk-test-secret", ledger_path=ledger,
        client=httpx.Client(transport=httpx.MockTransport(respond)))
    intent = model.parse("Ithaca 2024 OPENAI_API_KEY=sk-test-secret")
    assert intent.years == [2024]
    assert seen[0]["model"] == "gpt-6-luna"
    assert seen[0]["reasoning"]["effort"] == "low"
    assert seen[0]["text"]["format"]["type"] == "json_schema"
    schema = seen[0]["text"]["format"]["schema"]
    assert "locations" in schema["required"]
    assert "product_id" in schema["required"]
    guidance = seen[0]["input"][0]["content"]
    assert "product=tmyx" in guidance
    assert "Provider IDs are lowercase" in guidance
    assert seen[0]["store"] is False
    assert "sk-test-secret" not in seen[0]["input"][1]["content"]
    assert "sk-test-secret" not in ledger.read_text()
    assert json.loads(ledger.read_text())["estimated_usd"] < 0.001


def test_interactive_parser_can_continue_after_persisted_smoke_count(tmp_path):
    ledger = tmp_path / "cost.json"
    ledger.write_text(json.dumps({"calls": 20, "input_tokens": 1000,
                                  "output_tokens": 500, "estimated_usd": 0.001}))

    def respond(request):
        return httpx.Response(200, json={
            "status": "completed",
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps({"kind": "unknown"})}]}],
            "usage": {"input_tokens": 50, "output_tokens": 10},
        })

    model = OpenAIIntentParser(
        "sk-test-secret", ledger_path=ledger, max_calls=None,
        client=httpx.Client(transport=httpx.MockTransport(respond)))
    assert model.parse("hello").kind == "unknown"
    assert json.loads(ledger.read_text())["calls"] == 21


def test_interactive_parser_still_enforces_cost_stop(tmp_path):
    ledger = tmp_path / "cost.json"
    ledger.write_text(json.dumps({"calls": 20, "input_tokens": 1000,
                                  "output_tokens": 500, "estimated_usd": 8.0}))
    model = OpenAIIntentParser("sk-test-secret", ledger_path=ledger, max_calls=None,
                               client=httpx.Client(transport=httpx.MockTransport(
                                   lambda request: pytest.fail("No model call expected"))))
    with pytest.raises(ModelUnavailable, match="budget stop"):
        model.parse("hello")
