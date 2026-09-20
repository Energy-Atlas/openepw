# OpenEPW architecture proposal

Stage 1 design, 2026-09-20. Approval pending. The [human brief](docs/20260920-openepw-brief.md)
defines intent; [Stage 2 tasks](docs/plans/2026-09-20-stage-2.md) define delivery.

## Boundaries and package layout

Python 3.11+, `src` layout, Hatchling build. pandas/numpy for ordinary weather,
Pydantic v2 for serializable schemas, httpx for provider HTTP. Own EPW codec.
Optional extras: `api` (FastAPI/uvicorn), `mcp` (official Python MCP SDK),
`climate` (xarray, zarr, fsspec/gcsfs, cftime, PsychroLib and solar support),
`cds` (cdsapi/NetCDF support), `all` (union). Development dependencies are separate.
Pin tested development versions; keep justified compatible ranges in package metadata.

```text
src/openepw/
  __init__.py             public convenience functions and model exports
  models/
    geography.py         Location, BoundingBox, PolygonQuery, SamplingSpec
    requests.py          WeatherRequest, FutureRequest, policy objects
    discovery.py         Candidate, DiscoveryResult, availability and capabilities
    plans.py             SourceRef, FetchTask, TransformStep, OutputSpec, WeatherPlan
    artifacts.py          ArtifactRef, ArtifactBundle, Manifest, VariableLineage
    jobs.py              WeatherJob, states and progress
    errors.py            OpenEPWError, Issue, stable error codes
  dataset.py             WeatherDataset (DataFrame + typed metadata)
  config.py              secret-bearing runtime configuration, never plan content
  service.py             geocode/discover/plan/execute/fetch/future orchestration
  providers/
    base.py              provider protocol and registry
    http.py              timeouts, bounded retries, redaction, response limits
    openmeteo.py, pvgis.py, onebuilding.py, noaa_isd.py, nsrdb.py, era5.py
  geocoding/openmeteo.py  independent named-point resolver
  discovery/selection.py capability filtering and transparent ranking
  planning/
    weather.py, future.py plan construction
    spatial.py           shared regular grid sampling and query-to-source map
    hybrid.py            explicit variable assignments and alignment rules
  epw/
    schema.py            field definitions and sentinels
    reader.py, writer.py  artifact codec; preserve source headers
  qc/checks.py            structural/physical checks, no hidden repairs
  generation/
    base.py              generator capabilities/protocol
    cmip6.py             catalog selection, licensed climate signal extraction
    morph.py             independent published-equation implementation
    hourly_archive.py    OEDI locations, ZIP64/range access, ETag cache
    climate_profile.py   medoid/extreme/coherent-year selection
  artifacts/store.py     atomic bundle writes, checksum and URI lookup
  cache/store.py         raw/normalized caches and provenance keys
  jobs/store.py          SQLite durable state, item progress/idempotency
  jobs/worker.py         bounded local worker, cooperative cancellation
  api/app.py             FastAPI routes, dependency injection only
  mcp/server.py          tool/resource adapters, no weather logic
  cli/main.py            argparse thin entry points
tests/{unit,integration,fixtures,golden}/
examples/{point.py,batch.py,future.py,rest.py}
```

Dependency direction: models/EPW/QC → providers/generators → service/planning/jobs
→ adapters (arrow means “used by”). Adapters call Python services directly; MCP
does not call REST. Domain modules never import adapters. `WeatherDataset` is not
a JSON DataFrame dump and EPW text is not the internal scientific representation.

## Public operations

```python
geocode(query: str, *, mode: str = "point") -> GeocodeResult
discover(request: WeatherRequest) -> DiscoveryResult
plan(request: WeatherRequest, *, discovery: DiscoveryResult | None = None) -> WeatherPlan
execute(plan: WeatherPlan, *, config: RuntimeConfig | None = None) -> ArtifactBundle
fetch(request: WeatherRequest, *, config: RuntimeConfig | None = None) -> ArtifactBundle
plan_future(request: FutureRequest) -> WeatherPlan
generate_future(baseline, *, target_year=None, climate_period=None,
                reference_period=None, climate_scenario, method="morph",
                profile="typical", models=None, members=None, extreme=None,
                config=None) -> ArtifactBundle
```

`generate_future` validates a `FutureRequest`, plans and executes. Baseline may be
a local path, ArtifactRef or WeatherDataset in Python. HTTP/MCP use uploaded
artifact IDs, never arbitrary server filesystem paths. Blocking core methods
also work without a job server. Async jobs wrap those operations with progress
and cancellation hooks. `RuntimeConfig` is process-local, not a wire schema.

## Core schemas (Pydantic, version `0.1`)

