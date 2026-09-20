# OpenEPW — Agent Development Brief

## 0. Purpose of this document

This document is the complete handoff brief for developing **OpenEPW** in a new public GitHub repository named **OpenEPW**. The coding agent receiving this document does **not** have access to prior conversations, so this document is the source of truth for product intent, scope, architecture, implementation stages, repository rules, collaboration rules, and human-intervention boundaries.

OpenEPW is a standalone open-source project. It is not an EnergyAtlas submodule, although EnergyAtlas or similar building-energy software may later consume it.

---

# 1. Product definition

## 1.1 One-sentence definition

**OpenEPW is a Python-first, open-source weather-data discovery, retrieval, normalization, EPW conversion, and future-weather generation toolkit for building-energy and related simulation workflows, with REST and MCP interfaces over the same core service layer.**

## 1.2 Canonical product identity

The canonical product is a **Python package**:

```bash
pip install openepw
```

Expected import:

```python
import openepw
```

The Python package is the primary implementation surface and source of truth.

OpenEPW should also expose:

1. a **small CLI** for common development and user workflows;
2. a **REST API/backend service** for remote or cross-runtime access;
3. an **MCP server** as a later interface layer, designed from the beginning but implemented after the underlying service functionality is working.

The REST API and MCP server must be thin adapters over the same service/domain layer. They must not contain independent weather-fetching or climate-generation logic.

## 1.3 Primary users

By expected call volume, **AI agents using MCP** may eventually be the largest consumers.

Human users are prioritized approximately as follows:

1. building-energy researchers and modelers;
2. EnergyPlus users;
3. urban-energy / building-stock / energy-system researchers and practitioners;
4. students;
5. broader users of EPW-compatible weather data.

OpenEPW should therefore be both:
- easy to call programmatically and repeatedly; and
- scientifically transparent enough for research use.

## 1.4 Scope philosophy

OpenEPW should be a **general EPW-oriented weather utility**, not a project-specific weather downloader.

It should support:
- lookup/discovery of available weather datasets;
- retrieval of existing historical, actual-year, typical-year, and other published weather products;
- normalization and conversion into EPW;
- multi-location and spatial/batch workflows;
- future-weather generation using more than one method;
- transparent provenance, warnings, and quality metadata.

The project should not require a frontend UI. Any future UI belongs to a downstream application or a separate demonstration project.

---

# 2. Key conceptual split

OpenEPW has two major capability families.

## 2.1 Existing weather retrieval

This side should **retrieve what already exists**.

Examples:
- AMY / actual meteorological year;
- TMY / TMY3 / TMYx;
- XMY or other published/extreme weather products where a source directly provides them;
- provider-native historical or reanalysis weather that can be normalized and serialized to EPW.

Important rule:

> OpenEPW should not synthesize retrospective TMY/XMY files merely because it has historical observations.

For past or present conditions:
- discover;
- retrieve;
- normalize;
- convert;
- validate;
- export.

Do not introduce a standalone historical TMY-generation or historical XMY-generation subsystem in v0.1.

## 2.2 Future weather generation

Future weather is a separate operation based on:
- an input EPW supplied by the user; or
- an EPW/weather artifact retrieved through OpenEPW.

Future weather generation should use scenario/profile concepts such as:

```text
typical
extreme
ensemble
sampled   # experimental / lower priority
```

Do not expose separate top-level `generate_tmy()` and `generate_xmy()` APIs for future weather. Instead, future typical/extreme profiles are modes under one future-weather generation interface.

Example:

```python
future = openepw.generate_future(
    baseline="baseline.epw",
    target_year=2050,
    climate_scenario="ssp245",
    profile="typical",
)
```

Example:

```python
future = openepw.generate_future(
    baseline="baseline.epw",
    target_year=2050,
    climate_scenario="ssp585",
    profile="extreme",
    extreme={
        "type": "hot",
        "mode": "shock",
    },
)
```

---

# 3. Required public workflow

The project must implement the following workflow as first-class public concepts:

```text
geocode -> discover -> plan -> execute/fetch
                         \
                          -> generate_future
```

The normal workflow should favor transparency.

## 3.1 `geocode(...)`

Geocoding is a separate operation from weather discovery.

It translates human location descriptions into one or more canonical geographic inputs.

Examples:

```python
openepw.geocode("London")
```

Default interpretation may produce a representative center point.

But the API should support modes/parameters that may produce different geographic interpretations where feasible, for example:
- city center;
- administrative-area polygon;
- airports in or associated with a named area;
- other future resolvers.

Geocoding should ultimately return canonical geographic objects that the weather-query system already understands.

Do not tightly couple weather providers to geocoding.

## 3.2 `discover(...)`

Discovery is one of the central differentiators of OpenEPW.

Users often do not know:
- which datasets exist at a location;
- which years are available;
- which variables are available;
- whether a dataset is station-based, reanalysis, satellite-derived, modeled, or hybrid;
- the spatial and temporal resolution;
- whether a nearby published TMY exists;
- whether API credentials are required;
- whether an intended EPW can be produced without missing important variables.

`discover()` should return factual alternatives and enough metadata for a user or agent to reason about them.

Example conceptual output:

