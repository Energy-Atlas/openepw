"""Optional bounded OpenAI intent parser; no hosted tracing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from .agent import AgentIntent, safe_prompt

INPUT_USD_PER_MILLION = 0.10
OUTPUT_USD_PER_MILLION = 0.50


def _nullable(kind: str) -> dict[str, Any]:
    return {"type": [kind, "null"]}


INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["weather", "future", "unknown"]},
        "place": _nullable("string"),
        "locations": {
            "anyOf": [
                {"type": "array", "items": {
                    "type": "object", "properties": {
                        "id": {"type": "string"}, "lat": {"type": "number"},
                        "lon": {"type": "number"},
                    }, "required": ["id", "lat", "lon"],
                    "additionalProperties": False,
                }},
                {"type": "null"},
            ],
        },
        "lat": _nullable("number"),
        "lon": _nullable("number"),
        "product": {"type": ["string", "null"],
                    "enum": ["historical", "amy", "tmy", "tmyx", "published", None]},
        "years": {"type": "array", "items": {"type": "integer"}},
        "start": _nullable("string"),
        "end": _nullable("string"),
        "provider": _nullable("string"),
        "product_id": _nullable("string"),
        "missing_policy": {"type": "string", "enum": ["warn", "error"]},
        "baseline_artifact_id": _nullable("string"),
        "signals_artifact_id": _nullable("string"),
        "method": {"type": ["string", "null"],
                   "enum": ["morph", "climate_profile", None]},
        "climate_scenario": {"type": ["string", "null"],
                             "enum": ["ssp126", "ssp245", "ssp370", "ssp585",
                                      "rcp45", "rcp85", None]},
        "climate_period": {
            "anyOf": [
                {"type": "array", "items": {"type": "integer"},
                 "minItems": 2, "maxItems": 2},
                {"type": "null"},
            ]
        },
        "reference_period": {
            "anyOf": [
                {"type": "array", "items": {"type": "integer"},
                 "minItems": 2, "maxItems": 2},
                {"type": "null"},
            ]
        },
    },
    "required": [
        "kind", "place", "locations", "lat", "lon", "product", "years", "start", "end",
        "provider", "product_id", "missing_policy", "baseline_artifact_id",
        "signals_artifact_id",
        "method", "climate_scenario", "climate_period", "reference_period",
    ],
    "additionalProperties": False,
}


class ModelUnavailable(Exception):
    pass


class OpenAIIntentParser:
    """Use a small Responses call to extract intent; MCP remains authoritative."""

    def __init__(self, api_key: str, *, model: str = "gpt-6-luna",
                 ledger_path: str | Path | None = None,
                 max_cost_usd: float = 8.0,
                 client: httpx.Client | None = None):
        if not api_key:
            raise ModelUnavailable("OPENAI_API_KEY is required for model parsing")
        self.api_key = api_key
        self.model = model
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.max_cost_usd = max_cost_usd
        self.client = client or httpx.Client(timeout=30)
        self.last_intent: AgentIntent | None = None
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "estimated_usd": 0.0}
        if self.ledger_path and self.ledger_path.is_file():
            self.usage.update(json.loads(self.ledger_path.read_text(encoding="utf-8")))

    def _save(self):
        if self.ledger_path is None:
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.usage, indent=2), encoding="utf-8")
        temporary.replace(self.ledger_path)

    def parse(self, prompt: str) -> AgentIntent:
        prompt = safe_prompt(prompt)
        # Conservative allowance before every call; the server-side cap includes reasoning.
        projection = ((len(prompt) / 3 + 1500) * INPUT_USD_PER_MILLION +
                      1024 * OUTPUT_USD_PER_MILLION) / 1_000_000
        if self.usage["estimated_usd"] + projection >= self.max_cost_usd:
            raise ModelUnavailable("Projected model usage exceeds the local budget stop")
        if self.usage["calls"] >= 20:
            raise ModelUnavailable("Model smoke call limit reached")
        payload = {
            "model": self.model,
            "input": [
                {"role": "developer", "content": (
                    "Extract a weather task as a JSON object. Fields may be omitted except kind. "
                    "kind is weather, future, or unknown. For weather, include product "
                    "(historical, amy, tmy, tmyx, published), explicit years/dates, "
                    "place, coordinates or an explicit locations array with id/lat/lon, "
                    "provider and exact product_id only if requested, "
                    "and missing_policy. If the user names TMYx, use product=tmyx "
                    "even when it is a published file; published is only for an "
                    "unspecified published product. Provider IDs are lowercase "
                    "(for example onebuilding, openmeteo, noaa, nsrdb). "
                    "For future, include an exact baseline_artifact_id if supplied, "
                    "method, climate_scenario, climate_period, reference_period, "
                    "and signals_artifact_id only if supplied. Do not invent missing "
                    "values, source availability, coordinates, artifact IDs or climate windows. "
                    "Use exact enum values. Year windows are arrays [start_year,end_year]. "
                    "Use null for missing optional fields. Output JSON only."
                )},
                {"role": "user", "content": prompt},
            ],
            "reasoning": {"effort": "low"},
            "text": {"format": {
                "type": "json_schema", "name": "weather_intent",
                "strict": True, "schema": INTENT_SCHEMA,
            }},
            "max_output_tokens": 1024,
            "store": False,
        }
        try:
            response = self.client.post(
                "https://api.openai.com/v1/responses", json=payload,
                headers={"Authorization": "Bearer " + self.api_key},
            )
        except httpx.HTTPError:
            raise ModelUnavailable("OpenAI request could not complete") from None
        if response.status_code >= 400:
            raise ModelUnavailable(
                f"OpenAI model request returned HTTP {response.status_code}") from None
        try:
            raw: dict[str, Any] = response.json()
            usage = raw.get("usage") or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            cost = (input_tokens * INPUT_USD_PER_MILLION +
                    output_tokens * OUTPUT_USD_PER_MILLION) / 1_000_000
            self.usage["calls"] += 1
            self.usage["input_tokens"] += input_tokens
            self.usage["output_tokens"] += output_tokens
            self.usage["estimated_usd"] += cost
            self._save()
            if raw.get("status") != "completed":
                raise ModelUnavailable("Model response was incomplete")
            message = next(item for item in raw["output"] if item.get("type") == "message")
            text = next(item["text"] for item in message["content"]
                        if item.get("type") == "output_text")
            intent = AgentIntent.model_validate_json(text)
        except ValidationError as exc:
            fields = ",".join(str(error["loc"][0]) for error in exc.errors()[:3])
            raise ModelUnavailable(f"Model intent fields invalid: {fields}") from None
        except (KeyError, StopIteration, ValueError, TypeError):
            raise ModelUnavailable("Model returned no valid intent JSON") from None
        self.last_intent = intent
        return intent
