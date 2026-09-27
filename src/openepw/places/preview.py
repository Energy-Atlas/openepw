"""Build place previews and clarification questions for the service layer."""

from __future__ import annotations

import re
from typing import Callable

from ..models import Issue, Location, OpenEPWError, digest
from .geonames import GeoNamesStore
from .models import GEONAMES_ATTRIBUTION, MAX_PLACES, PlacePreview, PlaceRow, PlaceSetQuery
from .parse import (
    AMBIGUOUS_REGIONS,
    POPULATION,
    classify_places,
    describe_place_set,
    parse_coordinates,
)


def build_preview(rows: list[PlaceRow], issues: list[Issue], attribution: list[str]) -> PlacePreview:
    resolved = [row for row in rows if row.status == "resolved"]
    locations = [Location(lat=row.lat, lon=row.lon, id=f"place-{row.index}", name=row.name) for row in resolved]
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]},
                 "properties": {"index": row.index, "name": row.name, "input": row.input,
                                "source": row.source, "ambiguous": row.ambiguous}} for row in resolved]
    return PlacePreview(rows=rows, locations=locations, issues=issues, attribution=attribution,
                        geojson={"type": "FeatureCollection", "features": features},
                        digest=digest([row.model_dump(mode="json") for row in rows]))


def preview_places(items: list[str | dict], geocode: Callable) -> PlacePreview:
    """Resolve a list without per-row confirmation; ambiguity and misses stay visible.

    A dict item is a previously resolved row: it is kept as is (renumbered) so an edit
    never re-geocodes places the user already saw. Unresolved rows are retried by input.
    """
    if len(items) > MAX_PLACES:
        raise OpenEPWError("RESOURCE_LIMIT", f"A preview holds at most {MAX_PLACES} places")
    rows: list[PlaceRow] = []
    issues: list[Issue] = []
    for item in items:
        if isinstance(item, dict):
            pinned = PlaceRow.model_validate(item | {"index": len(rows) + 1})
            if pinned.status == "resolved":
                rows.append(pinned)
                continue
            item = pinned.input
        points = parse_coordinates(item)
        if points is not None:
            for lat, lon in points:
                rows.append(PlaceRow(index=len(rows) + 1, input=item, status="resolved", source="coordinates",
                                     name=f"{lat:.4f}, {lon:.4f}", lat=lat, lon=lon))
        elif describe_place_set(item) is not None:
            raise OpenEPWError("NEEDS_CLARIFICATION",
                               f"'{item}' describes a set of places; clarify it with weather_places_interpret")
        else:
            candidates = geocode(item).candidates
            if not candidates:
                rows.append(PlaceRow(index=len(rows) + 1, input=item, status="unresolved"))
                issues.append(Issue(code="UNRESOLVED_PLACE", severity="warning",
                                    message=f"Place {len(rows)} '{item}' was not found; correct it by text"))
                continue
            top = candidates[0]
            rows.append(PlaceRow(index=len(rows) + 1, input=item, status="resolved", source="geocoder",
                                 name=top.name, lat=top.lat, lon=top.lon, source_id=top.id,
                                 ambiguous=len(candidates) > 1, candidate_count=len(candidates)))
        if len(rows) > MAX_PLACES:
            raise OpenEPWError("RESOURCE_LIMIT", f"A preview holds at most {MAX_PLACES} places")
    ambiguous = [str(row.index) for row in rows if row.ambiguous]
    if ambiguous:
        issues.append(Issue(code="AMBIGUOUS_LOCATION", severity="info",
                            message=f"Place(s) {', '.join(ambiguous)} used the geocoder's top match of several; "
                                    "correct any wrong one by text"))
    return build_preview(rows, issues, [])


def place_set_preview(query: PlaceSetQuery, store: GeoNamesStore) -> PlacePreview:
    result = store.query(query)
    rows = [row.model_copy(update={"name": f"{row.name}, {row.region}" if row.region else row.name})
            for row in result.rows]
    issues = []
    if result.truncated:
        issues.append(Issue(code="PLACE_SET_TRUNCATED", severity="info",
                            message=f"Showing the {len(rows)} most populous of {result.total_matching} matches"))
    source = f"GeoNames {result.source_file} sha256 {result.source_sha256[:12]}, retrieved {result.retrieved_at[:10]}"
    return build_preview(rows, issues, [GEONAMES_ATTRIBUTION, source])


_LIMIT_OPTIONS = [10, 50, 100, MAX_PLACES]
_POPULATION_OPTIONS = [100_000, 50_000, 15_000, 5_000]


