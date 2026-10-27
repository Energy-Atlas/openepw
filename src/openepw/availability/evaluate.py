"""Pure geographic, temporal and adapter eligibility decisions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone

from openepw.models import Issue, Location, digest
from openepw.planning.spatial import sample

from .catalog_index import CatalogIndex, distance_km
from .coverage import GridCoverage
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


_distance = distance_km


def _time_sensitive(query: AvailabilityQuery, product: ProductRecord,
                    entries: list[AvailabilityEntry]) -> bool:
    """Whether aged evidence can no longer vouch for this answer."""
    if isinstance(query, FutureAvailabilityQuery):
        return True
    if query.request.product not in ("historical", "amy"):
        return False                                   # published files stay published
    years = _requested_years(query)
    newest = max(years, default=0)
    for entry in entries:
        scope = entry.scope
        if not isinstance(scope, ActualScope):
            continue
        if scope.years and newest >= max(scope.years):
            return True
        if not scope.years and scope.operating_end is None and newest >= datetime.now(timezone.utc).year - 1:
            return True
        if not scope.years and scope.operating_end and newest >= scope.operating_end.year:
            return True                                # the newest months of a dated catalogue
    return False


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
                     lookup: CatalogIndex) -> Sequence[SiteRecord | None]:
    if not lookup.has_sites(product.id):
        return [None]
    if (isinstance(query, WeatherAvailabilityQuery) and product.provider == "noaa" and
            query.request.product_id):
        site = lookup.site(query.request.product_id)
        return [site] if site is not None and site.product_id == product.id else []
    if product.provider == "onebuilding" and isinstance(query, WeatherAvailabilityQuery):
        if query.request.product_id:
            return [lookup.first_site(product.id)]
    index = lookup.site_index(product.id)
    if product.provider == "noaa" and isinstance(query, WeatherAvailabilityQuery):
        requested = set(_requested_years(query))
        nearby = index.nearest(location, radius=100)
        listed = [(distance, site) for distance, site in nearby if any(
            isinstance(entry.scope, ActualScope) and requested <= set(entry.scope.years)
            for entry in lookup.entries(product.id, site.id))]
        supported_ids = {site.id for _, site in listed[:5]}
        uncertain = [site for _, site in nearby if site.id not in supported_ids][:3]
        chosen = [site for _, site in listed[:5]] + uncertain
        if chosen:
            return chosen
    known = index.nearest(location, count=5)
    if known:
        return [site for _, site in known]
    return [lookup.first_site(product.id)]


def _temporal(query: AvailabilityQuery, entry: AvailabilityEntry,
              product: ProductRecord) -> tuple[str, list[str], list[str]]:
    scope = entry.scope
    if isinstance(query, FutureAvailabilityQuery):
        if not isinstance(scope, FutureWindowScope):
            return "excluded", ["TEMPORAL_KIND_MISMATCH"], []
        if scope.scenario != query.scenario:
            return "excluded", ["SCENARIO_MISMATCH"], []
        if product.provider == "cmip6":
            if query.model and scope.model and scope.model != query.model:
                return "excluded", ["MODEL_MISMATCH"], []
            if query.member and scope.member and scope.member != query.member:
                return "excluded", ["MEMBER_MISMATCH"], []
            if query.model and not scope.model:
                return "unknown", [], ["MODEL_UNVERIFIED"]
            if query.member and not scope.member:
                return "unknown", [], ["MEMBER_UNVERIFIED"]
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
        if scope.operating_end and years and date(max(years), 12, 31) > scope.operating_end:
            return "unknown", [], ["AFTER_DATED_CATALOG_END"]       # includes a year the end cuts short
        if not scope.operating_end and max(years, default=0) >= datetime.now(timezone.utc).year:
            return "unknown", [], ["MOVING_END_UNVERIFIED"]
        if entry.site_id is None and (entry.evidence_basis == "documentation" or product.provider == "cds"):
            # A gridded product's documented period (owner decision 2026-10-13: Copernicus's
            # own catalogue record counts as documentation of ERA5's global period).
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
            stale_sources: set[str], coverage: GridCoverage | None = None,
            ) -> tuple[EligibilityDecision, float | None, float | None]:
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
        if query.profile == "sampled":
            reasons.append("PROFILE_UNSUPPORTED")
        if product.provider == "oedi":
            if query.model and query.model.lower() not in ("wrf", "ccsm4", "wrf/ccsm4"):
                reasons.append("MODEL_MISMATCH")
            if query.member:
                unknowns.append("MEMBER_UNVERIFIED")
            if query.reference_period == (1995, 2004):
                unknowns.append("REFERENCE_MEMBERSHIP_UNVERIFIED")
            elif query.reference_period is not None:
                reasons.append("REFERENCE_PERIOD_UNSUPPORTED")
        elif product.provider == "cmip6" and query.reference_period is not None:
            unknowns.append("REFERENCE_WINDOW_UNVERIFIED")
    elif (query.request.product in ("historical", "amy")) != (product.temporal_kind == "actual"):
        reasons.append("TEMPORAL_KIND_MISMATCH")
    if not product.adapter_supported:
        reasons.append("ADAPTER_PRODUCT_UNSUPPORTED")
    explicit_noaa = (isinstance(query, WeatherAvailabilityQuery) and product.provider == "noaa"
                     and site is not None and query.request.product_id == site.id)
    if product.provider == "noaa" and not explicit_noaa and distance is not None and distance > 100:
        reasons.append("BEYOND_PROVIDER_SEARCH_RADIUS")
    # A published station file describes its station, not a place far from it (owner decision
    # 2026-10-12: the same 100 km as NOAA ISD).
    if product.provider == "onebuilding" and distance is not None and distance > 100:
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
    if product.provider == "cmip6":
        unknowns.append("GRID_CELL_UNVERIFIED")
    # A reviewed coverage mask gates its product (coverage.py): outside is excluded, inside
    # stands in for the point evidence, next to the edge stays unknown.
    place = coverage.where(location.lat, location.lon) if coverage else None
    if product.dataset in ("reanalysis-era5-land", "era5_land") and place != "inside":
        unknowns.append("LAND_MASK_UNVERIFIED" if place is None else "NEAR_SOURCE_COVERAGE_EDGE")
    if place == "outside":
        reasons.append("OUTSIDE_SOURCE_COVERAGE")
    elif place == "inside" and not any(e.probe_location for e in entries):
        reasons.append("INSIDE_SOURCE_COVERAGE")
    elif product.provider in ("nsrdb", "pvgis") and any(e.probe_location for e in entries):
        at_point = [e for e in entries if e.probe_location is not None and (
            abs(e.probe_location.lat - location.lat) <= 1e-6 and
            abs(e.probe_location.lon - location.lon) <= 1e-6)]
        area = [e for e in entries if e.probe_location is None]
        if at_point:
            entries = at_point                               # the probe's own lists
        elif place == "inside":
            reasons.append("INSIDE_SOURCE_COVERAGE")
            # A documented area-wide entry (PVGIS) applies inside the mask; without one, the
            # probes' lists apply (NSRDB). A probe's selected months never move to another point.
            entries = area or entries
        else:
            unknowns.append("TARGETED_PROBE_ONLY")
            if place == "edge":
                unknowns.append("NEAR_SOURCE_COVERAGE_EDGE")
            entries = []
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
        # Owner decision 2026-10-12: a check that is due does not undo durable facts (a site's
        # position, a published-file list, a closed dated period); it does for facts that
        # change: the newest years, CDS's operational state and future-window directories.
        if unknowns or _time_sensitive(query, product, entries):
            unknowns.append("STALE_SOURCE_EVIDENCE")
        else:
            reasons.append("SOURCE_CHECK_DUE")
    access = "terms_required" if "accepted_terms" in product.access_requirements else (
        "credentials_required" if product.access_requirements else "unknown")
    stable_exclusions = (
        "METHOD_PRODUCT_MISMATCH", "TEMPORAL_KIND_MISMATCH", "BEYOND_PROVIDER_SEARCH_RADIUS",
        "BEYOND_REQUESTED_DISTANCE", "BEYOND_REQUESTED_ELEVATION", "REQUIRED_VARIABLE_UNSUPPORTED",
        "ADAPTER_PRODUCT_UNSUPPORTED",
        "SCENARIO_MISMATCH", "MODEL_MISMATCH", "MEMBER_MISMATCH",
        "PROFILE_UNSUPPORTED", "REFERENCE_PERIOD_UNSUPPORTED", "BEFORE_DOCUMENTED_START",
        "PUBLISHED_PRODUCT_MISMATCH", "OUTSIDE_SOURCE_COVERAGE")
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


def evaluate(query: AvailabilityQuery, view: CatalogView,
             coverage: dict[str, GridCoverage] | None = None) -> AvailabilityResult:
    """Assess catalog eligibility only; no I/O or weather-quality claim. ``coverage`` holds the
    installed coverage masks by gated product (``"provider:dataset"``)."""
    lookup = view.index
    result = AvailabilityResult(checked_at=datetime.now(timezone.utc), snapshots=[view.snapshot])
    for occurrence, location in enumerate(_locations(query)):
        assessment = LocationAssessment(occurrence_index=occurrence,
                                        requested_location=location)
        result.locations.append(assessment)
        selected_published: set[str] | None = None
        if (isinstance(query, WeatherAvailabilityQuery) and not query.request.product_id):
            # The 20 nearest published files, ordered by (distance, product id) as before.
            nearby = lookup.published.nearest(location, count=20, key=lambda site: site.product_id)
            selected_published = {site.product_id for _, site in nearby}
        for product in lookup.products_for(query, selected_published):
            if not _relevant_product(query, product):
                continue
            for site in _candidate_sites(query, location, product, lookup):
                entries = lookup.entries(product.id, site.id if site else None)
                decision, distance, elevation_delta = _assess(
                    query, location, product, site, entries,
                    set(view.snapshot.stale_sources),
                    (coverage or {}).get(f"{product.provider}:{product.dataset}"))
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