```json
{
  "location": {"lat": 42.44, "lon": -76.50},
  "candidates": [
    {
      "provider": "nsrdb",
      "dataset": "psm",
      "weather_types": ["amy", "historical"],
      "available_years": [1998, 2025],
      "native_spatial_resolution_km": 2.0,
      "native_temporal_resolution_minutes": 10,
      "variables": ["dry_bulb", "dew_point", "ghi", "dni", "dhi", "wind_speed"],
      "provenance_type": "satellite_model",
      "requires_credentials": true,
      "selected_by_default": true,
      "selection_reasons": [
        "high spatial resolution",
        "good solar coverage"
      ]
    }
  ]
}
```

Discovery must:
- show alternatives;
- provide factual suitability metadata;
- provide a transparent default selection where useful;
- never hide alternative candidates simply because one default is chosen.

## 3.3 `plan(...)`

Planning converts a high-level request into a reproducible execution plan.

A `WeatherPlan` should be a real serializable domain object.

It should be able to include:
- requested locations;
- resolved source locations/grid cells/stations;
- provider/dataset selections;
- requested years/ranges;
- duplicate-grid-cell collapse/deduplication;
- expected provider calls;
- transformations;
- EPW outputs;
- warnings;
- missing-variable handling;
- expected artifact count;
- future-weather methods if applicable.

The planning step should make expensive or ambiguous requests inspectable before execution.

Example:

```python
plan = openepw.plan(request)
```

Plans should be serializable and replayable where practical.

## 3.4 `execute(...)` / `fetch(...)`

`execute(plan)` executes a plan.

A convenience `fetch(...)` API may:
- discover;
- plan;
- execute;
internally for users who do not need manual staging.

However, discovery and planning remain first-class public APIs.

## 3.5 `generate_future(...)`

Future weather generation operates on:
- user-supplied EPW; or
- an OpenEPW artifact / `WeatherDataset`.

It should support:
- target year;
- explicit climate period/window;
- climate scenario;
- future profile type;
- future method/provider;
- model/ensemble controls where supported.

---

# 4. Geographic inputs and spatial workflows

OpenEPW v0.1 should support:

## 4.1 Single point

```python
Location(lat=..., lon=...)
```

## 4.2 List of points

A list means several location queries and potentially several EPW outputs.

## 4.3 Bounding box

A bounding box should be sampled into a point array.

Sampling controls should include:
- spacing in X/longitude direction;
- spacing in Y/latitude direction;
- offsets/origin where meaningful;
- sensible defaults.

## 4.4 GeoJSON polygon

GeoJSON polygon inputs should also be sampled into a point array using the same underlying spatial sampling model.

The system should not require a sophisticated GIS meshing algorithm in v0.1. A regular sampling grid is sufficient.

## 4.5 Source-cell deduplication

If many requested points map to the same underlying provider grid cell, the system should detect and deduplicate provider requests.

Example warning:

```text
73 requested points resolve to 11 unique native weather grid cells.
Provider data will be downloaded once per unique cell and reused.
```

## 4.6 Resolution warnings

The user may request points more densely than the source resolution.

OpenEPW must surface this clearly rather than pretending finer weather information exists.

Example:

```text
Requested point spacing: 0.5 km
Provider native resolution: approximately 2 km
Multiple output locations will share the same source cell.
```

---

# 5. Initial provider targets

Target the following public data sources in v0.1:

1. **NSRDB / NLR**
2. **Open-Meteo**
3. **ERA5 / ERA5-Land**
4. **Climate.OneBuilding**
5. **PVGIS**
6. **NOAA / ISD**

For ERA5-related access:
- support direct Copernicus/CDS access where feasible;
- also support convenient access through Open-Meteo where applicable;
- provenance must distinguish the actual access path and underlying dataset.

Provider architecture must be extensible so future providers can be added without redesigning the public API.

## 5.1 Provider feasibility rule

These providers are targets, not reasons to stall the whole project indefinitely.

The agent should:
1. make a serious implementation attempt;
2. try multiple reasonable approaches if blocked;
3. inspect current provider documentation/API behavior;
4. document the exact blocker;
5. only then drop/defer the provider.

The target is at least four working providers, including ideally:
- one strong U.S. actual-year source;
- one global reanalysis source;
- one existing TMY/TMYx source.

However, even the four-provider target may be relaxed if external access restrictions genuinely make it impractical after repeated documented attempts.

A blocked provider must not silently disappear. Record:
- what was attempted;
- why it failed;
- whether credentials, licensing, rate limits, anti-bot behavior, API changes, or other restrictions caused the issue;
- what future work could restore it.

---

# 6. Provider abstraction

Implement a provider interface/protocol/base class.

Conceptually:

```python
class WeatherProvider(Protocol):
    def discover(...): ...
    def plan(...): ...
    def fetch(...): ...
```

Provider internals may vary substantially.

Examples:
- gridded API;
- station API;
- downloadable archive;
- HTML/catalog-backed file repository.

The domain layer should normalize these differences.

Provider-specific options should be available through advanced configuration, but the normal public API should not require the user to understand every provider's native request format.

Avoid exposing separate top-level public functions such as:

```text
download_nsrdb()
download_era5()
download_onebuilding()
```

as the primary API.

Prefer:

