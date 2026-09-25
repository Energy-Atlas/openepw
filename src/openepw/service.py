from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .artifacts.store import ArtifactStore, atomic_write
from .availability import (
    AvailabilityResult,
    CatalogSnapshotRef,
    FutureAvailabilityQuery,
    ProductRecord,
    SuitabilityOption,
    WeatherAvailabilityQuery,
)
from .availability.bootstrap import bundled_contracts
from .availability.evaluate import evaluate
from .availability.importers import normalize_source
from .availability.recommend import rank
from .availability.refresh import refresh_if_relevant
from .availability.store import CatalogStore, CatalogView
from .config import RuntimeConfig
from .dataset import without_feb_29
from .epw.writer import epw_bytes
from .models import (
    ArtifactBundle,
    BatchRow,
    Candidate,
    DatasetSelection,
    DiscoveryResult,
    FetchTask,
    GeocodeResult,
    Issue,
    Location,
    OpenEPWError,
    OutputSpec,
    SourceRef,
    WeatherPlan,
    WeatherRequest,
    digest,
    utcnow,
)
from .planning.batch import (
    exact_published_source,
    exact_published_url,
    fetch_task_key,
    finalize_batch_rows,
    missing_selection_status,
)
from .planning.output_identity import filename, location_label, output_id, period_label
from .planning.store import PlanStore
from .providers.base import ProviderResult
from .providers.era5 import CDSProvider
from .providers.http import HttpClient
from .providers.noaa_isd import NOAAProvider
from .providers.nsrdb import NSRDBProvider
from .providers.onebuilding import OneBuildingProvider
from .providers.openmeteo import OpenMeteoProvider
from .providers.pvgis import PVGISProvider
from .qc import validate


class _DiscoveryHttp:
    """Reuse identical metadata GETs inside one multi-point discovery call."""

    def __init__(self, underlying):
        self.underlying = underlying
        self.cache: dict[tuple[str, str, str], Any] = {}

    def get(self, url: str, **kwargs):
        key = ("get", url, repr(sorted(kwargs.items())))
        if key not in self.cache:
            self.cache[key] = self.underlying.get(url, **kwargs)
        return self.cache[key]

    def get_json(self, url: str, **kwargs):
        key = ("get_json", url, repr(sorted(kwargs.items())))
        if key not in self.cache:
            self.cache[key] = self.underlying.get_json(url, **kwargs)
        return copy.deepcopy(self.cache[key])

    def __getattr__(self, name: str):
        return getattr(self.underlying, name)


def _candidate_for_occurrence(
    candidate: Candidate, occurrence_index: int, used_ids: set[str],
) -> Candidate:
    """Keep a provider's identity while giving colliding query rows distinct IDs."""
    if candidate.id not in used_ids:
        used_ids.add(candidate.id)
        return candidate.model_copy(deep=True)
    suffix = f":occurrence:{occurrence_index}"
    unique_id = candidate.id + suffix
    counter = 1
    while unique_id in used_ids:
        unique_id = candidate.id + suffix + f":{counter}"
        counter += 1
    used_ids.add(unique_id)
    return candidate.model_copy(update={"id": unique_id}, deep=True)


