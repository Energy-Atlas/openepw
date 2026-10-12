"""Fixed standard-time offsets for requested points and the note shown before an actual-year run."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..models import Location, WeatherRequest, nominal_offset_minutes


def estimate_offsets(value: Any) -> tuple[Any, dict | None, bool]:
    """Choose a fixed offset for points that lack one; preserve supplied offsets.

    Returns the geography, the sampling override for an area (or None) and whether any
    offset was estimated from longitude.
    """
    if isinstance(value, list):
        points = [estimate_offsets(point) for point in value]
        return [point for point, _, _ in points], None, any(estimated for _, _, estimated in points)
    if isinstance(value, dict) and ("west" in value or value.get("type") == "Polygon"):
        return value, {"standard_offset": "longitude"}, True
    point = Location.model_validate(value)
    if "standard_offset_minutes" not in point.model_fields_set:
        local = point.model_copy(update={"standard_offset_minutes": nominal_offset_minutes(point.lon)})
        return local.model_dump(mode="json"), None, True
    return point.model_dump(mode="json"), None, False


def request_points(request: WeatherRequest) -> list[Location]:
    """The points a request resolves to: one location, a list, or a sampled area."""
    if isinstance(request.locations, Location):
        return [request.locations]
    if isinstance(request.locations, list):
        return request.locations
    from .spatial import sample

    return sample(request.locations, request.sampling)


def standard_time_note(points: list[Location], estimated: bool) -> str:
    """Show the clock convention before the person runs an actual-year plan."""
    offsets = sorted({point.standard_offset_minutes for point in points})
    labels = [f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
              for minutes in offsets]
    note = "Fixed standard time: " + ", ".join(labels) + "; no daylight-saving shift."
    if estimated:
        note += " Some offsets were estimated from longitude and may differ from local civil standard time."
    return note


def location_key(value: Any) -> str:
    """Identifies a reviewed geography, so a changed one needs approval again."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]