```python
openepw.fetch(..., provider="nsrdb")
```

Provider-specific modules may still be directly importable for advanced users.

---

# 7. Data discovery metadata

Discovery results should expose as much of the following as can be reliably obtained:

- provider;
- dataset/product name;
- supported weather product types;
- geography/coverage;
- available year/date range;
- update latency/current availability;
- native spatial resolution;
- native temporal resolution;
- station/grid location;
- distance to station where relevant;
- variable list;
- variable provenance;
- measurement/reanalysis/satellite/model classification;
- credential requirement;
- known usage/rate limits;
- known licensing/redistribution constraints;
- whether native EPW is available;
- whether conversion is required;
- likely missing EPW fields;
- warnings relevant to building simulation.

Do not fabricate metadata if the source does not expose it.

---

# 8. EPW as the primary artifact

EPW is the primary product artifact.

CSV/tabular output may also be generated, but is secondary.

## 8.1 Internal representation

Do not make raw EPW text the internal architecture.

Implement a lightweight `WeatherDataset` abstraction.

Recommended approach:
- pandas-backed for normal single-location/single-year weather;
- optional xarray support for multidimensional climate/batch datasets where it materially helps.

Avoid forcing heavy xarray/dask dependencies onto simple users unless required.

## 8.2 EPW parser/writer/validator

OpenEPW should own a small, understandable EPW parser/writer/validator rather than making a large third-party package mandatory for the core artifact.

A pandas-based implementation is acceptable.

The parser/writer should:
- read standard EPW headers;
- parse hourly data rows;
- preserve useful metadata;
- write valid EPW;
- handle standard EPW missing-value markers;
- validate field counts/types/ranges sufficiently for building simulation use.

Lossless preservation of every obscure comment/header variation is desirable but not more important than correctness and maintainability.

## 8.3 EPW fields and missing values

Not all EPW fields are required by every simulation workflow, and many real EPWs use standard missing-value sentinels for unavailable fields.

Therefore:
- do not fail merely because every possible EPW column is not available;
- use standard EPW conventions for unavailable fields;
- identify fields that are commonly necessary or important for building/radiation simulation;
- issue stronger warnings when such important fields are absent.

Examples of frequently important variables include:
- dry-bulb temperature;
- dew point or humidity information;
- relative humidity;
- atmospheric pressure;
- GHI;
- DNI;
- DHI;
- wind speed;
- wind direction.

The exact validation rules should be verified against current EPW/EnergyPlus conventions during Stage 1.

---

# 9. Hybrid EPWs

OpenEPW should plan for and support hybrid EPWs where variables come from different providers.

Example:

```text
temperature/humidity -> station or reanalysis
solar radiation      -> NSRDB
missing fallback      -> ERA5
```

This must not happen opaquely.

Requirements:
- user must be warned;
- selection/mixing logic must be explicit;
- provenance must be tracked per variable or variable group;
- transforms and fallback decisions must appear in the manifest;
- scientific incompatibilities/time alignment issues must be surfaced.

Do not silently blend providers merely because values are missing.

---

# 10. Provenance and manifests

Every produced weather artifact should carry machine-readable provenance.

Recommended artifact bundle:

```text
job-or-request-id/
├── request.json
├── plan.json
├── manifest.json
├── qc.json
└── weather/
    ├── location_001_2024_nsrdb.epw
    ├── location_001_2024_nsrdb.csv
    └── ...
```

At minimum, manifests should record:

- OpenEPW version;
- request/plan schema version;
- requested location;
- actual provider location/grid/station;
- provider;
- dataset/product;
- source year/date range;
- spatial resolution;
- temporal resolution;
- timezone conventions;
- variables;
- per-variable provenance where necessary;
- transformations;
- interpolation/resampling;
- missing-data treatment;
- fallback provider usage;
- future-weather methodology where applicable;
- checksums if practical;
- warnings;
- creation timestamp.

Do not serialize credentials or secrets into manifests.

---

# 11. Existing TMY/TMYx/XMY behavior

For past/current weather products, OpenEPW should retrieve existing published files/products where available.

Examples include:
- TMY;
- TMY3;
- TMYx;
- XMY or other provider-specific products.

Preserve provider terminology in discovery metadata and manifests rather than normalizing away meaningful distinctions.

Examples:

```text
TMY
TMY3
TMYx 2009-2023
TMYx 2011-2025
```

Do not create a historical `generate_tmy()` or `generate_xmy()` feature in v0.1.

---

# 12. Future weather generation

This is a major v0.1 capability.

The project should implement at least **two methodologically distinct future-weather approaches**.

Do not satisfy this requirement merely by wrapping two packages that both implement essentially the same morphing algorithm.

## 12.1 Method family A — morphing

Implement or integrate a CMIP6-informed EPW morphing workflow.

Candidate references/libraries include:
- pyepwmorph;
- epwshiftr;
- Future Weather Generator;
- other current permissively reusable implementations.

The agent must review:
- current methodology;
- license;
- dependencies;
- supported variables;
- supported scenarios;
- climate-data access;
before deciding whether to depend on, adapt, or reimplement.

## 12.2 Method family B — climate-profile / downscaled-hourly approach

