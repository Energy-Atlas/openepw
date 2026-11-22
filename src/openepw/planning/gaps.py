"""Data gaps: requested variables a chosen source does not supply, and the ways to cover them.

A plan records one gap per place, chosen source and variable group (``PlanGap``). A gap is
covered by the first fill rule in the request (``WeatherRequest.fills``) that is possible
there: another source supplies the whole group for the same hours, a NOAA station's own
pressure reports give station pressure, or the person leaves the group missing. Without a
rule the gap stays ``unresolved`` and the EPW marks those values missing (9999), as before.

Owner decisions (2026-11-22): whole variables only; GHI, DNI and DHI always come from one
source; no adjustment of a filling source toward the station; station pressure from the
station's own reports where it can be worked out. Hours missing inside a variable are not
filled here (they are reported after retrieval).
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable

from ..models import Candidate, GapOption, PlanGap, VariableFill

GROUPS: dict[str, tuple[str, ...]] = {
    "solar": ("ghi", "dni", "dhi"),
    "pressure": ("pressure",),
    "humidity": ("dew_point", "relative_humidity"),
    "temperature": ("dry_bulb",),
    "wind": ("wind_speed", "wind_direction"),
}
GROUP_LABELS = {
    "solar": "Solar radiation (GHI, DNI, DHI)",
    "pressure": "Station pressure",
    "humidity": "Humidity (dew point, relative humidity)",
    "temperature": "Dry-bulb temperature",
    "wind": "Wind (speed, direction)",
}
VARIABLE_LABELS = {"ghi": "GHI", "dni": "DNI", "dhi": "DHI", "pressure": "station pressure",
                   "dew_point": "dew point", "relative_humidity": "relative humidity",
                   "dry_bulb": "dry-bulb temperature", "wind_speed": "wind speed",
                   "wind_direction": "wind direction"}
# Sources that can fill a group, best first: actual-year, offline discovery, global coverage.
FILL_SOURCES: dict[tuple[str, str], tuple[str, str]] = {
    ("openmeteo", "era5"): ("Open-Meteo ERA5", "25 km reanalysis grid; no key"),
    ("openmeteo", "era5_land"): ("Open-Meteo ERA5-Land", "11 km land grid; no key"),
    ("cds", "reanalysis-era5-single-levels"): (
        "Copernicus CDS ERA5", "reanalysis grid; needs a CDS key and terms; requests queue at Copernicus"),
    ("cds", "reanalysis-era5-land"): (
        "Copernicus CDS ERA5-Land", "land grid; needs a CDS key and terms; requests queue at Copernicus"),
}
SOURCE_NAMES = {"noaa": "NOAA ISD", "openmeteo": "Open-Meteo", "cds": "Copernicus CDS", "nsrdb": "NSRDB"}
# Providers whose adapter can work station pressure out from the station's own reports.
STATION_REPORT_PROVIDERS = frozenset({"noaa"})
MISSING_NOTES = {
    "solar": "solar gains and daylighting cannot be simulated from this file",
    "pressure": "simulation tools use their own default pressure or stop",
}


def source_label(provider: str, dataset: str) -> str:
    """A source's name as people see it: a fill source's label, else the product label offered
    for it (availability/products.py), else the provider and dataset."""
    from ..availability.products import FIXED_PRODUCTS

    known = FILL_SOURCES.get((provider, dataset))
    if known:
        return known[0]
    product = next((item for item in FIXED_PRODUCTS if (item.provider, item.dataset) == (provider, dataset)), None)
    if product is not None:
        return product.label
    return f"{SOURCE_NAMES.get(provider, provider)} {dataset}".strip()


def wanted(group: str, required: Iterable[str]) -> list[str]:
    """The requested variables of a group, in group order (what a fill replaces)."""
    required = set(required)
    return [variable for variable in GROUPS[group] if variable in required]


def missing_groups(variables: Iterable[str], required: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Groups with requested variables the source lacks, and the variables it lacks."""
    have, asked = set(variables), list(required)
    found = []
    for group in GROUPS:
        lacking = [variable for variable in wanted(group, asked) if variable not in have]
        if lacking:
            found.append((group, lacking))
    return found


def station_reports_possible(candidate: Candidate) -> bool:
    """Station pressure from the station's reports needs a NOAA station with a known elevation."""
    location = candidate.source.location
    return (candidate.source.provider in STATION_REPORT_PROVIDERS and location is not None
            and location.elevation is not None)