class WeatherService:
    def __init__(self, config: RuntimeConfig | None = None, *, http=None, providers=None,
                 catalog_store: CatalogStore | None = None):
        self.config = config or RuntimeConfig.load()
        self.http = http or HttpClient(self.config)
        self.providers: dict[str, Any] = {
            p.name: p
            for p in (
                providers
                if providers is not None
                else list[Any](
                    [
                        OpenMeteoProvider(),
                        PVGISProvider(),
                        OneBuildingProvider(),
                        NOAAProvider(),
                        NSRDBProvider(),
                        CDSProvider(),
                    ]
                )
            )
        }
        self.artifacts = ArtifactStore(self.config.data_root)
        self.catalog_store = catalog_store or CatalogStore(self.config.data_root / "catalog")
        self.plan_store = PlanStore(self.config.data_root)

    def assess_availability(self, query: WeatherAvailabilityQuery | FutureAvailabilityQuery) -> AvailabilityResult:
        view = self.catalog_store.active()
        if view is None:
            bundle = bundled_contracts()
            provider_names = (["cmip6" if query.method == "morph" else "oedi"]
                              if isinstance(query, FutureAvailabilityQuery) else
                              query.request.providers or list(self.providers))
            known = {product.provider for product in bundle.products}
            for provider in provider_names:
                if provider in known:
                    continue
                bundle.products.append(ProductRecord(
                    id=f"unloaded:{provider}", provider=provider, dataset="unloaded",
                    temporal_kind=("future_window" if isinstance(query, FutureAvailabilityQuery)
                                   else "tmy_reference" if query.request.product in
                                   ("tmy", "tmyx", "published") else "actual")))
            snapshot = CatalogSnapshotRef(generation_id="bundled-contracts-v1",
                                          created_at=datetime(2026, 9, 24, tzinfo=timezone.utc))
            result = rank(evaluate(query, CatalogView(snapshot, bundle)), query)
            result.snapshots = []
            result.issues.insert(0, Issue(code="CATALOG_UNAVAILABLE",
                                          message="Local inventories are not loaded; bundled contracts only"))
            return self._compact_availability(result)
        result = rank(evaluate(query, view), query)
        if query.refresh == "if_needed":
            relevant = {evidence_id for option in result.options
                        if option.eligibility.status == "unknown"
                        for evidence_id in option.eligibility.evidence_ids}
            issues = refresh_if_relevant(query, self.catalog_store, self.http,
                                         relevant, normalize_source)
            if relevant:
                refreshed = self.catalog_store.active()
                if refreshed is not None:
                    result = rank(evaluate(query, refreshed), query)
            result.issues.extend(issues)
        return self._compact_availability(result)

    @staticmethod
    def _compact_availability(result: AvailabilityResult) -> AvailabilityResult:
        """Bound ordinary API/tool output while retaining ranked alternatives."""
        option_limit = 50
        kept = set()
        truncated = 0
        for assessment in result.locations:
            truncated += max(0, len(assessment.ranked_option_ids) - option_limit)
            assessment.ranked_option_ids = assessment.ranked_option_ids[:option_limit]
            assessment.recommended_option_ids = [
                option_id for option_id in assessment.recommended_option_ids
                if option_id in assessment.ranked_option_ids]
            kept.update(assessment.ranked_option_ids)
        if truncated:
            result.options = [option for option in result.options if option.id in kept]
            result.issues.append(Issue(
                code="OPTIONS_TRUNCATED", severity="info",
                message=f"{truncated} lower-ranked options omitted; narrow the query for detail"))
        return result

    def geocode(self, query, *, mode="point"):
        if mode != "point":
            raise OpenEPWError("UNSUPPORTED_GEOGRAPHY", "Only named point geocoding is supported")
        raw = self.http.get_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 10, "language": "en", "format": "json"},
        )
        candidates = [
            Location(
                id=str(r["id"]),
                lat=r["latitude"],
                lon=r["longitude"],
                elevation=r.get("elevation"),
                name=", ".join(str(r[k]) for k in ("name", "admin1", "country") if r.get(k)),
            )
            for r in raw.get("results", [])
        ]
        return GeocodeResult(
            query=query,
            candidates=candidates,
            issues=[
                Issue(
                    code="AMBIGUOUS_LOCATION",
                    message="Multiple candidates; choose an explicit location",
                )
            ]
            if len(candidates) > 1
            else [],
        )

    def locations(self, request):
        if isinstance(request.locations, Location):
            return [request.locations]
        if isinstance(request.locations, list):
            return request.locations
        from .planning.spatial import sample

        return sample(request.locations, request.sampling)

    def discover(self, request: WeatherRequest):
        if self.catalog_store.active() is None:
            return self._discover_live(request)
        availability = self.assess_availability(WeatherAvailabilityQuery(request=request))
        locations = self.locations(request)
        candidates: dict[str, Candidate] = {}
        candidate_bases: dict[str, str] = {}
        option_candidates: dict[str, str] = {}
        extra_by_occurrence: dict[int, list[str]] = {}
        live_resolved: set[str] = set()
        issues = list(availability.issues)
        live_cache: dict[tuple[str, float, float, int, str | None], list[Candidate]] = {}
        live_http = _DiscoveryHttp(self.http)
        for option in sorted(availability.options, key=lambda item: (
            item.occurrence_index, item.rank or 9999)):
            if option.eligibility.status == "excluded":
                continue
            location = locations[option.occurrence_index]
            candidate = (self._catalog_candidate(option, location, request)
                         if option.eligibility.status == "supported" else None)
            if candidate is not None:
                unique = _candidate_for_occurrence(candidate, option.occurrence_index,
                                                   set(candidates))
                candidates[unique.id] = unique
                candidate_bases[unique.id] = candidate.id
                option_candidates[option.id] = unique.id
                continue
            provider = self.providers.get(option.product.provider)
            if provider is None:
                continue
            key = (option.product.provider, location.lat, location.lon,
                   location.standard_offset_minutes, option.product.dataset)
            if key not in live_cache:
                try:
                    provider_request = request.model_copy(update={"dataset": option.product.dataset})
                    live_cache[key] = provider.discover(provider_request, location, live_http)
                except OpenEPWError as exc:
                    issues.append(exc.issue)
                    live_cache[key] = []
            found_ids = []
            for found in live_cache[key]:
                unique = _candidate_for_occurrence(found, option.occurrence_index,
                                                   set(candidates))
                candidates[unique.id] = unique
                candidate_bases[unique.id] = found.id
                found_ids.append(unique.id)
            if found_ids:
                option_candidates[option.id] = found_ids[0]
                extra_by_occurrence.setdefault(option.occurrence_index, []).extend(found_ids[1:])
                live_resolved.add(option.id)
        ranked: dict[str, list[str]] = {}
        by_occurrence: list[list[str]] = []
        selected: list[str] = []
        selected_bases: set[str] = set()
        for assessment in availability.locations:
            location_key = assessment.requested_location.key
            occurrence_ids = list(dict.fromkeys(
                [option_candidates[option_id] for option_id in assessment.ranked_option_ids
                 if option_id in option_candidates] +
                extra_by_occurrence.get(assessment.occurrence_index, [])
            ))
            by_occurrence.append(occurrence_ids)
            ranked[location_key] = occurrence_ids
            preferred = list(assessment.recommended_option_ids)
            if not preferred:
                preferred = [option_id for option_id in assessment.ranked_option_ids
                             if option_id in live_resolved][:1]
            for option_id in preferred:
                candidate_id = option_candidates.get(option_id)
                if candidate_id and candidate_bases[candidate_id] not in selected_bases:
                    if option_id in live_resolved:
                        candidates[candidate_id].selection_reasons.append(
                            "Live provider discovery provided a retrieval candidate; "
                            "catalog uncertainty remains")
                    selected.append(candidate_id)
                    selected_bases.add(candidate_bases[candidate_id])
        return DiscoveryResult(locations=locations, candidates=list(candidates.values()),
                               selected_candidate_ids=selected,
                               ranked_candidate_ids=ranked,
                               candidate_ids_by_occurrence=by_occurrence, issues=issues,
                               availability=availability)

    def _catalog_candidate(self, option: SuitabilityOption, location: Location,
                           request: WeatherRequest) -> Candidate | None:
        product = option.product
        site = option.site
        if product.provider == "noaa" and site and site.lat is not None and site.lon is not None:
            station = site.id
            source = SourceRef(
                provider="noaa", dataset="ISD global-hourly", identity=station,
                location=Location(lat=site.lat, lon=site.lon, elevation=site.elevation_m,
                                  standard_offset_minutes=location.standard_offset_minutes),
                provisional=False, license="US government public data",
                citation="https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database",
            )
            return Candidate(
                id=f"noaa:{station}:{location.key}", location_id=location.key,
                product_id=station, source=source, weather_types=["historical", "amy"],
                variables=product.adapter_variables,
                missing_fields=[v for v in request.required_variables if v not in
                                product.adapter_variables],
                warnings=["Catalog listing does not establish hourly completeness or variable coverage"],
            )
        if product.provider == "onebuilding" and product.native_product_id:
            parsed = urlparse(product.native_product_id)
            if parsed.scheme != "https" or parsed.netloc != "climate.onebuilding.org" or (
                not parsed.path.endswith(".zip") or ".." in parsed.path.split("/")):
                return None
            return Candidate(
                id=f"onebuilding:{hashlib.sha256(product.native_product_id.encode()).hexdigest()[:16]}:{location.key}",
                location_id=location.key, product_id=parsed.path.lstrip("/"),
                source=SourceRef(provider="onebuilding", dataset="OneBuilding published EPW",
                                 identity=parsed.path, citation=product.native_product_id,
                                 license="Redistribution permission unverified; local retrieval only"),
                weather_types=["tmy", "tmyx", "published"],
                variables=product.adapter_variables,
                warnings=["Published product coordinates remain provisional until EPW header verification"],
            )
        if product.provider == "nsrdb" and option.eligibility.status == "supported":
            published = product.temporal_kind == "tmy_reference"
            product_id = request.product_id if published else None
            if published and not product_id:
                view = self.catalog_store.active()
                labels = [entry.scope.product_label for entry in view.bundle.entries
                          if entry.product_id == product.id and entry.probe_location and
                          abs(entry.probe_location.lat - location.lat) < 1e-6 and
                          abs(entry.probe_location.lon - location.lon) < 1e-6 and
                          hasattr(entry.scope, "product_label")] if view else []
                product_id = max((label for label in labels if label.startswith("tmy-")), default=None)
            if published and not product_id:
                return None
            return Candidate(
                id=f"nsrdb:{product.dataset}:{product_id or 'actual'}:{location.key}",
                product_id=product_id, location_id=location.key,
                source=SourceRef(provider="nsrdb", dataset=product.dataset,
                                 resolution_km=4, citation="https://nsrdb.nlr.gov",
                                 license="NLR NSRDB data terms; attribute NSRDB"),
                weather_types=["tmy", "published"] if published else ["historical", "amy"],
                variables=product.adapter_variables, interval_minutes=60,
                requires_credentials=product.access_requirements,
            )
        return None

    def _discover_live(self, request: WeatherRequest):
        locations = self.locations(request)
        candidates: list[Candidate] = []
        by_occurrence: list[list[str]] = []
        issues = []
        if not request.dataset_selections:
            for name in request.providers:
                if name not in self.providers:
                    issues.append(
                        Issue(code="PROVIDER_UNAVAILABLE", message=f"Unknown provider: {name}")
                    )
        selected = []
        selected_bases: set[str] = set()
        ranked: dict[str, list[str]] = {}
        used_ids: set[str] = set()
        for occurrence_index, loc in enumerate(locations):
            choices: list[Candidate] = []
            queries = (
                [
                    (
                        selection.provider,
                        request.model_copy(
                            update={
                                "dataset": selection.dataset,
                                "product_id": selection.product_id or request.product_id,
                            }
                        ),
                    )
                    for selection in request.dataset_selections
                ]
                if request.dataset_selections
                else [
                    (name, request)
                    for name in self.providers
                    if not request.providers or name in request.providers
                ]
            )
            for name, query in queries:
                p = self.providers.get(name)
                if p is None:
                    continue
                try:
                    for found in p.discover(query, loc, self.http):
                        unique = _candidate_for_occurrence(found, occurrence_index, used_ids)
                        candidates.append(unique)
                        choices.append(unique)
                except OpenEPWError as exc:
                    issues.append(exc.issue)
            choices.sort(
                key=lambda c: (
                    len(c.missing_fields),
                    request.providers.index(c.source.provider)
                    if c.source.provider in request.providers
                    else len(request.providers),
                    bool(c.requires_credentials),
                )
            )
            ranked[loc.key] = [c.id for c in choices]
            by_occurrence.append([c.id for c in choices])
            if choices:
                choices[0].selection_reasons = [
                    "Fewest missing requested fields; explicit provider order; ungated access as tie-break"
                ]
                base_id = choices[0].id.split(":occurrence:", 1)[0]
                if base_id not in selected_bases:
                    selected.append(choices[0].id)
                    selected_bases.add(base_id)
        return DiscoveryResult(
            locations=locations,
            candidates=candidates,
            selected_candidate_ids=selected,
            ranked_candidate_ids=ranked,
            candidate_ids_by_occurrence=by_occurrence,
            issues=issues,
        )

    def plan(self, request: WeatherRequest, *, discovery=None):
        locations = self.locations(request)
        if request.product in ("historical", "amy") and any(
            loc.standard_offset_minutes % 60 for loc in locations
        ):
            raise OpenEPWError(
                "UNSUPPORTED_TIMEZONE",
                "Fractional-hour output requires explicit temporal interpolation; request UTC or a whole-hour fixed offset in v0.1",
            )
        output_multiplier = max(1, len(request.years)) * max(1, len(request.dataset_selections))
        if len(locations) * output_multiplier > 1000:
            raise OpenEPWError("RESOURCE_LIMIT", "Request exceeds 1000 output locations/periods")
        discovery = discovery or self.discover(request)
        if [p.key for p in discovery.locations] != [p.key for p in self.locations(request)]:
            raise OpenEPWError("PLAN_STALE", "Discovery locations differ from this request")
        tasks = {}
        outputs = []
        batch_rows: list[BatchRow] = []
        selected: list[Candidate] = []
        warnings = [i.message for i in discovery.issues]
        issues = list(discovery.issues)
        for occurrence, loc in enumerate(discovery.locations):
            candidate_ids = (discovery.candidate_ids_by_occurrence[occurrence]
                             if len(discovery.candidate_ids_by_occurrence) == len(discovery.locations)
                             else [c.id for c in discovery.candidates if c.location_id == loc.key])
            candidates_by_id = {c.id: c for c in discovery.candidates}
            candidates = [candidates_by_id[cid] for cid in candidate_ids
                          if cid in candidates_by_id]
            periods = [(f"{y}-01-01", f"{y}-12-31") for y in request.years] or [
                (str(request.start), str(request.end))
            ]
            missing: list[DatasetSelection | None] = []
            chosen: list[tuple[Candidate, DatasetSelection | None]]
            if request.hybrid_policy.enabled:
                if request.product not in ("historical", "amy"):
                    raise OpenEPWError("INVALID_ALIGNMENT", "Hybrids require actual dated series")
                chosen = []
                for provider in dict.fromkeys(request.hybrid_policy.assignments.values()):
                    candidate = next((c for c in candidates if c.source.provider == provider), None)
                    if candidate is None:
                        raise OpenEPWError(
                            "PROVIDER_UNAVAILABLE", "Assigned hybrid provider is unavailable"
                        )
                    chosen.append((candidate, None))
            elif request.dataset_selections:
                chosen = []
                ranking = candidate_ids
                ordered = sorted(
                    candidates,
                    key=lambda candidate: (
                        ranking.index(candidate.id) if candidate.id in ranking else len(ranking)
                    ),
                )
                for selection in request.dataset_selections:
                    candidate = next(
                        (
                            c
                            for c in ordered
                            if c.source.provider == selection.provider
                            and c.source.dataset == selection.dataset
                            and (
                                selection.product_id is None or c.product_id == selection.product_id
                            )
                        ),
                        None,
                    )
                    if candidate is None:
                        missing.append(selection)
                        issues.append(
                            Issue(
                                code="DATASET_UNAVAILABLE",
                                message=f"{selection.provider}/{selection.dataset} has no executable candidate for this location",
                                severity="warning",
                                field="dataset_selections",
                                location_id=loc.key,
                                occurrence_index=occurrence,
                                dataset_selection=selection.model_dump(mode="json"),
                            )
                        )
                        continue
                    chosen.append((candidate, selection))
            else:
                chosen = []
                if candidates:
                    chosen = [(candidates[0], None)]
            if not chosen:
                if not request.dataset_selections:
                    missing.append(None)
            for missing_selection in missing:
                status = missing_selection_status(discovery.availability, occurrence,
                                                  missing_selection)
                chosen_selection = missing_selection or DatasetSelection(
                    provider="unresolved", dataset=request.dataset or request.product,
                    product_id=request.product_id)
                code = "DATASET_UNAVAILABLE" if missing_selection else "PROVIDER_UNAVAILABLE"
                if missing_selection is None:
                    issues.append(Issue(code=code, message="No executable candidate for this location",
                                        location_id=loc.key, occurrence_index=occurrence))
                for start, end in periods:
                    batch_rows.append(BatchRow(
                        occurrence_index=occurrence, requested_location_id=loc.key,
                        dataset_selection=chosen_selection,
                        period_start=date.fromisoformat(start) if request.years or request.start else None,
                        period_end=date.fromisoformat(end) if request.years or request.end else None,
                        status=status, issue_codes=[code],
                    ))
            if not chosen:
                continue
            selected.extend(c for c, _ in chosen if c.id not in [v.id for v in selected])
            for start, end in periods:
                ids = []
                for candidate, _selection in chosen:
                    warnings.extend(candidate.warnings)
                    if (
                        candidate.source.resolution_km
                        and min(request.sampling.dx_km, request.sampling.dy_km)
                        < candidate.source.resolution_km
                    ):
                        warnings.append(
                            "Requested spacing is below native source resolution; density does not improve weather resolution"
                        )
                    query_location = loc.model_dump(mode="json", exclude={"id", "name"})
                    if (
                        candidate.source.identity
                        and not candidate.source.provisional
                        and candidate.source.location
                    ):
                        query_location.update(
                            lat=candidate.source.location.lat, lon=candidate.source.location.lon
                        )
                    params = {
                        "start": start,
                        "end": end,
                        "product": request.product,
                        "product_id": candidate.product_id or request.product_id,
                    }
                    if not exact_published_url(candidate):
                        params["location"] = query_location
                    key = fetch_task_key(candidate.source, params)
                    task_id = key[:20]
                    if key not in tasks:
                        tasks[key] = FetchTask(
                            id=task_id,
                            source=candidate.source,
                            parameters=params,
                            cache_key=key,
                            dependents=[loc.key],
                        )
                    elif loc.key not in tasks[key].dependents:
                        tasks[key].dependents.append(loc.key)
                    ids.append(task_id)
                groups: list[tuple[list[str], list[Candidate], DatasetSelection | None]] = (
                    [
                        ([task_id], [pair[0]], pair[1])
                        for task_id, pair in zip(ids, chosen, strict=True)
                    ]
                    if request.dataset_selections
                    else [(ids, [pair[0] for pair in chosen], None)]
                )
                for output_task_ids, output_candidates, output_selection in groups:
                    identity = output_id(
                        {
                            "kind": "weather",
                            "location_id": loc.key,
                            "occurrence": occurrence,
                            "task_ids": output_task_ids,
                            "sources": [
                                {
                                    "provider": c.source.provider,
                                    "dataset": c.source.dataset,
                                    "product_id": c.product_id or request.product_id,
                                }
                                for c in output_candidates
                            ],
                            "selection": output_selection.model_dump(mode="json")
                            if output_selection
                            else None,
                            "product": request.product,
                            "period": [start, end],
                            "skip_feb_29": request.skip_feb_29,
                            "hybrid_assignments": request.hybrid_policy.assignments,
                            "missing_policy": request.missing_policy,
                        }
                    )
                    first = output_candidates[0]
                    output_spec = OutputSpec(
                            id=identity,
                            occurrence_index=occurrence,
                            requested_location_id=loc.key,
                            task_ids=output_task_ids,
                            dataset_selection=output_selection,
                            name=filename(
                                [
                                    location_label(loc),
                                    first.source.provider,
                                    first.source.dataset,
                                    first.product_id or first.source.identity or request.product_id,
                                    period_label(start, end, request.product, request.product_id),
                                ],
                                identity,
                            ),
                        )
                    outputs.append(output_spec)
                    row_selection = output_selection or DatasetSelection(
                        provider="hybrid" if request.hybrid_policy.enabled else first.source.provider,
                        dataset="explicit" if request.hybrid_policy.enabled else first.source.dataset,
                        product_id=first.product_id or request.product_id,
                    )
                    batch_rows.append(BatchRow(
                        occurrence_index=occurrence, requested_location_id=loc.key,
                        dataset_selection=row_selection,
                        period_start=date.fromisoformat(start) if request.years or request.start else None,
                        period_end=date.fromisoformat(end) if request.years or request.end else None,
                        status="planned", candidate_id=first.id,
                        task_ids=output_task_ids, output_id=identity,
                    ))
        plan = WeatherPlan(
            request=request,
            selected_candidates=selected,
            tasks=list(tasks.values()),
            outputs=outputs,
            batch_rows=batch_rows,
            warnings=list(dict.fromkeys(warnings)),
            issues=issues,
            estimated_calls=len(tasks),
        )
        self.plan_store.put(plan)
        return plan

    def execute(self, plan: WeatherPlan, *, cancelled=lambda: False, progress=lambda *_: None,
                task_results: dict[str, ProviderResult] | None = None,
                cacheable_task_ids: set[str] | None = None,
                future_results: dict[str, Any] | None = None):
        plan = WeatherPlan.model_validate_json(plan.model_dump_json())
        if not plan.tasks or not plan.outputs:
            raise OpenEPWError("NO_EXECUTABLE_OUTPUTS", "Cannot execute a plan without outputs")
        if plan.kind == "future":
            return self._execute_future(plan, cancelled=cancelled, progress=progress,
                                        source_results=future_results)
        for task in plan.tasks:
            expected = digest(
                {
                    "source": task.source.model_dump(mode="json"),
                    "parameters": task.parameters,
                    "version": "0.1",
                }
            )
            if task.cache_key != expected or task.id != expected[:20]:
                raise OpenEPWError(
                    "PLAN_STALE", "Task identifiers do not match its scientific request"
                )
            if "location" in task.parameters:
                Location.model_validate(task.parameters["location"])
            elif not exact_published_source(task.source, task.parameters.get("product_id")):
                raise OpenEPWError("PLAN_STALE", "Task lacks a validated source location")
        bundle_id = uuid.uuid4().hex
        weather, additional, issues, manifest_outputs, qc_records = (
            [],
            [],
            list(plan.issues),
            [],
            [],
        )
        results = {}
        for task in plan.tasks:
            if cancelled():
                issues.append(
                    Issue(code="CANCELLED", message="Execution cancelled", severity="error")
                )
                break
            try:
                if (task_results is not None and not task.source.provisional and
                        task.id in task_results):
                    results[task.id] = task_results[task.id]
                else:
                    provider = self.providers.get(task.source.provider)
                    if provider is None:
                        raise OpenEPWError("PLAN_STALE", "Planned provider is not registered")
                    results[task.id] = self._cached_fetch(provider, task)
                    if (task_results is not None and not task.source.provisional and
                            (cacheable_task_ids is None or task.id in cacheable_task_ids)):
                        task_results[task.id] = results[task.id]
            except OpenEPWError as exc:
                issues.append(exc.issue.model_copy(update={"task_id": task.id}))
                progress(task.id, exc.issue)
        written = set()
        for output in plan.outputs:
            output_key = output.id or output.name
            if output_key in written:
                continue
            written.add(output_key)
            if not all(t in results for t in output.task_ids):
                continue
            try:
                parts = [results[t] for t in output.task_ids]
                if plan.request.hybrid_policy.enabled:
                    from .planning.hybrid import combine

                    dataset = combine(
                        {p.source.provider: p.dataset for p in parts},
                        plan.request.hybrid_policy.assignments,
                    )
                else:
                    dataset = copy.deepcopy(parts[0].dataset)
                if plan.request.skip_feb_29:
                    source_checks = validate(dataset, "annual")
                    if any(i.severity == "error" for i in source_checks):
                        raise OpenEPWError(
                            "EPW_CONVERSION_FAILED",
                            "Source structural annual QC failed before leap-day omission",
                        )
                    dataset = without_feb_29(dataset)
                checks = validate(dataset, "annual" if plan.request.skip_feb_29 else "standard")
                if plan.request.missing_policy == "error" and any(
                    v not in dataset.data or dataset.data[v].isna().any()
                    for v in plan.request.required_variables
                ):
                    raise OpenEPWError(
                        "MISSING_CRITICAL_VARIABLE", "Required weather values are missing"
                    )
                if any(i.severity == "error" for i in checks):
                    raise OpenEPWError(
                        "EPW_CONVERSION_FAILED", "Structural QC failed; no EPW emitted"
                    )
                ref = self.artifacts.write(
                    bundle_id,
                    output.name,
                    epw_bytes(dataset),
                    "weather",
                    "application/vnd.energyplus.epw",
                )
                weather.append(ref)
                for task_id, part in zip(output.task_ids, parts):
                    if part.native_epw:
                        additional.append(
                            self.artifacts.write(
                                bundle_id,
                                task_id + "-native.epw",
                                part.native_epw,
                                "native_weather",
                                "application/vnd.energyplus.epw",
                            )
                        )
                manifest_outputs.append(
                    {
                        "artifact_id": ref.id,
                        "output_id": output.id,
                        "task_ids": output.task_ids,
                        "requested_locations": [output.requested_location_id],
                        "source": parts[0].source.model_dump(mode="json"),
                        "lineage": {
                            k: v.model_dump(mode="json") for k, v in dataset.lineage.items()
                        },
                        "metadata": dataset.metadata,
                        "raw_sha256": [hashlib.sha256(p.raw).hexdigest() for p in parts],
                    }
                )
                qc_records.append(
                    {"artifact_id": ref.id, "issues": [i.model_dump() for i in checks]}
                )
                issues.extend(check.model_copy(update={"task_id": output_key}) for check in checks)
                progress(output_key, None)
            except OpenEPWError as exc:
                issues.append(exc.issue.model_copy(update={"task_id": output_key}))
                progress(output_key, exc.issue)
        return self._bundle(
            plan, bundle_id, weather, additional, issues, manifest_outputs, qc_records
        )

    def _bundle(self, plan, bundle_id, weather, additional, issues, manifest_outputs, qc_records):
        request_ref = self.artifacts.json(
            bundle_id, "request.json", plan.request.model_dump(mode="json"), "request"
        )
        plan_ref = self.artifacts.json(bundle_id, "plan.json", plan.model_dump(mode="json"), "plan")
        qc_ref = self.artifacts.json(bundle_id, "qc.json", qc_records, "qc")
        manifest = {
            "schema_version": "0.1",
            "package_version": "0.1.0",
            "created_at": utcnow(),
            "plan_hash": plan.plan_hash,
            "request_hash": digest(plan.request.model_dump(mode="json")),
            "outputs": manifest_outputs,
            "output_mapping": [o.model_dump() for o in plan.outputs],
            "warnings": plan.warnings,
            "issues": [i.model_dump() for i in issues],
            "timezone_policy": "fixed local standard time; default UTC when not supplied",
            "leap_policy": (
                plan.request.leap_policy if isinstance(plan.request, WeatherRequest) else "preserve"
            ),
            "simulation_ready": False,
        }
        if plan.kind == "weather" and plan.batch_rows:
            manifest["batch_rows"] = finalize_batch_rows(
                plan, manifest_outputs, issues,
                cancelled=any(issue.code == "CANCELLED" for issue in issues),
            )
            for row in manifest["batch_rows"]:
                if row["status"] == "succeeded":
                    row["qc_artifact_id"] = qc_ref.id
            uses = Counter(task_id for row in plan.batch_rows
                           if row.status == "planned" for task_id in row.task_ids)
            manifest["counts"] = {
                "requested_occurrences": len({row.occurrence_index for row in plan.batch_rows}),
                "output_intents": len(plan.outputs),
                "native_tasks": len(plan.tasks),
                "shared_native_tasks": sum(count > 1 for count in uses.values()),
                "unsupported": sum(row["status"] == "unsupported"
                                   for row in manifest["batch_rows"]),
                "unresolved": sum(row["status"] == "unresolved"
                                  for row in manifest["batch_rows"]),
                "emitted_artifacts": len(manifest_outputs),
            }
        if plan.kind == "future":
            produced = {entry.get("output_id"): entry for entry in manifest_outputs}
            cancelled = any(issue.code == "CANCELLED" for issue in issues)
            manifest["future_rows"] = []
            for output in plan.outputs:
                identity = output.id or output.name
                entry = produced.get(identity)
                related = [issue.code for issue in issues if issue.task_id == identity]
                row = {
                    "output_id": output.id,
                    "index": output.index,
                    "method": plan.request.method,
                    "scenario": plan.request.climate_scenario,
                    "reference_period": plan.request.reference_period,
                    "climate_period": plan.request.climate_period,
                    "baseline_artifact_id": plan.request.baseline,
                    "status": "succeeded" if entry else
                              ("cancelled" if cancelled and not related else "failed"),
                    "issue_codes": list(dict.fromkeys(related)),
                }
                if entry:
                    row["artifact_id"] = entry["artifact_id"]
                    row["qc_artifact_id"] = qc_ref.id
                manifest["future_rows"].append(row)
        manifest_ref = self.artifacts.json(bundle_id, "manifest.json", manifest, "manifest")
        return ArtifactBundle(
            bundle_id=bundle_id,
            weather=weather,
            request=request_ref,
            plan=plan_ref,
            manifest=manifest_ref,
            qc=qc_ref,
            additional=additional,
            issues=issues,
        )

    def _cached_fetch(self, provider, task):
        # Replay exact HTTP bytes using a private cache recording, never request URLs/keys.
        root = Path(self.config.data_root) / "cache" / "raw-v2" / task.cache_key
        records: list[int] = []
        pending = []
        http = self.http

        class Replay:
            config = http.config

            def get(inner, url, **kwargs):
                n = len(records)
                path = root / f"{n}.bin"
                checksum = root / f"{n}.sha256"
                if (
                    path.is_file()
                    and checksum.is_file()
                    and hashlib.sha256(path.read_bytes()).hexdigest() == checksum.read_text()
                ):
                    body = path.read_bytes()
                else:
                    body = http.get(url, **kwargs)
                    secrets = [
                        v.get_secret_value().encode()
                        for v in (
                            http.config.nlr_api_key,
                            http.config.nlr_email,
                            http.config.cds_key,
                            http.config.openmeteo_api_key,
                            http.config.bearer_token,
                        )
                        if v
                    ]
                    if not any(secret in body for secret in secrets):
                        pending.append((path, body, checksum))
                records.append(n)
                return body

            def get_json(inner, url, **kwargs):
                if task.source.provider == "cds":
                    return http.get_json(url, **kwargs)
                return json.loads(inner.get(url, **kwargs))

            def request(inner, *args, **kwargs):
                return http.request(*args, **kwargs)

        result = provider.fetch(task, Replay())
        for path, body, checksum in pending:
            atomic_write(path, body)
            atomic_write(checksum, hashlib.sha256(body).hexdigest().encode())
        return result

    def fetch(self, request):
        return self.execute(self.plan(request))

    def plan_future(self, request):
        from .planning.future import plan_future

        plan = plan_future(self, request)
        self.plan_store.put(plan)
        return plan

    def register_baseline(self, value):
        """Register a trusted local EPW path or bounded upload bytes."""
        if isinstance(value, (str, Path)):
            path = Path(value)
            if not path.is_file() or path.stat().st_size > 5_000_000:
                raise OpenEPWError("INVALID_BASELINE", "Baseline file exceeds local size limit")
            body = path.read_bytes()
        else:
            body = value
        return self.artifacts.register_baseline_bytes(
            body, "allowlisted_path" if isinstance(value, (str, Path)) else "upload")

    def _execute_future(self, plan, **kwargs):
        from .planning.future import execute_future

        return execute_future(self, plan, **kwargs)