Implement a materially different method based on future climate-model or downscaled hourly time series where feasible.

Conceptually:

```text
future climate hourly/downscaled data
        ->
representative or extreme profile construction
        ->
EPW normalization/output
```

This should not simply be the same monthly-delta morphing algorithm under another package.

Exact provider/data source may depend on Stage 1 feasibility research.

## 12.3 User inputs

Support:

```python
generate_future(
    baseline=...,
    target_year=2050,
    climate_scenario="ssp245",
    profile="typical",
)
```

Also allow advanced explicit climate windows, for example:

```python
climate_period=(2041, 2070)
```

When a user provides `target_year=2050`, the implementation may internally use a climate window centered around or otherwise representative of that year. The manifest must state the actual climate period used.

Do not imply that a generated "2050 EPW" is a literal weather forecast for calendar year 2050.

## 12.4 Future profile types

### `typical`

Representative future conditions for the requested climate scenario/period.

### `extreme`

Future extreme conditions.

Top-level use should remain simple:

```python
profile="extreme"
```

Advanced configuration may include:

```python
extreme={
    "type": "hot",
    "mode": "shock",
}
```

or:

```python
extreme={
    "type": "hot",
    "mode": "persistence",
    "percentile": 0.95,
}
```

Do not pretend that "extreme" has one universally accepted scientific definition. The method used must be explicit in metadata.

### `ensemble`

Return multiple coherent future EPWs corresponding to:
- multiple climate models;
- ensemble members;
- scenario quantiles;
- other supported ensemble definitions.

Prefer coherent member-level outputs over independently mixing percentile values variable-by-variable.

### `sampled`

Architecture may support this concept, but arbitrary stochastic future-weather generation is **experimental/lower priority** in v0.1.

Do not block v0.1 on a sophisticated stochastic weather generator.

---

# 13. Future-weather provenance

Every future artifact should record, where applicable:

- baseline EPW identity/checksum;
- baseline source;
- requested target year;
- actual climate window used;
- climate scenario (e.g. SSP);
- climate model;
- ensemble member;
- percentile/quantile if used;
- generation method;
- method implementation/version;
- source climate dataset;
- transformed variables;
- variables left unchanged;
- any derived variables;
- extreme-profile parameters;
- limitations/warnings.

---

# 14. REST API

Use a modern Python REST framework, preferably **FastAPI**, unless Stage 1 finds a strong reason not to.

REST is a major supported interface because OpenEPW should be callable:
- locally;
- remotely;
- from another runtime;
- from another application;
- from downstream engineering software.

## 14.1 REST should mirror domain operations, not replace them

Conceptual routes:

```text
POST /v1/geocode
POST /v1/weather/discover
POST /v1/weather/plan
POST /v1/weather/jobs
GET  /v1/jobs/{job_id}
GET  /v1/jobs/{job_id}/artifacts
POST /v1/future/plan
POST /v1/future/jobs
```

Exact design may change, but preserve the domain concepts.

## 14.2 Job system

v0.1 should include a lightweight asynchronous job model for large requests.

Small requests may execute synchronously.

Large/batch jobs should support states such as:

```text
queued
running
completed
partially_completed
failed
cancelled
```

Use lightweight local infrastructure first:
- SQLite;
- local filesystem artifact storage;
- in-process/background worker where reasonable.

Do not introduce Redis/Celery/Kubernetes-class infrastructure unless truly necessary.

The architecture should allow stronger distributed infrastructure later.

---

# 15. MCP server

MCP is required, but should be implemented after the underlying service functionality is proven.

It must be designed from the beginning so that the core API does not become hostile to agent use.

## 15.1 MCP must be a thin adapter

Never implement provider/weather logic inside the MCP layer.

Correct:

```text
MCP tool
  -> service/domain API
  -> provider/generator
```

Incorrect:

```text
MCP tool
  -> provider-specific download code
```

## 15.2 Suggested MCP tools

Initial tool surface should remain compact:

```text
weather_geocode
weather_discover
weather_plan
weather_fetch
weather_inspect
weather_generate_future
```

Do not create dozens of provider-specific MCP tools unless a strong need emerges.

## 15.3 Agent-oriented workflow

Tool descriptions should encourage:

```text
discover -> plan -> execute
```

especially for:
- expensive;
- batch;
- ambiguous;
- multi-provider;
- future-weather requests.

## 15.4 MCP resources / artifacts

Generated EPWs and manifests should be exposed as resources/artifacts rather than stuffing full 8760-row EPW content into tool responses.

Support stdio and Streamable HTTP if practical with the current MCP SDK.

Do not make MCP protocol-specific job/task abstractions the canonical internal job model. Map them onto the project's own `WeatherJob`.

---

# 16. CLI

Provide a limited CLI.

It is not a major product surface and should not consume large implementation effort.

Examples:

```bash
openepw geocode "London"
openepw discover --lat 42.44 --lon -76.50
openepw fetch --lat 42.44 --lon -76.50 --year 2024 --provider nsrdb
openepw future baseline.epw --year 2050 --scenario ssp245 --profile typical
```

CLI should be useful for:
- smoke testing;
- scripting;
- demonstrations;
- simple user workflows.

Do not build a complex interactive terminal UI.

---

# 17. Credentials and configuration

