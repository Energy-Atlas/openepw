"""The model behind agent mode: a provider-neutral port, a scripted model and an OpenAI adapter.

Conversation items are provider-neutral dictionaries:

- ``{"type": "user", "text": ...}``: what the person said (already redacted)
- ``{"type": "note", "text": ...}``: host context for this turn, such as finished jobs
- ``{"type": "assistant", "text": ..., "tool_calls": [...], "raw": [...]}``: a model reply;
  ``raw`` holds the provider's own items so they can be sent back unchanged
- ``{"type": "tool_result", "call_id": ..., "name": ..., "output": ...}``: a tool's result
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

import httpx

# The legacy parser's default model and its price assumptions (USD per million tokens).
DEFAULT_MODEL = "gpt-6-luna"
INPUT_USD_PER_MILLION = 0.10
OUTPUT_USD_PER_MILLION = 0.50
RESPONSES_URL = "https://api.openai.com/v1/responses"


class ModelUnavailable(Exception):
    """No usable model reply: no key, budget stop, transport or provider failure."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str                     # JSON text exactly as the model produced it


@dataclass
class ModelReply:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0

    def item(self) -> dict[str, Any]:
        """This reply as a conversation item."""
        return {"type": "assistant", "text": self.text, "raw": self.raw,
                "tool_calls": [{"id": call.id, "name": call.name, "arguments": call.arguments}
                               for call in self.tool_calls]}


class ModelPort(Protocol):
    name: str

    async def respond(self, system: str, items: list[dict[str, Any]],
                      tools: list[dict[str, Any]]) -> ModelReply: ...


Step = ModelReply | BaseException | Callable[[str, list[dict[str, Any]], list[dict[str, Any]]], ModelReply]


def say(text: str) -> ModelReply:
    return ModelReply(text=text)


def call(name: str, arguments: dict[str, Any] | str | None = None) -> ModelReply:
    """A reply with one tool call; a string is sent as raw (possibly malformed) arguments."""
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments or {})
    return ModelReply(tool_calls=[ToolCall("call_" + uuid.uuid4().hex[:12], name, raw)])


class ScriptedModel:
    """Replays fixed steps for offline tests and records every request it receives."""

    name = "scripted"

    def __init__(self, steps: Sequence[Step]):
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []

    async def respond(self, system: str, items: list[dict[str, Any]],
                      tools: list[dict[str, Any]]) -> ModelReply:
        self.requests.append({"system": system, "items": json.loads(json.dumps(items)),
                              "tools": [tool["name"] for tool in tools]})
        if not self.steps:
            raise RuntimeError("The scripted model has no more steps")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step(system, items, tools) if callable(step) else step


def load_openai_key(env_file: str | Path | None = ".env") -> str | None:
    """OPENAI_API_KEY from the environment, else from an ignored dotenv file; never logged."""
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    path = Path(env_file) if env_file else None
    if path is None or not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "OPENAI_API_KEY" and value.strip().strip("\"'"):
            return value.strip().strip("\"'")
    return None


class OpenAIModel:
    """OpenAI Responses API with function tools, a local usage ledger and a budget stop.

    Requests are stateless (``store: false``); encrypted reasoning items are requested and sent
    back with the rest of the reply so a tool loop keeps its reasoning between calls.
    """

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL,
                 ledger_path: str | Path | None = None, max_cost_usd: float = 5.0,
                 max_calls: int | None = None, client: httpx.AsyncClient | None = None,
                 max_output_tokens: int = 2048):
        if not api_key:
            raise ModelUnavailable("OPENAI_API_KEY is required for agent mode")
        self._key = api_key
        self.name = model
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.max_cost_usd = max_cost_usd
        self.max_calls = max_calls
        self.max_output_tokens = max_output_tokens
        self.client = client or httpx.AsyncClient(timeout=30)
        self.usage: dict[str, Any] = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                      "estimated_usd": 0.0}
        if self.ledger_path and self.ledger_path.is_file():
            try:
                self.usage.update(json.loads(self.ledger_path.read_text(encoding="utf-8")))
            except ValueError:                     # an unreadable ledger means an unknown spend
                raise ModelUnavailable("The model usage ledger is unreadable") from None

    def _save(self) -> None:
        if self.ledger_path is None:
            return
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.ledger_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.usage, indent=2), encoding="utf-8")
        temporary.replace(self.ledger_path)

    @staticmethod
    def _input(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for item in items:
            if item["type"] == "user":
                converted.append({"role": "user", "content": item["text"]})
            elif item["type"] == "note":
                converted.append({"role": "developer", "content": item["text"]})
            elif item["type"] == "assistant":
                if item.get("raw"):
                    converted.extend(item["raw"])
                elif item.get("text"):
                    converted.append({"role": "assistant", "content": item["text"]})
            elif item["type"] == "tool_result":
                converted.append({"type": "function_call_output", "call_id": item["call_id"],
                                  "output": item["output"]})
        return converted

    async def respond(self, system: str, items: list[dict[str, Any]],
                      tools: list[dict[str, Any]]) -> ModelReply:
        payload = {
            "model": self.name, "instructions": system, "input": self._input(items),
            "reasoning": {"effort": "low"}, "max_output_tokens": self.max_output_tokens,
            "store": False, "include": ["reasoning.encrypted_content"],
        }
        if tools:                                  # a summary turn sends no tool fields at all
            payload.update({"tool_choice": "auto", "parallel_tool_calls": False, "tools": [
                {"type": "function", "name": tool["name"], "description": tool["description"],
                 "parameters": tool["parameters"], "strict": False} for tool in tools]})
        size = len(json.dumps(payload))
        # Conservative allowance before every call: about 3 characters per input token.
        projection = (size / 3 * INPUT_USD_PER_MILLION +
                      self.max_output_tokens * OUTPUT_USD_PER_MILLION) / 1_000_000
        if self.usage["estimated_usd"] + projection >= self.max_cost_usd:
            raise ModelUnavailable("Projected model usage exceeds the local budget stop")
        if self.max_calls is not None and self.usage["calls"] >= self.max_calls:
            raise ModelUnavailable("Model call limit reached")
        try:
            response = await self.client.post(RESPONSES_URL, json=payload,
                                              headers={"Authorization": "Bearer " + self._key})
        except httpx.HTTPError:
            raise ModelUnavailable("The model request could not complete") from None
        if response.status_code >= 400:
            raise ModelUnavailable(f"The model request returned HTTP {response.status_code}")
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
                raise ModelUnavailable("The model reply was incomplete")
            output = list(raw.get("output") or [])
            calls = [ToolCall(str(item["call_id"]), str(item["name"]), str(item.get("arguments") or "{}"))
                     for item in output if item.get("type") == "function_call"]
            texts = [part.get("text", "") for item in output if item.get("type") == "message"
                     for part in item.get("content") or [] if part.get("type") == "output_text"]
        except ModelUnavailable:
            raise
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ModelUnavailable("The model returned an unreadable reply") from None
        return ModelReply(text="".join(texts).strip() or None, tool_calls=calls, raw=output,
                          cost_usd=cost)
