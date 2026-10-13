"""Fixed standard-time offsets for requested points and the note shown before an actual-year run."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..models import Location, WeatherRequest
from .timezones import LOOKUP, describe, label, zone_offset

# The note lists the offsets of at most this many points, one per distinct description.
NOTE_POINTS = 50


def estimate_offsets(value: Any) -> tuple[Any, dict | None, bool]:
    """Choose a fixed offset for points that lack one, from the point's time zone; preserve
    supplied offsets.

    Returns the geography, the sampling override for an area (or None) and whether the
    service chose any offset (the person must see and approve it).
    """
    if isinstance(value, list):
        points = [estimate_offsets(point) for point in value]
        return [point for point, _, _ in points], None, any(estimated for _, _, estimated in points)
    if isinstance(value, dict) and ("west" in value or value.get("type") == "Polygon"):
        return value, {"standard_offset": "zone"}, True
    point = Location.model_validate(value)
    if "standard_offset_minutes" not in point.model_fields_set:
        local = point.model_copy(update={"standard_offset_minutes": zone_offset(point.lat, point.lon).offset_minutes})
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
    """Show the clock convention, and where each chosen offset came from, before a run."""
    labels: list[str] = []
    for point in points[:NOTE_POINTS]:
        text = label(point.standard_offset_minutes)
        if estimated:
            found = zone_offset(point.lat, point.lon)
            if found.offset_minutes == point.standard_offset_minutes:
                text = describe(found)
        if text not in labels:
            labels.append(text)
    if len(points) > NOTE_POINTS:
        extra = {point.standard_offset_minutes for point in points[NOTE_POINTS:]}
        labels += [label(minutes) for minutes in sorted(extra) if label(minutes) not in labels]
    note = "Fixed standard time: " + ", ".join(labels) + "; no daylight-saving shift."
    if estimated:
        note += (" Offsets not given come from each place's time zone (standard time all year, as EPW"
                 " files use); a typed offset replaces it.")
    return note


def year_offset_warnings(points: list[Location], years: list[int]) -> list[str]:
    """Years in which a point's zone kept a different standard time than the file uses, for
    points whose offset matches their zone today (such as Singapore before 1982)."""
    warnings = []
    for point in points[:NOTE_POINTS]:
        today = zone_offset(point.lat, point.lon)
        if today.source != LOOKUP or today.offset_minutes != point.standard_offset_minutes:
            continue
        for year in years:
            then = zone_offset(point.lat, point.lon, year)
            if then.zone == today.zone and (then.offset_minutes != today.offset_minutes or then.changed):
                warnings.append(
                    f"{point.name or f'{point.lat:.4f}, {point.lon:.4f}'}: standard time in {then.zone} was "
                    f"{label(then.civil_minutes or then.offset_minutes)} in {year}"
                    + (" and changed during that year" if then.changed else "")
                    + f"; this file uses {label(point.standard_offset_minutes)}.")
    return list(dict.fromkeys(warnings))


def location_key(value: Any) -> str:
    """Identifies a reviewed geography, so a changed one needs approval again."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]
