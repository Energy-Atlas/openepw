"""Build place previews and clarification questions for the service layer."""

from __future__ import annotations

from typing import Callable

from ..models import Issue, Location, OpenEPWError, digest
from .geonames import GeoNamesStore
from .models import GEONAMES_ATTRIBUTION, MAX_PLACES, PlacePreview, PlaceRow, PlaceSetQuery
from .parse import AMBIGUOUS_REGIONS, classify_places, describe_place_set, parse_coordinates


def build_preview(rows: list[PlaceRow], issues: list[Issue], attribution: list[str]) -> PlacePreview:
    resolved = [row for row in rows if row.status == "resolved"]
    locations = [Location(lat=row.lat, lon=row.lon, id=f"place-{row.index}", name=row.name) for row in resolved]
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]},
                 "properties": {"index": row.index, "name": row.name, "input": row.input,
                                "source": row.source, "ambiguous": row.ambiguous}} for row in resolved]
    return PlacePreview(rows=rows, locations=locations, issues=issues, attribution=attribution,
                        geojson={"type": "FeatureCollection", "features": features},
                        digest=digest([row.model_dump(mode="json") for row in rows]))


def preview_places(items: list[str], geocode: Callable) -> PlacePreview:
    """Resolve a list without per-row confirmation; ambiguity and misses stay visible."""
    if len(items) > MAX_PLACES:
        raise OpenEPWError("RESOURCE_LIMIT", f"A preview holds at most {MAX_PLACES} places")
    rows: list[PlaceRow] = []
    issues: list[Issue] = []
    for item in items:
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


def interpret_places(text: str, store: GeoNamesStore) -> dict:
    """Classify place text; descriptive sets return questions until a query is complete."""
    try:
        routed = classify_places(text)
    except OpenEPWError as error:
        return {"kind": "invalid", "issue": error.issue.model_dump(mode="json")}
    if routed["kind"] == "coordinates":
        return {"kind": "coordinates", "points": [[lat, lon] for lat, lon in routed["points"]]}
    if routed["kind"] != "descriptive":
        return routed
    draft = routed["draft"]
    questions = []
    region = None
    if draft.region_text and draft.region_text.casefold().removeprefix("the ") not in AMBIGUOUS_REGIONS:
        matches = store.resolve_region(draft.region_text)
        if len(matches) == 1:
            region = matches[0]
        else:
            questions.append({"field": "region", "prompt": (
                f"Which '{draft.region_text}' do you mean?" if matches else
                f"'{draft.region_text}' is not a country or first-level division I can list; name one."),
                "options": [match.model_dump(mode="json") for match in matches]})
    else:
        questions.append({"field": "region", "prompt": (
            "Which region? Name one country, or a state or province; continent-wide sets are not supported."),
            "options": [{"country": "US", "admin1": None, "label": "United States"}]})
    if draft.kind == "city" and draft.min_population is None:
        questions.append({"field": "definition", "prompt": "Which places count as cities? Choose a minimum population.",
                          "options": [{"min_population": value} for value in _POPULATION_OPTIONS]})
    if draft.limit is None:
        questions.append({"field": "limit", "prompt": f"How many at most, largest first? (up to {MAX_PLACES})",
                          "options": [{"limit": value} for value in _LIMIT_OPTIONS]})
    query = None
    if not questions and region is not None:
        query = PlaceSetQuery(kind=draft.kind, country=region.country, admin1=region.admin1,
                              min_population=draft.min_population, limit=draft.limit).model_dump(mode="json")
    return {"kind": "descriptive", "questions": questions, "query": query,
            "draft": {"kind": draft.kind, "region_text": draft.region_text,
                      "region": region.model_dump(mode="json") if region else None,
                      "min_population": draft.min_population, "limit": draft.limit}}