def gap_options(group: str, candidate: Candidate, fillers: dict[tuple[str, str], Candidate | None],
                required: Iterable[str]) -> list[GapOption]:
    """The ways to cover one gap at one place, the recommended one marked.

    ``fillers`` maps each fill source to its candidate at this place (None where it has none).
    Recommended: the station's reports for pressure where possible, else the first source with
    no key, else the first source, else leaving the group missing.
    """
    options: list[GapOption] = []
    target = {"for_provider": candidate.source.provider, "for_dataset": candidate.source.dataset}
    if group == "pressure" and station_reports_possible(candidate):
        elevation = candidate.source.location.elevation if candidate.source.location else None
        options.append(GapOption(
            fill=VariableFill(group="pressure", method="station_reports", **target),
            label="Use the station's own pressure reports",
            detail=("Measured station pressure, else worked out from the altimeter setting or sea-level "
                    f"pressure with the station elevation ({elevation:g} m); hours without a usable "
                    "report stay missing")))
    variables = wanted(group, required)
    for (provider, dataset), (label, detail) in FILL_SOURCES.items():
        filler = fillers.get((provider, dataset))
        if filler is None or (provider, dataset) == (candidate.source.provider, candidate.source.dataset):
            continue
        if not set(variables) <= set(filler.variables):
            continue
        options.append(GapOption(
            fill=VariableFill(group=group, method="source", provider=provider, dataset=dataset, **target),
            label=f"Fill from {label}", detail=f"Whole variable{'s' if len(variables) > 1 else ''}; {detail}",
            requires_credentials=list(filler.requires_credentials)))
    note = MISSING_NOTES.get(group)
    options.append(GapOption(
        fill=VariableFill(group=group, method="leave_missing", **target), label="Leave missing",
        detail="The EPW marks these values missing (9999)" + (f"; {note}" if note else "")))
    best = next((option for option in options if option.fill.method == "station_reports"), None) or next(
        (option for option in options if option.fill.method == "source" and not option.requires_credentials),
        None) or next((option for option in options if option.fill.method == "source"), None) or options[-1]
    best.recommended = True
    return options


def resolve(group: str, candidate: Candidate, rules: list[VariableFill],
            fillers: dict[tuple[str, str], Candidate | None],
            required: Iterable[str]) -> tuple[str, VariableFill | None, str | None]:
    """The first applicable rule possible here: (status, rule, note on rules skipped)."""
    variables = set(wanted(group, required))
    skipped = []
    for rule in rules:
        if rule.group != group or not rule.applies_to(candidate.source.provider, candidate.source.dataset):
            continue
        if rule.method == "leave_missing":
            return "left_missing", rule, None
        if rule.method == "station_reports":
            if station_reports_possible(candidate):
                return "station_reports", rule, None
            skipped.append("station reports need a NOAA station with a known elevation")
            continue
        assert rule.provider is not None and rule.dataset is not None
        filler = fillers.get((rule.provider, rule.dataset))
        if filler is not None and variables <= set(filler.variables):
            return "filled", rule, None
        skipped.append(f"{source_label(rule.provider, rule.dataset)} has nothing to fill {group} here")
    return "unresolved", None, "; ".join(skipped) or None


def describe(gap: PlanGap) -> str:
    """One line for warnings and summaries."""
    lacking = ", ".join(VARIABLE_LABELS.get(variable, variable) for variable in gap.variables)
    source = source_label(gap.provider, gap.dataset)
    if gap.status == "filled" and gap.fill and gap.fill.provider and gap.fill.dataset:
        return f"{source} has no {lacking}: filled from {source_label(gap.fill.provider, gap.fill.dataset)}"
    if gap.status == "station_reports":
        return f"{source} has no {lacking}: worked out from the station's own pressure reports"
    if gap.status == "left_missing":
        return f"{source} has no {lacking}: left missing by choice (EPW 9999)"
    return f"{source} has no {lacking}: not covered yet (EPW 9999 unless a fill is chosen)"


def row_id(provider: str, dataset: str, group: str) -> str:
    return f"{provider}|{dataset}|{group}"


def option_id(fill: VariableFill) -> str:
    if fill.method == "source":
        return f"source:{fill.provider}:{fill.dataset}"
    return fill.method


def gap_rows(gaps: list[PlanGap]) -> list[dict[str, Any]]:
    """Gaps grouped by chosen source and group, as the person decides them: one row each.

    Each row counts its places and their statuses, lists every option possible at any of them
    (``places`` says at how many), marks the option most often recommended, and names the
    rule already covering it (``chosen``) when every place shares one.
    """
    grouped: dict[str, list[PlanGap]] = {}
    for gap in gaps:
        grouped.setdefault(row_id(gap.provider, gap.dataset, gap.group), []).append(gap)
    rows = []
    for key, items in grouped.items():
        first = items[0]
        options: dict[str, dict[str, Any]] = {}
        recommended: Counter[str] = Counter()
        for gap in items:
            for option in gap.options:
                oid = option_id(option.fill)
                entry = options.setdefault(oid, {
                    "id": oid, "label": option.label, "detail": option.detail,
                    "fill": option.fill.model_dump(mode="json", exclude_none=True),
                    "requires_credentials": option.requires_credentials, "places": 0})
                entry["places"] += 1
                if option.recommended:
                    recommended[oid] += 1
        statuses = Counter(gap.status for gap in items)
        best = recommended.most_common(1)[0][0] if recommended else None
        chosen = {option_id(gap.fill) for gap in items if gap.fill is not None}
        variables = list(dict.fromkeys(variable for gap in items for variable in gap.variables))
        rows.append({
            "id": key, "provider": first.provider, "dataset": first.dataset, "group": first.group,
            "label": GROUP_LABELS[first.group], "source": source_label(first.provider, first.dataset),
            "variables": variables, "places": len({gap.occurrence_index for gap in items}),
            "statuses": dict(statuses), "unresolved": statuses.get("unresolved", 0),
            "options": [{**entry, "recommended": entry["id"] == best} for entry in options.values()],
            "chosen": chosen.pop() if len(chosen) == 1 and not statuses.get("unresolved") else None,
            "notes": sorted({gap.note for gap in items if gap.note}),
        })
    return rows


def distance_km(a: Any, b: Any) -> float | None:
    """Great-circle distance between two locations (objects with lat and lon), or None."""
    if a is None or b is None:
        return None
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)), 1)
