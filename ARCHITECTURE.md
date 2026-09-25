# OpenEPW architecture

Implemented v0.1 architecture, 2026-09-20. Stage 2 was approved by the owner;
[execution decisions](docs/validation/stage-2-ledger.md) and
[acceptance](docs/validation/v0.1-acceptance.md) record evidence and limits.

## Boundaries

Python 3.11+, Hatchling/src layout. pandas/numpy tables, Pydantic wire contracts,
httpx transport with system certificate trust. Domain modules do not import
FastAPI, MCP or xarray. Heavy climate readers and service adapters import their
optional dependencies only when used.

```text
src/openepw/
  __init__.py             public Python convenience API
  models/__init__.py      versioned geography/request/plan/artifact/job contracts
  config.py              runtime secrets and configuration precedence
  dataset.py             scientific table and interval conventions
  epw/{schema,reader,writer}.py
  qc/checks.py
  providers/{base,http,openmeteo,pvgis,onebuilding,noaa_isd,nsrdb,era5}.py
  availability/{models,store,stage1,bootstrap,freshness,refresh,evaluate,recommend}.py
  availability/importers/{contracts,climate}.py
  planning/{spatial,hybrid,future,output_identity,batch,store}.py
  service.py             discovery, planning, execution and bundles
  generation/{cmip6,morph,hourly_archive,climate_profile}.py
  artifacts/{store,export}.py  atomic files, checksums, compact export
  jobs/{store,worker}.py  SQLite item records and bounded worker threads
  api/app.py             REST adapter
  mcp/server.py          MCP adapter
  cli/main.py            argparse adapter
```

The proposed fine-grained models/geocoding/cache modules were consolidated where
small functions/classes suffice. There are no separate REST/MCP weather algorithms.

## Public operations

`geocode`, `discover`, `assess_availability`, `plan`, `execute`, `fetch`, `plan_future`, and
`generate_future` are exported from `openepw`. `WeatherService` supports injected
providers and HTTP transport for testing/embedding. Python accepts local baseline
paths, registered `ArtifactRef`s or `WeatherDataset`s. REST/MCP future requests
accept registered artifact IDs only. Planning snapshots baseline and signal files
as immutable, checksummed artifacts.

`WeatherRequest` accepts a Location, point list, BoundingBox, or GeoJSON-style
PolygonQuery; actual years or inclusive dates; a published product ID; provider
ordering; dataset-level selections; required variables; explicit hybrid assignments
and missing policy. `FutureRequest` separates SSP/RCP scenarios, reference and target periods,
method, profile and model/member selectors. Unknown fields/schema versions fail.

`WeatherPlan` contains the typed request, source candidates, fetch tasks, output
mapping, warnings, cost estimates and stable canonical hash. Timestamps in candidate
observations do not affect its identity. Task cache identifiers are SHA-256 values;
weather execution verifies them against source/request inputs. Plan graph references
and artifact names are validated. A hash is an integrity check, not authorization;
execution also restricts provider endpoints, climate stores and resource budgets.
Each new `OutputSpec` has a deterministic ID distinct from its fetch task IDs and
semantic EPW filename. An occurrence index keeps even identical requested point
entries distinct. Legacy persisted plans without output IDs retain their old hashes
and use filenames as their internal item keys.

## Weather semantics

WeatherDataset stores a pandas frame indexed by timezone-aware UTC **interval ends**,
with interval length, units, location/fixed offset, calendar, original row years,
headers, per-variable lineage, metadata and issues. Solar columns are interval
Wh/m². State samples may be instantaneous at the interval end and are identified
as such in lineage. No daily-to-hourly fabrication, hidden DST conversion or gaps
filled as zero. Fractional-hour historical conversion currently fails explicitly;
request UTC or an integer-hour fixed offset.

The EPW codec owns eight headers and 35 fields, field-specific missing sentinels,
hour 24, native minute-zero compatibility and independent partial/annual QC. Native
TMY row years remain separate from the synthetic timeline. Explicit noleap sources
use a synthetic 365-day timeline and an exported calendar marker, retaining source
year labels. `read_epw` assigns honest input-file provenance when original provider
identity is unknown. Original downloaded EPWs accompany normalized native products.

## Providers, discovery and cache

MCP Stage 2 adds an ignored local SQLite availability catalog. Explicit offline
`catalog import` validates the saved Stage 1 ledger/raw checksums and analysis,
then stages and atomically activates an immutable generation. The packaged review
registry contains accepted decisions, not the full source inventories. Full import
requires the local analysis to carry matching ledger/source input fingerprints;
an absent analysis leaves inventory-dependent answers unknown through bundled
contracts. No full inventory or generation manifest is tracked in Git. Assessments
pin one active generation, evaluate each input occurrence independently, then rank
eligible and uncertain alternatives with reasons. Actual sparse years, TMY source
reference periods and future scenario/windows have separate tagged scopes. A
supported assessment means eligible to attempt retrieval, not complete weather.
Access/terms and operational health are reported separately. When no catalog is
loaded, bundled dated Open-Meteo/CDS contracts screen documented capabilities;
inventory-dependent facts remain typed unknowns. Evidence ages against local
source check cadences. Source refresh is opt-in per query and keeps the last good
generation on failure, including partial replacements. Broad responses retain the first 50
ranked options per occurrence and report truncation.