Support, in reasonable precedence order:

1. explicit programmatic/request override;
2. environment variables;
3. optional local configuration file.

Exact precedence should be documented.

Never:
- commit real credentials;
- serialize credentials into plans/manifests;
- print secrets into logs.

Repository should include tracked templates such as:

```text
.env.example
config.example.toml
```

Local secret-bearing versions must be gitignored.

---

# 18. Online requirement and caching

OpenEPW is fundamentally an online data-access tool.

It does not need to promise full offline operation.

Caching is still desirable for:
- raw provider responses;
- normalized datasets;
- generated artifacts;
- duplicate grid-cell reuse.

Cache design should favor correctness and reproducibility.

Cache keys should incorporate enough information to avoid accidental reuse across:
- providers;
- dataset versions;
- locations/grid cells;
- years;
- query parameters;
- transformations.

Provide basic cache inspection/cleanup utilities if easy, but do not overbuild cache management in early milestones.

---

# 19. Quality control

Implement sensible weather/EPW QC.

At minimum check where relevant:
- missing timestamps;
- duplicate timestamps;
- expected interval/frequency;
- temperature plausibility;
- relative humidity range;
- pressure plausibility;
- negative/inconsistent solar radiation;
- nighttime solar issues;
- wind plausibility;
- missing key variables;
- standard EPW missing-value sentinel usage;
- timezone/standard-time consistency;
- leap-year handling.

QC should distinguish:
- errors;
- warnings;
- informational notices.

Avoid aggressive auto-repair that changes scientific data without a clear record.

If data are repaired/filled/derived, record it in provenance.

---

# 20. Errors and warnings

Define structured exceptions/error codes for at least:

- unsupported geography;
- unavailable year/date;
- provider unavailable;
- provider auth/credential issue;
- rate limit;
- malformed response;
- missing critical variable;
- EPW conversion failure;
- future-weather method unsupported for request;
- invalid geometry;
- invalid scenario/period;
- job partial failure.

Warnings should be machine-readable where practical, not only free-text strings.

This is especially important for MCP/agent consumers.

---

# 21. Suggested package architecture

Use one repository.

Do **not** split REST and MCP into separate repos at this stage.

Recommended structure:

```text
OpenEPW/
├── src/
│   └── openepw/
│       ├── models/
│       ├── providers/
│       │   ├── base.py
│       │   ├── nsrdb.py
│       │   ├── openmeteo.py
│       │   ├── era5.py
│       │   ├── onebuilding.py
│       │   ├── pvgis.py
│       │   └── noaa_isd.py
│       │
│       ├── geocoding/
│       ├── discovery/
│       ├── planning/
│       ├── epw/
│       ├── qc/
│       ├── generation/
│       │   ├── base.py
│       │   ├── morph.py
│       │   └── climate_profile.py
│       ├── jobs/
│       ├── artifacts/
│       ├── cache/
│       ├── api/
│       ├── mcp/
│       └── cli/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── golden/
├── examples/
├── docs/
├── scripts/
├── pyproject.toml
├── README.md
├── AGENTS.md
├── CONTRIBUTING.md
├── ARCHITECTURE.md
├── FEATURES.md
├── ROADMAP.md
├── LICENSE
└── .env.example
```

The agent may refine this after Stage 1, but preserve separation of:
- scientific/data core;
- provider integrations;
- service/domain orchestration;
- REST adapter;
- MCP adapter.

---

# 22. Dependency direction

Maintain a strict dependency direction.

Conceptually:

```text
models / epw / qc
        ^
        |
providers + future generators
        ^
        |
service/discovery/planning/jobs
        ^
        |
+-------+-------+
|               |
REST            MCP
|
CLI/SDK convenience
```

The MCP layer must not call REST merely because REST exists.

The REST layer must not contain core business logic.

The Python package/service layer is canonical.

---

# 23. Packaging

Project:
- display name: **OpenEPW**
- PyPI package: `openepw`
- Python import: `openepw`
- CLI command: `openepw`

Use optional dependency groups.

Conceptually:

```bash
pip install openepw
pip install "openepw[api]"
pip install "openepw[mcp]"
pip install "openepw[climate]"
pip install "openepw[all]"
```

Avoid forcing all server, MCP, xarray/dask, climate-data, and provider-specific dependencies onto simple EPW users.

---

# 24. Licensing

OpenEPW should use the **MIT License**.

Dependency/reuse policy:

- prefer MIT/BSD/Apache-2.0 dependencies and source material;
- avoid GPL/AGPL dependencies in the core unless there is a compelling reason;
- direct dependency on permissively licensed libraries is allowed;
- adapting permissively licensed code is allowed with proper notices/attribution;
- studying published methods/algorithms and implementing them independently is allowed where legally appropriate;
- maintain required notices for reused/adapted code;
- if a license is ambiguous, do not copy code until clarified.

A full formal license audit is not required for every trivial dependency, but Stage 1 must check the licenses of:
- weather/future-generation libraries being considered for direct reuse;
- any code the agent intends to copy/adapt;
- unusual provider SDKs.

---

# 25. Technical defaults

Unless Stage 1 finds a strong reason otherwise, prefer:

