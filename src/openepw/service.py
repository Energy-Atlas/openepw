from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from .artifacts.store import ArtifactStore, atomic_write
from .config import RuntimeConfig
from .epw.writer import epw_bytes
from .models import (
    ArtifactBundle,
    Candidate,
    DiscoveryResult,
    FetchTask,
    GeocodeResult,
    Issue,
    Location,
    OpenEPWError,
    OutputSpec,
    WeatherPlan,
    WeatherRequest,
    digest,
    utcnow,
)
from .providers.era5 import CDSProvider
from .providers.http import HttpClient
from .providers.noaa_isd import NOAAProvider
from .providers.nsrdb import NSRDBProvider
from .providers.onebuilding import OneBuildingProvider
from .providers.openmeteo import OpenMeteoProvider
from .providers.pvgis import PVGISProvider
from .qc import validate


class WeatherService:
    def preview_artifact(self, artifact_id, start=0, limit=168, variables=None):
        from .epw import read_epw
        from .preview import preview

        ref, path = self.artifacts.resolve(artifact_id)
        if ref.media_type != "application/vnd.energyplus.epw":
            raise OpenEPWError("INVALID_ARTIFACT", "Preview requires an EPW artifact")
        return preview(read_epw(path), start, limit, variables)

    def __init__(self, config: RuntimeConfig | None = None, *, http=None, providers=None):
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
        locations = self.locations(request)
        candidates: list[Candidate] = []
        issues = []
        for name in request.providers:
            if name not in self.providers:
                issues.append(
                    Issue(code="PROVIDER_UNAVAILABLE", message=f"Unknown provider: {name}")
                )
        for loc in locations:
            for name, p in self.providers.items():
                if request.providers and name not in request.providers:
                    continue
                try:
                    candidates.extend(p.discover(request, loc, self.http))
                except OpenEPWError as exc:
                    issues.append(exc.issue)
        selected = []
        for loc in locations:
            choices = [c for c in candidates if c.location_id == loc.key]
            choices.sort(
                key=lambda c: (
                    len(c.missing_fields),
                    request.providers.index(c.source.provider)
                    if c.source.provider in request.providers
                    else len(request.providers),
                    bool(c.requires_credentials),
                )
            )
            if choices:
                choices[0].selection_reasons = [
                    "Fewest missing requested fields; explicit provider order; ungated access as tie-break"
                ]
                selected.append(choices[0].id)
        return DiscoveryResult(
            locations=locations,
            candidates=candidates,
            selected_candidate_ids=selected,
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
        if len(locations) * max(1, len(request.years)) > 1000:
            raise OpenEPWError("RESOURCE_LIMIT", "Request exceeds 1000 output locations/periods")
        discovery = discovery or self.discover(request)
        if [p.key for p in discovery.locations] != [p.key for p in self.locations(request)]:
            raise OpenEPWError("PLAN_STALE", "Discovery locations differ from this request")
        tasks = {}
        outputs = []
        selected: list[Candidate] = []
        warnings = [i.message for i in discovery.issues]
        for loc in discovery.locations:
            candidates = [c for c in discovery.candidates if c.location_id == loc.key]
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
                    chosen.append(candidate)
            else:
                chosen = [c for c in candidates if c.id in discovery.selected_candidate_ids][:1]
            if not chosen:
                raise OpenEPWError(
                    "PROVIDER_UNAVAILABLE", "No candidate supports requested product/location"
                )
            selected.extend(c for c in chosen if c.id not in [v.id for v in selected])
            periods = [(f"{y}-01-01", f"{y}-12-31") for y in request.years] or [
                (str(request.start), str(request.end))
            ]
            for start, end in periods:
                ids = []
                for candidate in chosen:
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
                        "location": query_location,
                        "start": start,
                        "end": end,
                        "product": request.product,
                        "product_id": candidate.product_id or request.product_id,
                    }
                    key = digest(
                        {
                            "source": candidate.source.model_dump(mode="json"),
                            "parameters": params,
                            "version": "0.1",
                        }
                    )
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
                outputs.append(
                    OutputSpec(
                        requested_location_id=loc.key, task_ids=ids, name=digest(ids)[:20] + ".epw"
                    )
                )
        return WeatherPlan(
            request=request,
            selected_candidates=selected,
            tasks=list(tasks.values()),
            outputs=outputs,
            warnings=list(dict.fromkeys(warnings)),
            estimated_calls=len(tasks),
        )

    def execute(self, plan: WeatherPlan, *, cancelled=lambda: False, progress=lambda *_: None):
        plan = WeatherPlan.model_validate_json(plan.model_dump_json())
        if not plan.tasks or not plan.outputs:
            raise OpenEPWError("INVALID_REQUEST", "Cannot execute an empty plan")
        if plan.kind == "future":
            return self._execute_future(plan, cancelled=cancelled, progress=progress)
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
            Location.model_validate(task.parameters.get("location"))
        bundle_id = uuid.uuid4().hex
        weather, additional, issues, manifest_outputs, qc_records = [], [], [], [], []
        results = {}
        for task in plan.tasks:
            if cancelled():
                issues.append(
                    Issue(code="CANCELLED", message="Execution cancelled", severity="error")
                )
                break
            try:
                provider = self.providers.get(task.source.provider)
                if provider is None:
                    raise OpenEPWError("PLAN_STALE", "Planned provider is not registered")
                results[task.id] = self._cached_fetch(provider, task)
            except OpenEPWError as exc:
                issues.append(exc.issue.model_copy(update={"task_id": task.id}))
                progress(task.id, exc.issue)
        written = set()
        for output in plan.outputs:
            if output.name in written:
                continue
            written.add(output.name)
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
                    dataset = parts[0].dataset
                checks = validate(dataset)
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
                        "task_ids": output.task_ids,
                        "requested_locations": [
                            o.requested_location_id for o in plan.outputs if o.name == output.name
                        ],
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
                issues.extend(checks)
                progress(output.name, None)
            except OpenEPWError as exc:
                issues.append(exc.issue.model_copy(update={"task_id": output.name}))
                progress(output.name, exc.issue)
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
            "leap_policy": "preserve",
            "simulation_ready": False,
        }
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

        return plan_future(self, request)

    def _execute_future(self, plan, **kwargs):
        from .planning.future import execute_future

        return execute_future(self, plan, **kwargs)
