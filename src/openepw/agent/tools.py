"""What the model may call: MCP model tools plus host ask-tools, and how results reach it."""

from __future__ import annotations

import json
from typing import Any

from ..mcp.access import MODEL_TOOLS
from .mcp_port import ToolResult

_POINT = {"type": "object", "properties": {
    "lat": {"type": "number"}, "lon": {"type": "number"}, "name": {"type": "string"}},
    "required": ["lat", "lon"]}

# Host ask-tools open a form; the person's answer becomes the tool's result.
ASK_TOOLS: dict[str, dict[str, Any]] = {
    "review_location": {
        "description": (
            "Show the person the resolved locations, with their fixed standard-time offsets, for "
            "approval. Required before choose_products and weather_plan. Pass coordinates you got "
            "from weather_geocode, weather_places_preview or the person; never guess coordinates."),
        "parameters": {"type": "object", "properties": {
            "locations": {"anyOf": [_POINT, {"type": "array", "items": _POINT, "maxItems": 1000}]}},
            "required": ["locations"]}},
    "choose_products": {
        "description": (
            "After the locations are approved, list the downloadable weather products with "
            "catalog availability and let the person choose. Never choose for them. Optional "
            "filters narrow the offers to a product kind or provider the person asked for."),
        "parameters": {"type": "object", "properties": {
            "product": {"type": "string", "enum": ["historical", "tmy", "tmyx", "published"]},
            "provider": {"type": "string"}}}},
    "ask_text": {
        "description": (
            "Ask the person a short question answered in words, for example which actual years "
            "they need (purpose 'years'). Use it instead of guessing."),
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string"}, "hint": {"type": "string"},
            "purpose": {"type": "string", "enum": ["years", "other"]}},
            "required": ["prompt"]}},
    "ask_choice": {
        "description": (
            "Ask the person to pick from listed options, for example which of several geocoded "
            "places they mean. Option ids are returned as the answer."),
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string"},
            "options": {"type": "array", "minItems": 1, "maxItems": 20, "items": {
                "type": "object", "properties": {
                    "id": {"type": "string"}, "label": {"type": "string"}, "detail": {"type": "string"}},
                "required": ["id", "label"]}},
            "multi": {"type": "boolean"}},
            "required": ["prompt", "options"]}},
    "request_map_input": {
        "description": "Ask the person to give the place: a name, a list, or coordinates.",
        "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}}},
    "request_upload": {
        "description": "Ask the person to attach an EPW file; the answer is its artifact id.",
        "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}}},
    "review_plan": {
        "description": (
            "Show the plans made with weather_plan to the person. Only the person can run them; "
            "you cannot submit. Call it after weather_plan succeeds."),
        "parameters": {"type": "object", "properties": {}}},
}
# The step each gate needs, named as the ask-tool or MCP tool the model should call.
NEED_TOOL = {"review_location": "review_location", "choose_products": "choose_products",
             "years": "ask_text", "plan": "weather_plan", "review_plan": "review_plan"}
RESULT_LIMIT = 4000


async def model_tools(port: Any) -> list[dict[str, Any]]:
    """The model's tool list: the server's model tools (live schemas) plus the ask-tools."""
    listed = await port.list_tools()
    tools = [tool for tool in listed if tool["name"] in MODEL_TOOLS]
    return tools + [{"name": name, **spec} for name, spec in ASK_TOOLS.items()]


def _compact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, dict):
        return {key: _compact(item, depth + 1) for key, item in value.items()
                if depth < 4 and key not in ("pages", "spec", "page", "series")}
    if isinstance(value, list):
        items = [_compact(item, depth + 1) for item in value[:10]]
        return items + [f"... {len(value) - 10} more"] if len(value) > 10 else items
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "..."
    return value


def shape(result: ToolResult) -> str:
    """The tool's summary plus a compact copy of its data (at most 4 KB) for the model."""
    data = json.dumps(_compact(result.data), default=str)
    if len(data) + len(result.text) > RESULT_LIMIT:
        data = json.dumps({key: result.data[key] for key in result.data
                           if key.endswith("id") or key.endswith("_hash") or key == "key"}, default=str)
    shaped = json.dumps({"summary": result.text, "data": json.loads(data)})
    if len(shaped) > RESULT_LIMIT:                # still too long: the summary alone, cut
        shaped = json.dumps({"summary": result.text[:RESULT_LIMIT - 100], "data": {}})
    return shaped
