"""Pure geographic, temporal and adapter eligibility decisions."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timezone

from openepw.models import Issue, Location, digest
from openepw.planning.spatial import sample

from .models import (
    ActualScope,
    AvailabilityEntry,
    AvailabilityQuery,
    AvailabilityResult,
    EligibilityDecision,
    FutureAvailabilityQuery,
    FutureWindowScope,
    LocationAssessment,
    ProductRecord,
    SiteRecord,
    SuitabilityOption,
    TMYReferenceScope,
    WeatherAvailabilityQuery,
)
from .store import CatalogView

_PURPOSE_FIELDS = {
    "building_energy": ["dry_bulb", "dew_point", "relative_humidity", "pressure", "wind_speed",
                        "wind_direction", "ghi"],
    "solar": ["ghi", "dni", "dhi"],
    "thermal_extremes": ["dry_bulb", "dew_point"],
}


def _locations(query: AvailabilityQuery) -> list[Location]:
    if isinstance(query, FutureAvailabilityQuery):
        return [query.location]
    locs = query.request.locations
    if isinstance(locs, Location):
        return [locs]
    if isinstance(locs, list):
        return locs
    return sample(locs, query.request.sampling)


def _distance(a: Location, b: SiteRecord) -> float | None:
    if b.lat is None or b.lon is None:
        return None
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _requested_years(query: WeatherAvailabilityQuery) -> list[int]:
    request = query.request
    if request.years:
        return sorted(request.years)
    if request.start and request.end:
        return list(range(request.start.year, request.end.year + 1))
    return []


def _relevant_product(query: AvailabilityQuery, product: ProductRecord) -> bool:
    if isinstance(query, FutureAvailabilityQuery):
        return product.temporal_kind == "future_window"
    request = query.request
    if request.providers and product.provider not in request.providers:
        return False
    if request.dataset_selections and not any(
        selection.provider == product.provider and selection.dataset == product.dataset
        for selection in request.dataset_selections
    ):
        return False
    if request.dataset and request.dataset != product.dataset:
        return False
    if (request.product_id and product.provider == "onebuilding" and
            request.product_id not in (
                product.native_product_id, product.id,
                (product.native_product_id or "").split("climate.onebuilding.org/", 1)[-1],
            )):
        return False
    return True


def _candidate_sites(query: AvailabilityQuery, location: Location, product: ProductRecord,
                     sites: list[SiteRecord],
                     entries_by_site: dict[tuple[str, str | None], list[AvailabilityEntry]]) -> Sequence[SiteRecord | None]:
    if not sites:
        return [None]
    if (isinstance(query, WeatherAvailabilityQuery) and product.provider == "noaa" and
            query.request.product_id):
        return [site for site in sites if site.id == query.request.product_id]
    if product.provider == "onebuilding" and isinstance(query, WeatherAvailabilityQuery):
        if query.request.product_id:
            return sites[:1]
    known = [(distance, site) for site in sites if (distance := _distance(location, site)) is not None
             and site.position_status not in ("approximate_locality", "conflicted")]
    known.sort(key=lambda item: (item[0], item[1].id))
    if product.provider == "noaa" and isinstance(query, WeatherAvailabilityQuery) and known:
        requested = set(_requested_years(query))
        nearby = [(distance, site) for distance, site in known if distance <= 100]
        listed = [(distance, site) for distance, site in nearby if any(
            isinstance(entry.scope, ActualScope) and requested <= set(entry.scope.years)
            for entry in entries_by_site.get((product.id, site.id), []))]
        supported_ids = {site.id for _, site in listed[:5]}
        uncertain = [site for _, site in nearby if site.id not in supported_ids][:3]
        chosen = [site for _, site in listed[:5]] + uncertain
        if chosen:
            return chosen
    if known:
        return [site for _, site in known[:5]]
    return sites[:1]


def _temporal(query: AvailabilityQuery, entry: AvailabilityEntry,
              product: ProductRecord) -> tuple[str, list[str], list[str]]:
    scope = entry.scope
    if isinstance(query, FutureAvailabilityQuery):
        if not isinstance(scope, FutureWindowScope):
            return "excluded", ["TEMPORAL_KIND_MISMATCH"], []
        if scope.scenario != query.scenario:
            return "excluded", ["SCENARIO_MISMATCH"], []
        if scope.start_year is None or scope.end_year is None:
            return "unknown", [], ["CLIMATE_WINDOW_UNVERIFIED"]
        if (scope.start_year, scope.end_year) != query.climate_period:
            return "excluded", ["WINDOW_NOT_PUBLISHED"], []
        if scope.listed_years and set(range(scope.start_year, scope.end_year + 1)) - set(scope.listed_years):
            return "unknown", [], ["WINDOW_MEMBERSHIP_INCOMPLETE"]
        return "supported", ["WINDOW_LISTED"], []
    if query.request.product in ("historical", "amy"):
        if not isinstance(scope, ActualScope):
            return "excluded", ["TEMPORAL_KIND_MISMATCH"], []
        years = _requested_years(query)
        if scope.years:
            if set(years) <= set(scope.years):
                return "supported", ["YEAR_LISTED"], []
            return "unknown", [], ["YEAR_NOT_LISTED_IN_DATED_INVENTORY"]
        if scope.operating_start and min(years, default=scope.operating_start.year) < scope.operating_start.year:
            return "excluded", ["BEFORE_DOCUMENTED_START"], []
        if scope.operating_end and max(years, default=scope.operating_end.year) > scope.operating_end.year:
            return "unknown", [], ["AFTER_DATED_CATALOG_END"]
        if not scope.operating_end and max(years, default=0) >= datetime.now(timezone.utc).year:
            return "unknown", [], ["MOVING_END_UNVERIFIED"]
        if entry.evidence_basis == "documentation" and entry.site_id is None:
            return "supported", ["DOCUMENTED_PERIOD"], []
        return "unknown", [], ["OPERATING_INTERVAL_NOT_REPORT_COVERAGE"]
    if not isinstance(scope, TMYReferenceScope):
        return "excluded", ["TEMPORAL_KIND_MISMATCH"], []
    if product.provider == "nsrdb" and query.request.product_id and query.request.product_id != scope.product_label and (
        query.request.product_id not in entry.id
    ):
        return "excluded", ["PUBLISHED_PRODUCT_MISMATCH"], []
    return "supported", ["PUBLISHED_PRODUCT_LISTED"], []


def _assess(query: AvailabilityQuery, location: Location, product: ProductRecord,
            site: SiteRecord | None, entries: list[AvailabilityEntry],
            stale_sources: set[str]) -> tuple[EligibilityDecision, float | None, float | None]:
    reasons = []
    unknowns = []
    distance = _distance(location, site) if site else None
    elevation_delta = (abs(location.elevation - site.elevation_m)
                       if site and location.elevation is not None and site.elevation_m is not None
                       else None)
    if isinstance(query, FutureAvailabilityQuery):
        if (query.method == "morph" and product.provider != "cmip6") or (
            query.method == "climate_profile" and product.provider != "oedi"
        ):
            reasons.append("METHOD_PRODUCT_MISMATCH")
    elif (query.request.product in ("historical", "amy")) != (product.temporal_kind == "actual"):
        reasons.append("TEMPORAL_KIND_MISMATCH")
    if not product.adapter_supported:
        reasons.append("ADAPTER_PRODUCT_UNSUPPORTED")
    explicit_noaa = (isinstance(query, WeatherAvailabilityQuery) and product.provider == "noaa"
                     and site is not None and query.request.product_id == site.id)
    if product.provider == "noaa" and not explicit_noaa and distance is not None and distance > 100:
        reasons.append("BEYOND_PROVIDER_SEARCH_RADIUS")
    if product.provider == "oedi" and distance is not None and distance > 150:
        reasons.append("BEYOND_PROVIDER_SEARCH_RADIUS")
    if query.max_distance_km is not None and distance is not None and distance > query.max_distance_km:
        reasons.append("BEYOND_REQUESTED_DISTANCE")
    if query.max_distance_km is not None and distance is None:
        unknowns.append("SOURCE_DISTANCE_UNKNOWN")
    if query.max_elevation_delta_m is not None and elevation_delta is not None and (
        elevation_delta > query.max_elevation_delta_m
    ):
        reasons.append("BEYOND_REQUESTED_ELEVATION")
    if query.max_elevation_delta_m is not None and elevation_delta is None:
        unknowns.append("ELEVATION_DIFFERENCE_UNKNOWN")
    if site and (site.lat is None or site.lon is None or
                 site.position_status in ("approximate_locality", "conflicted")):
        unknowns.append("SITE_POSITION_UNVERIFIED")
    if product.provider == "cds" and abs(location.lat) >= 89:
        unknowns.append("POLAR_FOOTPRINT_CONFLICT")
    if product.id == "cds:era5_land" or product.id == "openmeteo:era5_land":
        unknowns.append("LAND_MASK_UNVERIFIED")
    if product.provider == "cmip6":
        unknowns.append("GRID_CELL_UNVERIFIED")
    if product.provider in ("nsrdb", "pvgis") and any(e.probe_location for e in entries):
        applicable = [e for e in entries if e.probe_location is None or (
            abs(e.probe_location.lat - location.lat) <= 1e-6 and
            abs(e.probe_location.lon - location.lon) <= 1e-6)]
        if not applicable:
            unknowns.append("TARGETED_PROBE_ONLY")
        entries = applicable
    if not entries:
        unknowns.append("TEMPORAL_EVIDENCE_MISSING")
    else:
        decisions = [_temporal(query, entry, product) for entry in entries]
        best = next((d for d in decisions if d[0] == "supported"),
                    next((d for d in decisions if d[0] == "unknown"), decisions[0]))
        if best[0] == "excluded":
            reasons.extend(best[1])
        else:
            reasons.extend(best[1])
            unknowns.extend(best[2])
    hard_fields = (query.required_variables if query.required_variables is not None else
                   query.request.required_variables if isinstance(query, WeatherAvailabilityQuery) and
                   query.request.missing_policy == "error" else [])
    missing = sorted(set(hard_fields) - set(product.adapter_variables))
    if missing:
        reasons.append("REQUIRED_VARIABLE_UNSUPPORTED")
    stale = bool(set(product.evidence_ids) & stale_sources or
                 any(set(e.evidence_ids) & stale_sources for e in entries))
    if stale:
        unknowns.append("STALE_SOURCE_EVIDENCE")
    access = "terms_required" if "accepted_terms" in product.access_requirements else (
        "credentials_required" if product.access_requirements else "unknown")
    stable_exclusions = (
        "METHOD_PRODUCT_MISMATCH", "TEMPORAL_KIND_MISMATCH", "BEYOND_PROVIDER_SEARCH_RADIUS",
        "BEYOND_REQUESTED_DISTANCE", "BEYOND_REQUESTED_ELEVATION", "REQUIRED_VARIABLE_UNSUPPORTED",
        "ADAPTER_PRODUCT_UNSUPPORTED",
        "SCENARIO_MISMATCH", "BEFORE_DOCUMENTED_START",
        "PUBLISHED_PRODUCT_MISMATCH")
    if any(code in reasons for code in stable_exclusions) or (
        "WINDOW_NOT_PUBLISHED" in reasons and not stale
    ):
        status = "excluded"
    elif unknowns:
        status = "unknown"
    else:
        status = "supported"
    evidence_ids = sorted(set(product.evidence_ids).union(
        *(set(e.evidence_ids) for e in entries)))
    bases = sorted(set(e.evidence_basis for e in entries))
    return EligibilityDecision(status=status, reasons=reasons, unknowns=unknowns,
                               evidence_ids=evidence_ids, evidence_bases=bases,
                               stale=stale, access=access), distance, elevation_delta


def evaluate(query: AvailabilityQuery, view: CatalogView) -> AvailabilityResult:
    """Assess catalog eligibility only; no I/O or weather-quality claim."""
    bundle = view.bundle
    all_sites: dict[str, list[SiteRecord]] = {}
    all_entries: dict[tuple[str, str | None], list[AvailabilityEntry]] = {}
    for source_site in bundle.sites:
        all_sites.setdefault(source_site.product_id, []).append(source_site)
    for entry in bundle.entries:
        all_entries.setdefault((entry.product_id, entry.site_id), []).append(entry)
    result = AvailabilityResult(checked_at=datetime.now(timezone.utc), snapshots=[view.snapshot])
    for occurrence, location in enumerate(_locations(query)):
        assessment = LocationAssessment(occurrence_index=occurrence,
                                        requested_location=location)
        result.locations.append(assessment)
        selected_published: set[str] | None = None
        if (isinstance(query, WeatherAvailabilityQuery) and not query.request.product_id):
            nearby = []
            for candidate_product in bundle.products:
                if candidate_product.provider != "onebuilding":
                    continue
                for candidate_site in all_sites.get(candidate_product.id, []):
                    distance = _distance(location, candidate_site)
                    if distance is not None and candidate_site.position_status not in (
                        "approximate_locality", "conflicted"):
                        nearby.append((distance, candidate_product.id))
            nearby.sort()
            selected_published = {product_id for _, product_id in nearby[:20]}
        for product in bundle.products:
            if not _relevant_product(query, product):
                continue
            if (product.provider == "onebuilding" and selected_published is not None and
                    product.id not in selected_published):
                continue
            for site in _candidate_sites(query, location, product,
                                         all_sites.get(product.id, []), all_entries):
                entries = all_entries.get((product.id, site.id if site else None), [])
                decision, distance, elevation_delta = _assess(
                    query, location, product, site, entries,
                    set(view.snapshot.stale_sources))
                hard_fields = (query.required_variables if query.required_variables is not None else
                               query.request.required_variables if isinstance(query, WeatherAvailabilityQuery)
                               and query.request.missing_policy == "error" else [])
                preferred = (_PURPOSE_FIELDS.get(query.purpose, []) if query.purpose else
                             query.request.required_variables if isinstance(query, WeatherAvailabilityQuery)
                             else [])
                option_id = f"{occurrence}:{digest([product.id, site.id if site else None])[:20]}"
                result.options.append(SuitabilityOption(
                    id=option_id, occurrence_index=occurrence, product=product, site=site,
                    eligibility=decision, distance_km=distance, elevation_delta_m=elevation_delta,
                    missing_required_variables=sorted(set(hard_fields) - set(product.adapter_variables)),
                    missing_preferred_variables=sorted(set(preferred) - set(product.adapter_variables)),
                    identity_status=("verified" if site and site.station_identity_status == "verified"
                                     else "provisional" if site else "unknown"),
                ))
        if not any(o.occurrence_index == occurrence for o in result.options):
            result.issues.append(Issue(code="CATALOG_NO_CANDIDATES",
                                       message="No catalog candidates match this request",
                                       location_id=location.key))
    return result
