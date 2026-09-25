import json

import httpx

from openepw.harness.model import OpenAIIntentParser


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
    assert seen[0]["store"] is False
    assert "sk-test-secret" not in seen[0]["input"][1]["content"]
    assert "sk-test-secret" not in ledger.read_text()
    assert json.loads(ledger.read_text())["estimated_usd"] < 0.001
