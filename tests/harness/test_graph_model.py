import json

from langchain_core.messages import AIMessage

from openepw.harness.agent import AgentIntent
from openepw.harness.graph_model import LangChainTurnParser, TurnExtraction


class StructuredModel:
    def __init__(self):
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return {
            "raw": AIMessage(content="", usage_metadata={
                "input_tokens": 100, "output_tokens": 80, "total_tokens": 180}),
            "parsed": TurnExtraction(requests=[
                AgentIntent(kind="weather", place="Cambridge MA", product="amy",
                            years=[2018]),
                AgentIntent(kind="weather", place="Cambridge MA", product="tmyx"),
            ]),
            "parsing_error": None,
        }


def test_langchain_parser_returns_all_requests_and_uses_shared_cost_ledger(tmp_path):
    model = StructuredModel()
    ledger = tmp_path / "cost-ledger.json"
    parser = LangChainTurnParser("", structured_model=model, ledger_path=ledger)

    requests = parser.parse_many("Cambridge AMY 2018 and TMYx OPENAI_API_KEY=sk-secret12345")

    assert [request.product for request in requests] == ["historical", "tmyx"]
    assert "sk-secret12345" not in model.messages[1][1]
    assert json.loads(ledger.read_text())["calls"] == 1
    assert "sk-secret12345" not in ledger.read_text()