- Python 3.11+ or 3.12+;
- `pyproject.toml`;
- modern build tooling;
- Pydantic or equivalent typed validation for request/response/domain schemas where useful;
- pandas for ordinary weather tables;
- optional xarray for climate/multidimensional data;
- FastAPI for REST;
- pytest;
- Ruff;
- static typing with mypy or pyright;
- pre-commit hooks if lightweight;
- GitHub Actions CI;
- cross-platform behavior on Windows, macOS, and Linux.

Do not introduce a large framework where a small implementation is adequate.

---

# 26. Repository rules

The agent has broad authority inside the repository, subject to these rules.

## 26.1 General

- Full access within the repository is allowed.
- Keep the repository understandable to a new contributor.
- Maintain clear README and developer documentation.
- Prefer simple architecture over speculative abstractions.
- Keep important decisions in git-controlled files because multiple people/machines may collaborate and chat histories do not synchronize.
- Do not rely on undocumented conversational context.

## 26.2 Git safety

Branch naming (explicit owner clarification, 2026-09-20):
- Use purpose-based prefixes such as `feature/`, `fix/`, `refactor/`, or `docs/`.
- Do not prefix branches with an agent, model, personal name, or `codex/`.
- Preserve the owner's existing renamed branches; do not rename or recreate them.

Allowed:
- normal commits;
- branches;
- merges;
- pulls/fetches;
- ordinary conflict resolution;
- tags when appropriate.

Forbidden unless explicitly authorized by a human:
- force push;
- history rewriting;
- destructive rebase;
- hard reset that discards uncommitted/unpushed work;
- deleting other contributors' branches/work;
- rewriting published history.

Do not use destructive git operations merely to make the local state convenient.

## 26.3 Commit authorship

Do not list:
- AI agent names;
- model names;
- automated coding systems;
as commit author/co-author/trailer.

Use normal repository/user authorship configuration.

## 26.4 Commit frequency

Commit moderately often.

Good boundaries:
- feature;
- fix;
- provider integration;
- architecture stage;
- test milestone;
- documentation milestone.

Do not produce one giant commit for the entire project.

Do not produce dozens of meaningless tiny commits for trivial edits.

## 26.5 Commit messages

Use the repository's established concise pattern:

```text
fix(topic): concise description
```

If the repository later adopts a broader conventional-commit scheme by explicit human decision, follow the updated repo rule.

Until then, keep messages concise and topic-scoped.

## 26.6 Secrets

- Commit secret templates only.
- Keep local secret files ignored.
- Never commit API keys/tokens.
- If a real credential is discovered in tracked history, stop and alert the human because credential rotation may be required.

---

# 27. Collaboration rules

Assume multi-machine and multi-person collaboration.

Therefore:

1. Record important architectural/product decisions in git-controlled docs.
2. Keep `ARCHITECTURE.md`, `FEATURES.md`, and relevant decision records current.
3. Keep provider-specific limitations documented.
4. Avoid local-only knowledge.
5. Prefer deterministic scripts over undocumented manual setup.
6. Commit sample configuration templates.
7. If another contributor's work appears, preserve it and integrate carefully rather than overwriting it.
8. Before broad refactors, inspect current branches/state and existing docs.
9. Do not assume the agent is the only contributor.
10. If conflicting decisions are found in repo docs, prefer the newest explicit human-authored decision; document the conflict if unresolved.

Use ADRs or `docs/decisions/` when decisions are important enough to affect future contributors.

---

# 28. Documentation required early

Create and maintain at least:

## `README.md`
User-facing project overview, install, quick start, examples.

## `FEATURES.md`
Product capabilities, supported providers, current status, limitations.

## `ARCHITECTURE.md`
Domain model, package boundaries, provider interface, REST/MCP adapters, jobs/artifacts.

## `ROADMAP.md`
Milestones and provider/future-method status.

## `AGENTS.md`
Repository operating rules for coding agents.

## `CONTRIBUTING.md`
Human contributor guidance.

## `docs/providers/`
Provider-specific notes:
- auth;
- coverage;
- years;
- API quirks;
- rate limits;
- provenance;
- implementation state.

## `docs/methods/`
Future-weather methodologies and scientific assumptions.

## `docs/decisions/`
Important architectural/product decisions when needed.

---

# 29. Testing strategy

## 29.1 Unit tests

Cover:
- schemas;
- coordinate normalization;
- planning;
- EPW parsing/writing;
- QC;
- provider response normalization;
- provenance;
- filename/artifact generation;
- future-method transforms.

## 29.2 Provider fixtures

Commit small sanitized provider-response fixtures where licensing allows.

Use fixtures for deterministic CI instead of making every test hit live APIs.

## 29.3 Live integration tests

Create opt-in/provider-tagged integration tests for actual APIs.

Do not make ordinary CI depend heavily on:
- live provider uptime;
- rate limits;
- credentials.

## 29.4 Golden EPWs

Maintain a few small/golden reference EPWs.

Validate:
- structure;
- timestamps;
- key fields;
- statistics;
- round-trip behavior.

Byte-for-byte equality is not required when transformations are inherently non-byte-stable; use meaningful field/statistical comparisons.

## 29.5 EnergyPlus compatibility

