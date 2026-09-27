"""Deterministic parsing of place text: coordinates, place lists, set descriptions, edits.

This module is pure. It never geocodes or downloads; the service resolves the results.
Coordinates are always latitude first and are never swapped or repaired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import OpenEPWError

_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_HEMISPHERE = re.compile(rf"({_NUMBER})\s*°?\s*([NSEW])\b", re.I)
_GEOMETRY_WORDS = re.compile(r"\b(?:bbox|bounding|box|polygon|area|between|within|rectangle|extent)\b", re.I)
_COORDINATE_CHARS = re.compile(r"[\s\d.,;:+\-()\[\]°]+")

US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
    "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
    "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
}
# A small, common set; the model parser handles anything this fallback cannot split.
COUNTRIES = {
    "usa", "united states", "canada", "mexico", "brazil", "argentina", "chile", "uk", "united kingdom",
    "england", "scotland", "wales", "ireland", "france", "germany", "spain", "portugal", "italy",
    "netherlands", "belgium", "switzerland", "austria", "sweden", "norway", "denmark", "finland",
    "poland", "greece", "turkey", "egypt", "south africa", "nigeria", "kenya", "india", "china",
    "japan", "south korea", "australia", "new zealand", "singapore", "indonesia",
}


def _is_qualifier(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{2}", token)) or token.casefold() in US_STATES | COUNTRIES


def _latlon(lat: float, lon: float) -> tuple[float, float]:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise OpenEPWError("INVALID_COORDINATES",
                           f"Latitude {lat:g}, longitude {lon:g} is out of range; give latitude first")
    return (lat, lon)


def parse_coordinates(text: str) -> list[tuple[float, float]] | None:
    """Parse one point or a list of points; None when the text is not coordinates."""
    stripped = text.strip()
    numbers = re.findall(_NUMBER, stripped)
    if numbers and _GEOMETRY_WORDS.search(stripped):
        raise OpenEPWError("UNSUPPORTED_GEOGRAPHY", "Only points or lists of points are supported")
    hemispheres = _HEMISPHERE.findall(stripped)
    if hemispheres:
        if not _COORDINATE_CHARS.fullmatch(_HEMISPHERE.sub(" ", stripped) or " "):
            return None
        if len(hemispheres) % 2:
            raise OpenEPWError("INVALID_COORDINATES", "Each point needs a latitude and a longitude")
        points = []
        for (lat, ns), (lon, ew) in zip(hemispheres[::2], hemispheres[1::2]):
            if ns.upper() not in "NS" or ew.upper() not in "EW":
                raise OpenEPWError("INVALID_COORDINATES", "Give latitude (N/S) before longitude (E/W)")
            points.append(_latlon(float(lat) * (-1 if ns.upper() == "S" else 1),
                                  float(lon) * (-1 if ew.upper() == "W" else 1)))
        return points
    if not _COORDINATE_CHARS.fullmatch(stripped) or len(numbers) < 2:
        return None
    if len(numbers) % 2:
        raise OpenEPWError("INVALID_COORDINATES", "Each point needs a latitude and a longitude")
    values = [float(value) for value in numbers]
    return [_latlon(lat, lon) for lat, lon in zip(values[::2], values[1::2])]


def split_place_list(text: str) -> list[str]:
    """Split a place list; region qualifiers such as ", MA" stay with their place."""
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) > 1 or ";" in text:
        return [part.strip() for line in lines for part in line.split(";") if part.strip()]
    tokens = [token.strip() for part in re.split(r",", lines[0] if lines else "")
              for token in re.split(r"\s+(?:and|&)\s+", part) if token.strip()]
    items: list[str] = []
    for token in tokens:
        if items and _is_qualifier(token) and not _is_qualifier(items[-1].rsplit(",", 1)[-1].strip()):
            items[-1] = f"{items[-1]}, {token}"
        else:
            items.append(token)
    return items


@dataclass
class PlaceSetDraft:
    kind: str                      # "city" or "capital"
    region_text: str | None
    min_population: int | None
    limit: int | None
    missing: list[str] = field(default_factory=list)


AMBIGUOUS_REGIONS = {"america", "the americas", "americas"}
_SET_KIND = re.compile(r"\b(state capitals?|capitals?|cities|towns|municipalities)\b", re.I)
_QUANTIFIER = re.compile(r"\b(?:all|every|each|top\s+\d+|largest|biggest|major|list of)\b", re.I)
POPULATION = re.compile(r"(?:over|above|more than|at least|exceeding|>=?)\s+([\d,.]+)\s*(k|thousand|m|million)?",
                         re.I)
_REGION = re.compile(r"\b(?:in|across|within|throughout)\s+((?:the\s+)?[A-Z][\w.'\- ]*?)"
                     r"(?=\s*(?:,|;|\.|$|\btop\b|\bwith\b|\bover\b|\babove\b))")
_LIMIT = re.compile(r"\btop\s+(\d+)\b|\b(\d+)\s+(?:largest|biggest)\b", re.I)


def describe_place_set(text: str) -> PlaceSetDraft | None:
    """Recognise 'all cities in X'-style requests and list what still needs clarifying."""
    kind_match = _SET_KIND.search(text)
    population = POPULATION.search(text)
    if not kind_match or not (_QUANTIFIER.search(text) or population):
        return None
    kind = "capital" if "capital" in kind_match.group(1).lower() else "city"
    region = _REGION.search(text)
    region_text = region.group(1).strip() if region else None
    min_population = None
    if population:
        value = float(population.group(1).replace(",", ""))
        unit = (population.group(2) or "").lower()
        value *= 1000 if unit in ("k", "thousand") else 1_000_000 if unit in ("m", "million") else 1
        min_population = int(value)
    limit_match = _LIMIT.search(text)
    limit = int(next(group for group in limit_match.groups() if group)) if limit_match else None
    missing = []
    if region_text is None or region_text.casefold() in AMBIGUOUS_REGIONS:
        missing.append("region")
    if kind == "city" and min_population is None:
        missing.append("definition")
    if limit is None:
        missing.append("limit")
    return PlaceSetDraft(kind, region_text, min_population, limit, missing)


def classify_places(text: str) -> dict:
    """Route place text: coordinates, a descriptive set, a list, or one place name."""
    points = parse_coordinates(text)
    if points is not None:
        return {"kind": "coordinates", "points": points}
    draft = describe_place_set(text)
    if draft is not None:
        return {"kind": "descriptive", "draft": draft}
    items = split_place_list(text)
    return {"kind": "list" if len(items) > 1 else "single", "items": items}


def _index(items: list[str], target: str) -> int:
    target = target.strip()
    if target.isdecimal():
        index = int(target) - 1
        if not 0 <= index < len(items):
            raise OpenEPWError("INVALID_EDIT", f"There is no place {target}; the list has {len(items)}")
        return index
    for index, item in enumerate(items):
        if item.casefold() == target.casefold() or item.casefold().startswith(target.casefold() + ","):
            return index
    raise OpenEPWError("INVALID_EDIT", f"'{target}' is not in the current list")


def apply_edit(items: list[str], text: str) -> list[str] | None:
    """Apply a text correction to a previewed list; None when the text is not an edit."""
    line = text.strip().rstrip(".!")
    updated = list(items)
    if match := re.fullmatch(r"(?:remove|drop|delete)\s+(?:place\s+|number\s+)?(.+)", line, re.I):
        del updated[_index(updated, match.group(1))]
        return updated
    if match := re.fullmatch(r"(?:replace|change|swap)\s+(?:place\s+|number\s+)?(.+?)\s+(?:with|to|for)\s+(.+)",
                             line, re.I):
        updated[_index(updated, match.group(1))] = match.group(2).strip()
        return updated
    if match := re.fullmatch(r"add\s+(.+)", line, re.I):
        return updated + split_place_list(match.group(1))
    return None