def _merge_answer(draft: dict, text: str, store: GeoNamesStore) -> dict:
    """Fill a pending set's missing fields from a clarification reply."""
    merged = dict(draft)
    answer = text.strip()
    options = merged.get("region_options") or []
    if merged.get("region") is None and answer.isdecimal() and 1 <= int(answer) <= len(options):
        merged["region"], merged["region_options"] = options[int(answer) - 1], []
        return merged
    if population := POPULATION.search(answer):
        value = float(population.group(1).replace(",", ""))
        unit = (population.group(2) or "").lower()
        merged["min_population"] = int(value * (1000 if unit in ("k", "thousand") else
                                                1_000_000 if unit in ("m", "million") else 1))
        answer = answer.replace(population.group(0), " ")
    if limit := re.search(r"\btop\s+(\d+)\b", answer, re.I):
        merged["limit"] = int(limit.group(1))
        answer = answer.replace(limit.group(0), " ")
    if re.fullmatch(r"\s*(?:all|all of them|everything)\s*[.!]?\s*", answer, re.I) and merged.get("limit") is None:
        merged["limit"], answer = MAX_PLACES, ""
    for number, unit in re.findall(r"\b(\d[\d,]*)\s*(k|m)?\b", answer, re.I):
        value = int(number.replace(",", "")) * (1000 if unit.lower() == "k" else 1_000_000 if unit.lower() == "m" else 1)
        if merged["kind"] == "city" and merged.get("min_population") is None and value >= 1000:
            merged["min_population"] = value
        elif merged.get("limit") is None and 1 <= value <= MAX_PLACES:
            merged["limit"] = value
    words = re.sub(r"\b\d[\d,]*\s*[km]?\b|\b(?:in|people|population|cities|top|over|above)\b", " ",
                   answer, flags=re.I).strip(" ,.;")
    if merged.get("region") is None and re.search(r"[A-Za-z]", words):
        merged["region_text"] = words
        matches = store.resolve_region(words)
        merged["region"] = matches[0].model_dump(mode="json") if len(matches) == 1 else None
        merged["region_options"] = [match.model_dump(mode="json") for match in matches] if len(matches) > 1 else []
    return merged


def _questions(draft: dict) -> list[dict]:
    questions = []
    if draft.get("region") is None:
        region_text = draft.get("region_text")
        options = draft.get("region_options") or []
        if options:
            prompt = f"Which '{region_text}' do you mean? Reply with a number."
        elif region_text and region_text.casefold().removeprefix("the ") not in AMBIGUOUS_REGIONS:
            prompt = f"'{region_text}' is not a country or first-level division I can list; name one."
        else:
            prompt = "Which region? Name one country, or a state or province; continent-wide sets are not supported."
            options = [{"country": "US", "admin1": None, "label": "United States"}]
        questions.append({"field": "region", "prompt": prompt, "options": options})
    if draft["kind"] == "city" and draft.get("min_population") is None:
        questions.append({"field": "definition", "prompt": "Which places count as cities? Choose a minimum population.",
                          "options": [{"min_population": value} for value in _POPULATION_OPTIONS]})
    if draft.get("limit") is None:
        questions.append({"field": "limit", "prompt": f"How many at most, largest first? (up to {MAX_PLACES})",
                          "options": [{"limit": value} for value in _LIMIT_OPTIONS]})
    return questions


def interpret_places(text: str, store: GeoNamesStore, draft: dict | None = None) -> dict:
    """Classify place text; descriptive sets return questions until a query is complete.

    With ``draft`` the text is a clarification reply that fills the pending set.
    """
    if draft is None:
        try:
            routed = classify_places(text)
        except OpenEPWError as error:
            return {"kind": "invalid", "issue": error.issue.model_dump(mode="json")}
        if routed["kind"] == "coordinates":
            return {"kind": "coordinates", "points": [[lat, lon] for lat, lon in routed["points"]]}
        if routed["kind"] != "descriptive":
            return routed
        found = routed["draft"]
        draft = {"kind": found.kind, "region_text": found.region_text, "region": None, "region_options": [],
                 "min_population": found.min_population, "limit": found.limit}
        if found.region_text and found.region_text.casefold().removeprefix("the ") not in AMBIGUOUS_REGIONS:
            matches = store.resolve_region(found.region_text)
            if len(matches) == 1:
                draft["region"] = matches[0].model_dump(mode="json")
            else:
                draft["region_options"] = [match.model_dump(mode="json") for match in matches]
    else:
        draft = _merge_answer(draft, text, store)
    questions = _questions(draft)
    query = None
    if not questions:
        query = PlaceSetQuery(kind=draft["kind"], country=draft["region"]["country"],
                              admin1=draft["region"].get("admin1"), min_population=draft.get("min_population"),
                              limit=draft["limit"]).model_dump(mode="json")
    return {"kind": "descriptive", "questions": questions, "query": query, "draft": draft}