If feasible without making CI excessively heavy, include at least a smoke-validation path confirming generated EPWs can be consumed by EnergyPlus or its weather processing tools.

This is useful but should not block all normal development if setup becomes disproportionately burdensome.

---

# 30. Stage structure and agent autonomy

Development is intentionally split into two major stages.

---

## STAGE 1 — validation, research, architecture, plan

Stage 1 is short and must happen before broad implementation.

The purpose is to validate external feasibility, not to spend weeks writing speculative docs.

### Stage 1 tasks

1. Initialize/inspect the repository.
2. Create baseline repo rules/docs.
3. Verify current provider APIs/web access for all target providers.
4. Make small real/sample requests where possible.
5. Verify authentication/credential needs.
6. Verify licensing of key libraries and code candidates.
7. Verify current EPW schema/conventions and missing-value conventions.
8. Survey candidate future-weather implementations/methods:
   - pyepwmorph;
   - epwshiftr;
   - Future Weather Generator;
   - other practical options.
9. Identify a viable second, methodologically distinct future-weather approach.
10. Produce/update:
    - `FEATURES.md`;
    - `ARCHITECTURE.md`;
    - `ROADMAP.md`;
    - provider feasibility matrix;
    - Stage 2 implementation plan.
11. Include explicit proposed package/module structure.
12. Include explicit API/domain schemas at a useful level of detail.
13. Identify any provider/method that appears blocked and explain why.

### Stage 1 implementation allowance

Small proof-of-concept code is allowed and encouraged:
- sample fetch scripts;
- quick API pins;
- temporary experiments;
- schema prototypes.

Do not prematurely build the entire project before the Stage 1 plan is reviewed.

### Stage 1 stop condition

At the end of Stage 1, present the implementation plan to the human and wait for approval.

This is the main required human review gate.

---

## STAGE 2 — autonomous implementation

After the human approves the Stage 1 plan, proceed through implementation with **minimal human intervention**.

The agent should continue until the agreed v0.1 scope is substantially complete.

Do not stop for routine questions that can be resolved by:
- reading documentation;
- running experiments;
- choosing a reasonable default;
- documenting the decision;
- implementing the best defensible option.

### Stage 2 expected sequence

A suggested vertical-slice order:

#### 2.1 Core/domain foundation
- typed schemas;
- `WeatherDataset`;
- location models;
- provider protocol;
- artifact/manifest models;
- EPW parser/writer/validator;
- QC framework.

#### 2.2 First retrieval vertical slice
Implement one provider end-to-end:

```text
geocode/location
-> discover
-> plan
-> fetch
-> WeatherDataset
-> EPW
-> manifest/QC
```

#### 2.3 Expand providers
Add the remaining practical providers.

#### 2.4 Spatial/batch behavior
- point lists;
- bbox grids;
- GeoJSON polygon grids;
- deduplication;
- resolution warnings;
- artifact bundles.

#### 2.5 REST service
- discovery/planning endpoints;
- jobs;
- artifacts;
- errors;
- credentials/config integration.

#### 2.6 Future weather
Implement two methodologically distinct future-weather approaches.

Support:
- typical;
- extreme;
- ensemble;
- experimental sampled architecture.

#### 2.7 MCP
Implement the MCP adapter over the already-working service layer.

#### 2.8 CLI and examples
Keep lightweight.

#### 2.9 Hardening
- tests;
- docs;
- packaging;
- CI;
- examples;
- provider limitations;
- reproducibility checks.

---

# 31. Human intervention rules during Stage 2

The agent should **not** stop for human approval for ordinary implementation decisions.

The following do **not** require human intervention:

- choosing a reasonable internal class name;
- choosing pandas/xarray boundaries within stated architecture;
- fixing provider parsing;
- adding retries/backoff;
- adding tests;
- adjusting cache layout;
- selecting straightforward libraries with compatible licenses;
- adapting API request shapes to provider changes;
- choosing sensible default timeout/retry values;
- adding provider-specific warnings;
- refactoring internally while preserving public design intent;
- dropping a blocked provider after serious documented attempts;
- changing milestone order to unblock work;
- fixing bugs;
- improving docs.

Human intervention **is required** when any of the following occurs:

1. **Major product-scope contradiction**
   - implementation would require violating a core product requirement;
   - a requested feature is scientifically or technically impossible under the chosen model.

2. **License conflict**
   - a key implementation appears to require GPL/AGPL or another materially restrictive license contrary to project policy;
   - code reuse legality is unclear and copying would be required.

3. **Credential/access barrier requiring the human**
   - API access requires a key/account/approval that the agent cannot create or obtain;
   - continue with other work first, and only request the credential if it is materially needed to proceed.

4. **Irreversible external action**
   - publishing to PyPI;
   - changing organization/repository ownership;
   - purchasing services;
   - accepting paid terms;
   - creating external accounts with legal/financial consequences.

5. **Security incident**
   - real secret appears committed;
   - credential leakage;
   - suspicious third-party dependency/security issue requiring owner action.

6. **Destructive git action**
   - a situation appears to require force push/history rewrite/deleting collaborator work.

7. **Scientific ambiguity that materially changes claimed output semantics**
   - for example, two competing future-weather definitions would produce materially different public claims and there is no defensible default consistent with this document.

