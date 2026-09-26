"""Structured, redacted MCP activity for the interactive console."""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .agent import safe_prompt
from .mcp_client import MCPToolFailure, StdioMCPPort

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.+ -]{1,100}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INTEGER_FIELDS = ("output_count", "estimated_calls", "completed", "failed", "total")
_RESULT_TEXT_FIELDS = ("plan_hash", "id", "artifact_id", "kind", "state", "status")


def _token(value: Any) -> str | None:
    if isinstance(value, str) and _SAFE_TOKEN.fullmatch(value) and not value.lower().startswith("sk-"):
        return value
    return None


def _request_summary(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {}
    summary: dict[str, Any] = {}
    for key in ("product", "method", "missing_policy", "climate_scenario"):
        value = _token(request.get(key))
        if value is not None:
            summary[key] = value
    years = request.get("years")
    if isinstance(years, list) and len(years) <= 100 and all(
            type(year) is int and 1900 <= year <= 2200 for year in years):
        summary["years"] = years
    for key in ("start", "end"):
        value = request.get(key)
        if isinstance(value, str) and _DATE.fullmatch(value):
            summary[key] = value
    for key in ("climate_period", "reference_period"):
        value = request.get(key)
        if (isinstance(value, list) and len(value) == 2 and
                all(type(year) is int and 1900 <= year <= 2200 for year in value)):
            summary[key] = value
    providers = request.get("providers")
    if isinstance(providers, list) and len(providers) <= 10:
        clean = [_token(item) for item in providers]
        if all(item is not None for item in clean):
            summary["providers"] = clean
    locations = request.get("locations")
    if isinstance(locations, list):
        summary["location_count"] = len(locations)
    elif isinstance(locations, dict):
        summary["location_count"] = 1
    return summary


def _arguments_summary(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    summary = _request_summary(arguments.get("request"))
    if name == "weather_assess" and isinstance(arguments.get("query"), dict):
        summary.update(_request_summary(arguments["query"].get("request")))
    for key in ("plan_hash", "job_id", "artifact_id"):
        value = _token(arguments.get(key))
        if value is not None:
            summary[key] = value
    if name == "weather_geocode":
        query = arguments.get("query")
        if isinstance(query, str):
            summary["query"] = safe_prompt(query, limit=120)
    if name == "baseline_upload":
        encoded = arguments.get("content_base64")
        if isinstance(encoded, str):
            try:
                summary["bytes"] = len(base64.b64decode(encoded, validate=True))
            except (ValueError, binascii.Error):
                summary["bytes"] = "invalid encoding"
    if name == "baseline_register_path":
        summary["local_path_provided"] = bool(arguments.get("path"))
    if not summary:
        summary["argument_names"] = sorted(arguments)
    return summary


def _result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in _RESULT_TEXT_FIELDS:
        value = _token(result.get(key))
        if value is not None:
            summary[key] = value
    for key in _INTEGER_FIELDS:
        value = result.get(key)
        if type(value) is int:
            summary[key] = value
    ready = result.get("simulation_ready")
    if isinstance(ready, bool):
        summary["simulation_ready"] = ready
    for source, target in (("candidates", "candidate_count"),
                           ("artifacts", "artifact_count"),
                           ("options", "option_count")):
        value = result.get(source)
        if isinstance(value, list):
            summary[target] = len(value)
    return summary


class ConsoleMCPPort(StdioMCPPort):
    """Print one call and one result/error record for each actual MCP invocation."""

    def __init__(self, data_root: str | Path, *,
                 allowed_roots: list[str | Path] | None = None,
                 server_args: list[str] | None = None,
                 before_message: Callable[[], None] | None = None):
        super().__init__(data_root, allowed_roots=allowed_roots,
                         server_args=server_args)
        self.before_message = before_message
        self._next_call_id = 0

    def _emit(self, record: dict[str, Any]) -> None:
        if self.before_message is not None:
            self.before_message()
        print("Tool> " + json.dumps(record, ensure_ascii=False,
                                   sort_keys=True, separators=(",", ":")), flush=True)

    async def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        self._next_call_id += 1
        call_id = self._next_call_id
        self._emit({"event": "call", "tool": name, "call_id": call_id,
                    "arguments": _arguments_summary(name, arguments)})
        start = time.monotonic()
        try:
            result = await super().call(name, **arguments)
        except BaseException as error:
            code = error.code if isinstance(error, MCPToolFailure) else type(error).__name__
            self._emit({"event": "error", "tool": name, "call_id": call_id,
                        "code": _token(code) or "TOOL_ERROR"})
            raise
        self._emit({"event": "result", "tool": name, "call_id": call_id,
                    "summary": _result_summary(result),
                    "duration_ms": round((time.monotonic() - start) * 1000)})
        return result
