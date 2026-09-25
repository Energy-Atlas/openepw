# OpenEPW

Python-first weather discovery, retrieval, EPW conversion and future-weather
creation, with REST and MCP adapters over the same service layer. MIT software;
source weather and climate data keep their own licenses.

**v0.1 implementation is available from this repository.** It has not been
published to PyPI. See [acceptance evidence](docs/validation/v0.1-acceptance.md)
and [limitations](docs/limitations.md) before using generated files in simulations.

## Install

```bash
python -m pip install .
python -m pip install ".[api,mcp,climate,cds,harness]"   # optional interfaces and climate access
```

Python 3.11+. Core imports do not require FastAPI, MCP or xarray. Development:
`python -m pip install -e ".[dev,api,mcp,climate,cds]"`.

## Retrieve weather

```python
import openepw
from openepw import Location, WeatherRequest
from openepw.config import RuntimeConfig

config = RuntimeConfig.load(env_file=".env")  # explicit local credential loading
request = WeatherRequest(
    locations=Location(lat=42.44, lon=-76.50, standard_offset_minutes=-300),
    years=[2024], providers=["openmeteo"], dataset="era5",
)
discovery = openepw.discover(request, config=config)
plan = openepw.plan(request, discovery=discovery, config=config)
print(plan.model_dump_json(indent=2))
bundle = openepw.execute(plan, config=config)
print(bundle.weather, bundle.manifest, bundle.qc)
# Convenience: openepw.fetch(request, config=config)
```

Artifact paths are relative to `config.data_root` (default `.local/openepw`).
Each bundle contains EPW files, request, plan, provenance manifest and QC reports.
Partial batch failures are reported in `bundle.issues`; inspect them even when
some files were produced. A syntactically valid EPW is not certified simulation-ready.

Geocoding is separate: `openepw.geocode("Ithaca")` returns named candidates.
Choose a location explicitly. Standard time defaults to UTC; specify a fixed
standard offset for local output. No DST conversion or automatic timezone guess.

Published products use `product="tmy"` (PVGIS/NSRDB), or `product="tmyx"` with a
OneBuilding `product_id`. Do not supply actual years with a published product.
No historical TMY/XMY synthesis is implemented.

## Future weather

```python
future = openepw.generate_future(
    baseline="baseline.epw", target_year=2050,
    reference_period=(1985, 2014), climate_scenario="ssp245",
    method="morph", profile="typical", config=config,
)
```

- `morph`: independent monthly CMIP6 shift/stretch of the baseline sequence.
  Default ACCESS-CM2/r1i1p1f1; full seven-variable availability is checked.
  `2050` means 2036–2065. Supply a defensible reference climate period.
  Typical, coherent model/member ensembles and ranked annual warming sensitivity
  profiles are supported. Explicit, provenance-bearing local signal JSON is also
  supported via `signals=...`; see [signal format](docs/methods/signals.md).
- `climate_profile`: selects coherent whole years from the Argonne WRF/CCSM4
  archive at published U.S. PUMA centroids. Use `climate_scenario="rcp85"` or
  `"rcp45"`; target 2050 resolves to 2045–2054, 2090 to 2085–2094.
  Typical medoid, hot/cold shock or persistence, and ten-year temporal ensembles
  are available. The input baseline supplies site/comparison identity; it is not
  morphed. Native 365-day calendars and source-year labels are retained explicitly.

These are climate-window scenarios, not forecasts or standardized future TMYs.
No SSP/RCP equivalence is invented. CMIP6 planning estimates a conservative decoded
byte budget (default 3 GB per plan); larger ensembles need an explicit runtime
budget. Data are cached locally. [Methods and assumptions](docs/methods/future-weather.md).

## CLI and services

```bash
openepw geocode Ithaca
openepw --env-file .env plan examples/request.json --output plan.json
openepw --env-file .env execute plan.json --output bundle.json
openepw inspect path/to/weather.epw
openepw serve                        # REST on 127.0.0.1:8000
openepw mcp                          # MCP stdio
openepw mcp --transport streamable-http  # loopback HTTP, port 8001
```

REST exposes discovery/planning, durable SQLite jobs, cancellation, bounded EPW
uploads and verified artifact downloads. Remote REST requires `OPENEPW_BEARER_TOKEN`.
Use one server process per data root. MCP exposes bounded availability, plan,
job, baseline, artifact and export tools with `weather://artifacts/{id}` resources;
future tool inputs use uploaded or fetched artifact IDs. The optional
`openepw-agent` harness runs against these same tools. The [Windows local pilot](docs/validation/mcp-stage-6-acceptance.md)
used the real MCP Python SDK stdio client, synthetic end-to-end journeys and
bounded Open-Meteo/OneBuilding retrieval. Streamable MCP is loopback-only in
v0.1. [MCP setup](docs/mcp/README.md) and [agent setup](docs/harness/README.md).

## Providers and constraints

Six adapters: Open-Meteo, PVGIS, OneBuilding, NOAA ISD, NSRDB/NLR and optional CDS.
Live acceptance includes actual data from all six; coverage is source-dependent.
NOAA lacks solar/station pressure; CDS currently exports GHI without DNI/DHI.
Open-Meteo's free hosted service is noncommercial. OneBuilding redistribution
permission remains unverified: local retrieval is supported, mirroring is not.
See the [provider matrix](docs/providers/README.md).

For bbox/polygon grids, source deduplication, explicit hybrids and reproducible
jobs, see [examples](examples/) and [architecture](ARCHITECTURE.md). Source resolution
is never increased by requesting a denser grid.

## Verify

```bash
python -m pytest
python -m ruff check .
python -m mypy
python -m build
```

Live tests are opt-in; ordinary tests do not need credentials or network.
[Contributing](CONTRIBUTING.md), [features](FEATURES.md), [roadmap](ROADMAP.md),
[execution record](docs/validation/stage-2-ledger.md), [handoff](docs/20260920-openepw-brief.md).