Discovery consumes these shared assessments when a catalog is active. Verified
fetch-task equivalence and full output mapping are Stage 3a execution concerns.
Each planned occurrence, dataset and period has a batch row, including unsupported
and unresolved combinations. Weather plans persist under their integrity hash.
Jobs use SQLite item records and reuse verified source results only within one
active job; checksum-verified output artifacts survive restart. Final manifests
record every row's status, source/QC links and separate request/task/output counts.
An explicit compact ZIP has a complete CSV mapping and groups only byte-identical
outputs with matching task, transform and lineage semantics. The existing v0.1
request/plan identity and artifact contracts remain intact.

Providers implement `discover(request, location, http)` and
`fetch(task, http) -> ProviderResult(dataset, source, raw, native_epw)`.
The service owns generic planning, cache and output orchestration. Discovery returns
alternatives and explains selection by missing fields, caller provider order and
credential requirements, including the full ranking per requested point. A
dataset-level selection resolves its own locally ranked station at each point;
unavailable point/dataset combinations remain explicit plan issues, never a
silently substituted dataset. A successful HTTP status is not proof of usable weather.

Only fully resolved source requests with identical scientific options deduplicate.
Unknown cells remain provisional. Batches maintain requested-location → output
mapping without moving native station metadata. Grid sampling is distance-based
using latitude-adjusted longitude spacing; dateline boxes split naturally, polygon
holes are excluded, point counts are capped before allocation.

Hybrid plans explicitly assign each variable to a provider. Timelines/calendars/units
must match. Subhourly states aggregate only with all required observations; interval
solar sums preserve energy and missingness; wind direction uses a circular mean.
There is no implicit secondary-source fill.

HTTP has bounded retries/timeouts/response sizes, certificate verification, redacted
errors/logs and a narrow NSRDB object-store redirect allowlist. Raw response caches
commit only after successful parsing. Credential-bearing/short-lived CDS polling
metadata and signed download URLs are not persisted. Cache identity includes source,
request and transform version; bytes are verified by SHA-256 before replay.

## Future methods

CMIP6 catalog selection requires the complete tas/tasmin/tasmax/hurs/ps/sfcWind/rsds
intersection for coherent models/members. Only approved Pangeo CMIP6 stores are read.
Calendar-aware monthly aggregation requires complete requested windows. Model signals,
source locations, units, licenses and extracted-input checksums accompany outputs.
Monthly morphing is an independent shift/stretch implementation. Hourly archive
selection uses bounded ZIP64 ranges, ETags, CRC and decompression limits to read
whole WRF trajectories. See [method contract](docs/methods/future-weather.md).

## Artifacts and jobs

```text
data-root/
  jobs.sqlite3
  artifacts/<opaque-id>.json
  cache/{raw-v2,cmip6,ranges}/...
  jobs/<bundle-id>/{request.json,plan.json,manifest.json,qc.json,*.epw}
```

Atomic writes use same-directory temporary files and replacement. Artifact reads
verify checksum and root confinement. Baseline provenance is retained even where
original provider metadata is unknown. Manifests include plan/request identity,
source and output mappings, per-variable lineage, transformations, warnings, and
`simulation_ready=false`.

SQLite uses WAL/busy timeout. Each unique output item is recorded independently;
a shared source retrieval may therefore fan out to several EPWs. New items are
keyed by output ID rather than display filename. Connections close after each
transaction, and completed/failed counts persist during running jobs.
A restarted worker verifies and reuses completed bundles, then executes remaining
items. Jobs support idempotency keys, queued/running/completed/partially_completed/
failed/cancelled states, counts, linked failed-output retry and cooperative
cancellation. Use one server process
per data root; worker threads are bounded. Failed items do not cause successful
items to disappear. No Redis/Celery/database server is required.

## Interfaces and deployment

REST: POST `/v1/geocode`, `/v1/availability`, `/v1/weather/discover`, `/v1/weather/plan`,
`/v1/weather/jobs`, `/v1/future/plan`, `/v1/future/jobs`, `/v1/artifacts`,
`/v1/jobs/{id}/cancel`, `/v1/jobs/{id}/retry`, `/v1/jobs/{id}/export/compact`;
GET `/v1/jobs/{id}`, `/v1/jobs/{id}/artifacts`, `/v1/artifacts/{id}`, `/health`.
Weather jobs accept an inline plan or stored plan hash plus optional idempotency key;
future jobs retain inline plans. CLI `execute` accepts a plan file or stored hash,
and `export` takes a finished weather job ID.
Uploads accept bounded EPW files, never arbitrary server paths. Remote REST requires
a runtime bearer token; default binding is loopback. Request validation does not
echo potentially secret inputs.

MCP exposes `weather_geocode`, `weather_discover`, `weather_plan`, `weather_fetch`,
`weather_inspect`, `weather_generate_future` and artifact resources. It calls the
Python service directly. Stdio and loopback Streamable HTTP are supported; remote
MCP authentication is deferred rather than exposed without protection.

MCP availability research tooling lives under `scripts/mcp_research/`, outside the
installed package. Its bounded collector and offline inventory analysis feed the
[Stage 1 findings](docs/validation/mcp-stage-1/README.md). The Stage 2 catalog and
recommendation service are implemented, with direct Python/REST/CLI access. The
existing MCP `weather_discover` serializes enriched shared results; Stage 4 owns
the final MCP tool contract.
The local availability map builder lives under `scripts/mcp_availability_map/` and
reads ignored snapshots; it is a research visualization, not a production service
or a source of eligibility decisions.

Configuration precedence: programmatic overrides → environment → explicitly loaded
local dotenv → ignored local TOML. Credentials are SecretStr runtime fields and
never request/plan fields. [Configuration template](config.example.toml),
[usage](docs/usage.md), [limitations](docs/limitations.md).
