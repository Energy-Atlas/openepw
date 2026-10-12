"""Publish inlined JSON schemas for dict-typed MCP parameters so clients see real fields.

Parameters stay plain dicts at runtime so the server validates them itself and can return
field-level errors; only the published input schema changes.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, WithJsonSchema

from ..availability import WeatherAvailabilityQuery
from ..models import WeatherRequest
from ..places.models import PlaceSetQuery
from ..visualization import VisualizationRequest


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema with every ``$ref`` replaced by its definition."""
    root = model.model_json_schema()
    definitions = root.pop("$defs", {})

    def resolve(node: Any, seen: tuple[str, ...] = ()) -> Any:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str):
                name = reference.rsplit("/", 1)[-1]
                if name in seen:                       # a recursive model stops here
                    return {"type": "object"}
                merged = {**definitions[name], **{key: value for key, value in node.items()
                                                  if key != "$ref"}}
                return resolve(merged, seen + (name,))
            return {key: resolve(value, seen) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        return node

    return resolve(root)


WeatherRequestArg = Annotated[dict[str, Any], WithJsonSchema(inline_schema(WeatherRequest))]
AvailabilityQueryArg = Annotated[dict[str, Any],
                                 WithJsonSchema(inline_schema(WeatherAvailabilityQuery))]
PlaceSetQueryArg = Annotated[dict[str, Any], WithJsonSchema(inline_schema(PlaceSetQuery))]
VisualizationRequestArg = Annotated[dict[str, Any],
                                    WithJsonSchema(inline_schema(VisualizationRequest))]
GeographyArg = Annotated[Any, WithJsonSchema(inline_schema(WeatherRequest)["properties"]["locations"])]
