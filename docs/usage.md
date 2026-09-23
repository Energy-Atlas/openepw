# Usage and reproducible workflows

Install from source with `pip install .` and optional `[api,mcp,climate,cds]` extras.
This repository has not published v0.1 to PyPI. Examples call the same Python service.

## Requests

[examples/request.json](../examples/request.json) is a small Open-Meteo request.
Use years for actual meteorological years, or inclusive start/end dates for partial
periods. Published TMY products cannot also specify actual years. Provider ordering
is explicit (`providers=["nsrdb", "openmeteo"]`); discovery retains alternatives,
but execution never silently reselects a different provider after failure.

Actual-year requests preserve February 29 by default. Set `skip_feb_29=True` when
the consuming software requires a 365-day array for every year:

```python
request = WeatherRequest(
    locations=Location(
        lat=42.45,
        lon=-76.50,
        standard_offset_minutes=-300,
    ),
    product="amy",
    years=[2024],
    providers=["nsrdb"],
    skip_feb_29=True,
)
```

The option is limited to actual-year `years` requests. It removes the 24 local
February 29 intervals, retains the original source-year labels, marks the EPW as
`OPENEPW_CALENDAR=noleap`, and records the policy and removal count in the manifest.
It does not permit any other missing day.

A list of Locations makes a batch. BoundingBox(west,south,east,north) and
PolygonQuery(type="Polygon", coordinates=[exterior, holes...]) use SamplingSpec.
Spacing/offsets are kilometers, measured from the bounding region's southwest
origin; longitude spacing varies with latitude. Poles and dateline-crossing polygon
rings are rejected (split polygons first); dateline-crossing boxes are supported.
The bounding sampling grid must fit max_locations, even if a small polygon covers
only part of it.

To request more than one dataset for every point, use `dataset_selections` with
provider/dataset pairs. Omit `product_id` to resolve each point's locally ranked
station; a supplied product ID constrains the variant. A missing combination is
reported as `DATASET_UNAVAILABLE` in the plan rather than replaced. Each output
has its own stable `id`; the descriptive EPW `name` is for display/download only.
Without selections, the original single-source or explicit-hybrid behavior remains.

Explicit hybrid example:

```python
from openepw.models import HybridPolicy, Location, WeatherRequest
request = WeatherRequest(
    locations=Location(lat=42.44, lon=-76.50),
    start="2024-01-01", end="2024-01-02",
    providers=["noaa", "openmeteo"],
    hybrid_policy=HybridPolicy(enabled=True, assignments={
        "dry_bulb": "noaa", "dew_point": "noaa", "relative_humidity": "noaa",
        "wind_speed": "noaa", "wind_direction": "noaa", "pressure": "openmeteo",
        "ghi": "openmeteo", "dni": "openmeteo", "dhi": "openmeteo",
    }),
)
```

Inspect station/source distances, elevations and QC before using the result.
Assignments name every desired output variable; unspecified variables remain missing.

## REST

`openepw --env-file .env serve` starts the local API. Set
`OPENEPW_BEARER_TOKEN` before `serve --host 0.0.0.0` for remote mode.

```python
import httpx
client = httpx.Client(base_url="http://127.0.0.1:8000")
request = {"locations": {"lat": 42.44, "lon": -76.5},
           "start": "2024-01-01", "end": "2024-01-02", "providers": ["openmeteo"]}
plan = client.post("/v1/weather/plan", json=request).raise_for_status().json()
job = client.post("/v1/weather/jobs", json={"plan": plan, "idempotency_key": "example-1"}).raise_for_status().json()
status = client.get("/v1/jobs/" + job["id"]).raise_for_status().json()
```

Poll until a terminal state, then read `bundle`. Use POST `/v1/jobs/{id}/cancel`
for cooperative cancellation; an in-flight external request may finish first.
POST `/v1/jobs/{id}/retry` creates a new job for missing outputs after the original
reaches a terminal state; `retry_of` links them and prior successful artifacts stay
on the original job. A completed job with nothing missing returns `NOTHING_TO_RETRY`.
GET `/v1/artifacts/{id}` downloads a verified artifact. POST `/v1/artifacts` accepts
multipart EPW upload and returns the baseline ID for future requests. No request
accepts API keys; configure server runtime credentials. A repeated idempotency key
with a different plan fails explicitly.

## MCP

Configure your MCP client to launch `openepw mcp` using the installed environment.
Provide runtime environment variables or explicit `--env-file` before the command.
`weather_plan` returns compact plans; `weather_fetch` submits a durable job;
`weather_inspect` checks the job or returns artifact URI metadata. Future inputs
must use uploaded/registered artifact IDs. `weather://artifacts/{id}` exposes bytes
without dumping hourly rows in tool responses. HTTP transport binds loopback port
8001; remote authenticated deployment is supported through REST in v0.1.

## Cache and storage

The manifest links each output to sources, input hashes, location mapping and QC.
Exact raw responses are retained locally after successful parsing and verified on
replay. Changed credentials do not change scientific cache identity. To force an
independent retrieval, use a new `data_root`; never manually alter cache bytes.
There is no automatic retention policy. Do not publish source caches without
checking their data licenses. A file returned in `bundle.weather` is located at
`config.data_root / artifact.path`.