| Schema | Required fields and invariants |
| --- | --- |
| Location | `lat[-90,90]`, `lon[-180,180]`; optional id/name/elevation/standard_offset_minutes. Reject nonfinite values; preserve original query |
| BoundingBox | west/south/east/north; south<north; explicit antimeridian split if west>east |
| PolygonQuery | GeoJSON Polygon coordinates in lon/lat; closed valid rings including holes; reject self-intersections rather than silently fixing |
| SamplingSpec | positive `dx_km`, `dy_km` (default 25 each), optional WGS84 origin and offsets; max_locations guard; boundary-inclusive grid excluding holes |
| GeocodeResult | query, mode, candidates (canonical Location, provider result id, display name, country/admin labels), attribution, ambiguity issues; no silent choice among homonyms |
| WeatherRequest | schema_version, locations (Location/list/bbox/polygon), sampling, product, years or explicit dates or published product_id, provider/dataset preferences, required_variables, hybrid_policy, missing_policy, leap_policy, output formats. Product/year combinations validated |
| Candidate | stable id, provider, dataset/version/product_id, weather_types, coverage/available periods with evidence timestamp, native resolution per variable group, interval, variables/derivations, access_path, provenance_type, source location, credential/terms requirements, missing fields, warnings, default-selection reasons; unknown values nullable |
| DiscoveryResult | normalized request locations, all candidates, selected_candidate_ids, issues, observed_at; no silent fallback |
| SourceRef | provider, access_path, dataset/version, station/grid identity if known, actual lat/lon/elevation, requested-to-source distance, resolution, license/citation, availability; unresolved source marked provisional |
| FetchTask | id, SourceRef, native request parameters without secrets, expected interval/variables/bytes/calls (nullable estimates), cache_key, dependents |
| TransformStep | id, method/version, input task/variable refs, parameters, output variables/units, alignment and missing policy; acyclic dependencies |
| OutputSpec | requested_location_id, source refs, product/year/period, formats, deterministic relative name |
| WeatherPlan | schema_version, kind=weather/future, request, selected candidates, source mapping, tasks, transforms, outputs, estimated calls/bytes/artifacts, warnings, capability versions, plan_hash. Stable canonical JSON hash excludes timestamps/secrets |
| WeatherDataset | DataFrame with UTC interval ends for actual series (or explicit synthetic calendar), source row year/month/day labels for TMY, units, interval semantics, fixed output offset, location metadata, variable lineage and headers. No mixed units or implicit DST |
| VariableLineage | variable, provider/dataset/version/access_path, source coordinates, raw checksum, transforms/dependencies, derived/filled/unchanged flags, affected row ranges and license |
| FutureRequest | baseline ref, method, target_year and/or actual window, reference_period, scenario namespace+id, profile, model/member selectors, extreme options; validate supported capability combinations |
| ArtifactRef | opaque id, relative path/URI, media type, bytes, sha256, role, location/output id; path confined to job root |
| ArtifactBundle | bundle_id, weather (list of EPW ArtifactRef), request/plan/manifest/qc ArtifactRef, additional artifacts and issues; convenience results reference files rather than embedding tables |
| Manifest | package/schema versions, request/plan hashes, timestamps, input/output refs, source periods/locations, variables/lineage, transformations, timezone/leap policies, licenses/citations, future-method parameters and limitations |
| Issue / OpenEPWError | stable code, severity, message, field/location/task context, retryable flag and redacted provider status; raw exceptions stay out of wire output |
| WeatherJob | id, plan hash, state, total/completed/failed items, submitted/started/finished times, cancellation request, item errors, artifact refs, idempotency key |

Error codes include `UNSUPPORTED_GEOGRAPHY`, `UNAVAILABLE_PERIOD`,
`PROVIDER_UNAVAILABLE`, `AUTH_REQUIRED`, `TERMS_REQUIRED`, `RATE_LIMITED`,
`MALFORMED_RESPONSE`, `MISSING_CRITICAL_VARIABLE`, `EPW_CONVERSION_FAILED`,
`UNSUPPORTED_FUTURE_METHOD`, `INVALID_GEOMETRY`, `INVALID_SCENARIO_PERIOD`,
`PLAN_STALE`, `RESOURCE_LIMIT`, `JOB_PARTIAL_FAILURE` and `CANCELLED`.

## Provider contract and planning

```python
class WeatherProvider(Protocol):
    def discover(self, request: WeatherRequest, context: ProviderContext) -> list[Candidate]: ...
    def plan(self, candidate: Candidate, request: WeatherRequest,
             context: ProviderContext) -> list[FetchTask]: ...
    def fetch(self, task: FetchTask, context: ProviderContext) -> ProviderResult: ...
```