8. **Public API break after a stable interface has already been explicitly approved**
   - if a broad breaking change appears necessary, document and ask.

Otherwise:
- decide;
- implement;
- document;
- continue.

---

# 32. MVP checkpoints during Stage 2

Short checkpoints are allowed, but they must not become mandatory approval gates unless the human explicitly asks.

Useful optional checkpoints include:

## MVP A
One provider:

```text
discover -> plan -> fetch -> EPW
```

## MVP B
Several providers + spatial/batch retrieval.

## MVP C
First future-weather method.

The human may test these and provide feedback.

If the human does not respond or does not request changes, continue with the approved Stage 2 plan.

---

# 33. Failure-handling policy

The agent is expected to make pragmatic progress.

For a provider or method that fails:

1. reproduce the issue;
2. inspect current docs;
3. try at least a few reasonable approaches;
4. confirm whether the problem is:
   - authentication;
   - licensing;
   - anti-bot behavior;
   - API deprecation;
   - inaccessible endpoint;
   - unavailable variables;
   - dependency incompatibility;
   - geospatial coverage;
   - other;
5. document findings;
6. implement a fallback/provider alternative if practical;
7. defer/drop the blocked integration rather than halting the project indefinitely.

The same principle applies to future-weather methods.

---

# 34. Scientific transparency rules

OpenEPW must not oversell the meaning of generated weather.

Examples:

- A target-year 2050 future EPW may represent a climate window around 2050, not literal forecast weather for 2050.
- A typical future profile is not necessarily a formally standardized TMY unless the method actually implements such a standard.
- An extreme future profile is not universally defined; expose the method and parameters.
- A hybrid EPW should identify variable provenance.
- A fine requested spatial grid does not increase the native resolution of the source dataset.
- Reanalysis is not station observation.
- Satellite/model-derived radiation is not necessarily measured radiation.

These distinctions should appear in manifests/docs and warnings where relevant.

---

# 35. Definition of v0.1 complete

v0.1 is complete when the project substantially provides:

## Core
- installable `openepw` Python package;
- typed public domain models;
- EPW parser/writer/validator;
- QC/provenance;
- configuration/credentials system.

## Retrieval
- geocoding support;
- `discover`;
- `plan`;
- `fetch/execute`;
- single and multi-location requests;
- bbox/GeoJSON sampling;
- source-cell deduplication;
- resolution warnings;
- existing AMY/TMY/TMYx/other product retrieval where providers support them;
- at least several practical provider integrations, targeting four or more unless genuinely blocked.

## Hybrid/provenance
- explicit hybrid/fallback architecture;
- per-variable provenance when mixing occurs;
- request/plan/manifest artifacts.

## Future
- `generate_future`;
- at least two methodologically distinct future-weather approaches;
- typical profile;
- extreme profile;
- ensemble output;
- architecture/experimental path for sampled output.

## Service
- REST API;
- lightweight async job system;
- artifact access.

## MCP
- MCP server over the service/domain layer;
- compact agent-oriented tool surface;
- generated artifact/resource handling.

## Delivery
- lightweight CLI;
- examples;
- tests;
- CI;
- docs;
- MIT license;
- public-repo readiness.

A provider or noncritical feature may be deferred when repeated documented attempts show a genuine external blocker.

---

# 36. Stage 1 deliverable expected from the agent

Before broad implementation, produce a concise but concrete plan containing:

1. validated provider feasibility table;
2. current auth requirements;
3. current provider years/resolution/important variables;
4. licensing/reuse findings;
5. chosen future-weather method A;
6. chosen future-weather method B;
7. proposed package architecture;
8. proposed core schemas;
9. proposed REST routes;
10. proposed MCP tools;
11. proposed job/artifact model;
12. milestone order;
13. identified blockers;
14. any requested human credential/input.

Then request approval to begin Stage 2.

Do not ask dozens of design questions. This document already defines the product direction. Only ask when a Stage 2 human-intervention condition is met.

---

# 37. Non-goals / avoid overengineering

Do not spend v0.1 effort on:

- a standalone frontend;
- a complex interactive CLI;
- Kubernetes/cloud orchestration;
- distributed microservices;
- a sophisticated arbitrary stochastic weather generator as a blocker;
- inventing a new historical TMY methodology;
- inventing a new historical XMY methodology;
- unnecessary database infrastructure;
- premature plugin marketplaces;
- tightly coupling the package to EnergyAtlas;
- hiding scientific assumptions behind a single opaque "best weather" button.

---

# 38. Desired project character

OpenEPW should feel like a serious research/software infrastructure component:

- simple Python entry points;
- transparent scientific metadata;
- clean provider abstraction;
- reproducible requests;
- practical EPW output;
- useful to both humans and agents;
- easy to self-host;
- not dependent on one commercial service;
- not dependent on one frontend;
- extensible without becoming framework-heavy.

When forced to choose between:
- clever abstraction and transparent behavior;
- prefer transparent behavior.

When forced to choose between:
- broad provider count and reliable/provenance-rich integrations;
- prefer reliable integrations, but continue attempting breadth pragmatically.

When forced to choose between:
- blocking on perfection and delivering a defensible implementation;
- deliver the defensible implementation and document the limitation.
