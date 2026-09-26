"""LangChain structured extraction for multi-intent console turns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, ValidationError

from .agent import AgentIntent, safe_prompt
from .model import INPUT_USD_PER_MILLION, INTENT_SCHEMA, OUTPUT_USD_PER_MILLION, ModelUnavailable


class TurnExtraction(BaseModel):
    requests: list[AgentIntent] = Field(default_factory=list)


TURN_SCHEMA: dict[str, Any] = {
    "title": "TurnExtraction",
    "type": "object",
    "properties": {"requests": {"type": "array", "items": INTENT_SCHEMA}},
    "required": ["requests"],
    "additionalProperties": False,
}


_INSTRUCTIONS = (
    "Extract every distinct user request and every explicit field from the current utterance. "
    "Return one request when a sentence has several fields for the same weather task, "
    "but multiple requests when the user asks for separate outputs (for example AMY and TMYx). "
    "A short answer such as a year or product is a delta: use kind=unknown if the current "
    "utterance does not state weather or future. Do not repeat information from prior turns. "
    "Use action=explore for a question about products, sources or availability without a "
    "retrieval request. If the user asks to retrieve and show options, use action=retrieve. "
    "For weather, capture place, coordinates, product, years/dates, provider and exact "
    "product_id when present. A named actual year normally implies historical only when "
    "no explicit product conflicts. TMY, TMYx and published reference products do not "
    "use an actual year. For future, capture baseline artifact ID, method, scenario and "
    "climate/reference windows when stated. Never invent a location, year, source "
    "availability, climate window, artifact ID or missing field. Use lowercase enum values. "
    "Return no requests for social acknowledgments or job/file status questions."
)


class LangChainTurnParser:
    def __init__(self, api_key: str, *, model: str = "gpt-6-luna",
                 ledger_path: str | Path | None = None, max_cost_usd: float = 8.0,
                 structured_model: Any = None):
        if not api_key and structured_model is None:
            raise ModelUnavailable("OPENAI_API_KEY is required for model parsing")
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.max_cost_usd = max_cost_usd
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "estimated_usd": 0.0}
        if self.ledger_path and self.ledger_path.is_file():
            self.usage.update(json.loads(self.ledger_path.read_text(encoding="utf-8")))
        if structured_model is None:
            client = ChatOpenAI(
                api_key=api_key, model=model, use_responses_api=True, store=False,
                reasoning={"effort": "low"}, max_tokens=2048, max_retries=0,
                timeout=30,
            )
            structured_model = client.with_structured_output(
                TURN_SCHEMA, method="json_schema", include_raw=True, strict=True)
        self.structured_model = structured_model

    def _save(self) -> None:
        if self.ledger_path is None:
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.usage, indent=2), encoding="utf-8")
        temporary.replace(self.ledger_path)

    def parse_many(self, prompt: str) -> list[AgentIntent]:
        prompt = safe_prompt(prompt, limit=4000)
        projected = ((len(prompt) / 3 + 2000) * INPUT_USD_PER_MILLION +
                     2048 * OUTPUT_USD_PER_MILLION) / 1_000_000
        if self.usage["estimated_usd"] + projected >= self.max_cost_usd:
            raise ModelUnavailable("Projected model usage exceeds the local budget stop")
        try:
            result = self.structured_model.invoke([
                ("system", _INSTRUCTIONS), ("human", prompt),
            ])
            raw = result["raw"]
            metadata = getattr(raw, "usage_metadata", None) or {}
            input_tokens = int(metadata.get("input_tokens") or 0)
            output_tokens = int(metadata.get("output_tokens") or 0)
            self.usage["calls"] += 1
            self.usage["input_tokens"] += input_tokens
            self.usage["output_tokens"] += output_tokens
            self.usage["estimated_usd"] += (
                input_tokens * INPUT_USD_PER_MILLION +
                output_tokens * OUTPUT_USD_PER_MILLION) / 1_000_000
            self._save()
            if result.get("parsing_error") or result.get("parsed") is None:
                raise ModelUnavailable("Model returned no valid intent JSON")
            parsed = TurnExtraction.model_validate(result["parsed"])
            if len(parsed.requests) > 5:
                raise ModelUnavailable("More than five requests in one turn; split the request")
            return parsed.requests
        except ModelUnavailable:
            raise
        except ValidationError as error:
            fields = ",".join(str(item["loc"][0]) for item in error.errors()[:3])
            raise ModelUnavailable(f"Model intent fields invalid: {fields}") from None
        except Exception:
            raise ModelUnavailable("OpenAI request could not complete") from None

    def parse(self, prompt: str) -> AgentIntent:
        """Compatibility with the single-intent reference-agent interface."""
        intents = self.parse_many(prompt)
        return intents[0] if intents else AgentIntent(kind="unknown")