`ProviderContext` supplies HTTP/cache/runtime credentials and cancellation.
`ProviderResult` carries normalized WeatherDataset, optional native EPW, resolved
SourceRef, raw checksum and issues. Provider-specific options are namespaced and
validated; no primary `download_nsrdb()` API. Metadata lookups may perform small
calls while planning; expensive data retrieval waits for execution.

Deduplicate only verified identical source requests, including provider/dataset
version, station/cell, date range, interval, variables, elevation/horizon options
and transformation version. If the API resolves its cell only at fetch time,
label the estimate provisional, then deduplicate only once confirmed; never
promise exact call collapse based on rounding. Keep a requested-location → source
mapping. Native files keep original location metadata; a point list may reference
one artifact multiple times without inventing relocated observations.

Spatial sampling uses a local distance-based regular grid with explicit origin
and latitude-dependent longitude spacing; record coordinates, units and method.
Split dateline boxes, include polygon boundaries, exclude hole interiors, reject
unsupported polar/singular grids with structured errors. Cap points before allocation.
Warn when requested spacing is below known native scale; unknown resolution stays
unknown. No claim of finer weather resolution from denser sampling.

Hybrid policy defaults off. When enabled, a plan names source per variable,
alignment/resampling/derivation and source mismatch warnings. Do not silently
substitute station sea-level pressure, modeled solar or a different time basis.
Replaying a plan never reselects providers silently; changed metadata yields
`PLAN_STALE` and a new plan. Exact replay requires cached checksummed raw inputs;
without them record new fetch checksums and possible upstream changes.

## REST and MCP

| REST route | Contract |
| --- | --- |
| POST `/v1/geocode` | query/mode → GeocodeResult |
| POST `/v1/weather/discover` | WeatherRequest → DiscoveryResult |
| POST `/v1/weather/plan` | WeatherRequest + optional discovery → WeatherPlan |
| POST `/v1/weather/jobs` | WeatherPlan + optional idempotency key → 202 WeatherJob |
| POST `/v1/future/plan` | FutureRequest → WeatherPlan |
| POST `/v1/future/jobs` | future WeatherPlan → 202 WeatherJob |
| GET `/v1/jobs/{id}` | WeatherJob with per-item failures |
| POST `/v1/jobs/{id}/cancel` | cooperative cancellation request |
| GET `/v1/jobs/{id}/artifacts` | manifest + compact ArtifactRef list |
| POST `/v1/artifacts` | bounded baseline EPW upload → ArtifactRef |
| GET `/v1/artifacts/{id}` | validated artifact bytes/download |
| GET `/health` | local readiness; no provider requests |

MCP tools: `weather_geocode`, `weather_discover`, `weather_plan`, `weather_fetch`,
`weather_inspect`, `weather_generate_future`. `weather_plan(kind=...)` routes both
request families; `weather_fetch(plan=...)` executes/submits a reviewed weather
plan. `weather_generate_future` accepts request or future plan. `weather_inspect`
returns job status, QC and artifact refs. EPWs are resources, not 8,760 inline rows.
Stdio first, Streamable HTTP next; same core schemas, no MCP-native job dependency.

## Storage, jobs, configuration and deployment

SQLite plus filesystem; one bounded worker process/thread pool, no Redis/Celery.
States: queued, running, completed, partially_completed, failed, cancelled. Persist
per-item completion and errors; resume safe unfinished tasks after restart, verify
completed checksums, avoid duplicate outputs via plan/idempotency keys. Cancellation
stops scheduling, preserves completed artifacts, records in-flight outcome. Never
report completed if some required artifacts failed.

```text
data-root/
  jobs.sqlite3
  cache/{raw,normalized}/<content-or-request-hash>/
  jobs/<job-id>/{request.json,plan.json,manifest.json,qc.json}
  jobs/<job-id>/weather/<location-product-period-provider-hash>.epw
```

Atomic temporary-file rename, output checksums and safe artifact identifiers.
Raw cache key includes provider/dataset/version/query; normalized cache additionally
includes code/transform version. Jobs retain immutable input references. Credentials
resolve programmatic override → environment → ignored local TOML. Secrets and
signed download URLs are redacted before persistence; plans carry credential
requirement names only. One process owns SQLite writes with WAL/busy timeout.

Service binds localhost by default. Remote deployments require configured bearer
authentication, upload/request limits and owner-controlled provider endpoints;
do not expose arbitrary URL fetching or server path reads. REST/MCP credentials
are runtime context, never accepted into persisted weather request bodies.

See [EPW conventions](docs/methods/epw-conventions.md),
[method definitions](docs/methods/future-weather.md), and
[decisions](docs/decisions/0001-stage-1-design.md).
