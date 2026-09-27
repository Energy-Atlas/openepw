# Local MCP client contract

Stage 4 uses the optional `openepw[mcp]` extra and a local stdio server.
The acceptance session used MCP Python SDK 1.30.0 and negotiated protocol
`2025-11-25`. The Python service and artifact store remain authoritative.

## Windows setup

```powershell
.venv/Scripts/python.exe -m pip install -e ".[mcp]"
.venv/Scripts/openepw.exe --data-root C:\path\to\private\openepw-data mcp
```

For a client that starts stdio servers, configure the executable as
`C:\path\to\openepw\.venv\Scripts\openepw.exe` and arguments as
`--data-root C:\path\to\private\openepw-data mcp`. Use only one server
process per data root. Stdio stdout is protocol traffic; diagnostics go to
stderr. Jobs remain in the data root and can be inspected after reconnect.

The optional `mcp --allow-root C:\path\to\inputs` flag allows
`epw_register_path` to import an EPW beneath that resolved directory.
Without it, path registration is denied. `epw_upload` is the portable
route: a client reads the file, base64 encodes it outside model context, and
calls the tool directly. The decoded size limit is 5 MB. REST multipart upload
and CLI `register-baseline` are alternatives when a host cannot send bytes.
Never paste EPW bytes into a model prompt.

## Tools and results

| Journey | Tools | Result to retain |
| --- | --- | --- |
| Geography and choices | `weather_geocode`, `weather_assess`, `weather_discover` | Explicit location candidate; occurrence-level reasons and evidence date |
| Place inputs | `weather_places_interpret`, `weather_places_preview`, `weather_place_set` | Route place text; numbered point preview (top geocoder match per name, ambiguity flagged, unresolved rows kept) with digest; clarification questions and draft for descriptive sets; GeoNames attribution |
| Planning | `weather_plan`, `plan_inspect` | Immutable `plan_hash`, selected/output rows, warnings and estimated calls |
| EPW input | `epw_upload`, `epw_register_path` | Checksummed `artifact_id`, row count and input QC |
| Execution | `weather_submit` | Durable `job_id` from a stored weather plan hash |
| Progress | `job_inspect`, `job_cancel`, `job_retry_failed` | State, counts, completed output IDs, issue codes and artifact IDs |
| Results | `artifact_inspect`, `weather_export_compact` | Checksum, media type, size, QC/manifest summary and resource URI |
| Visualization | `weather_visualization_capabilities`, `weather_data_describe`, `weather_visualize`, `weather_data_page` | Framework-neutral JSON spec, factual summary, stable `view_id` and bounded prepared-data pages |

`weather_fetch` and `weather_inspect` remain v0.1 compatibility aliases for
weather submission and inspection. Future-weather MCP endpoints are temporarily
absent: `future_plan`, `future_submit` and `weather_generate_future` are not
registered. Compatibility requests using `weather_plan(kind="future")`,
`weather_assess(kind="future")`, or retry of an existing future job return
`FEATURE_SUSPENDED`. Existing plans, jobs and artifacts remain readable; this
MCP suspension does not change the Python scientific core or REST API. New
clients should use the stored weather plan tools. Normal results are structured JSON capped at
160 KB; plans and job summaries page or truncate at 50 rows. An oversized
query returns `RESOURCE_LIMIT`, so narrow it. Large EPWs and ZIPs are never
inline tool results.

`weather://artifacts/{artifact_id}` reads checksum-verified bytes under the
configured data root, up to 10 MB. A client may represent these as base64
blob content and may impose a lower host limit. The tested MCP SDK client
could read a full synthetic annual EPW. Inspect metadata/QC before requesting
bulk resource data. An artifact URI is an opaque local identifier, not a path
or authorization token.

Tool execution failures set MCP `isError=true` and carry a safe JSON error
with `code`, `message` and `retryable`. Invalid tool names/arguments are
protocol errors. Ordinary output does not include credentials, local paths or
full-year hourly arrays. A catalog `supported` answer means eligible to try retrieval;
only output QC describes retrieved-weather gaps. Every manifest currently
records `simulation_ready=false`; do not claim simulator certification.

## Example flow

1. Call `weather_assess` or `weather_discover` with an explicit location,
   product and period. If geocoding returns multiple candidates, select one
   before planning.
2. Call `weather_plan`, inspect its `plan_hash`, occurrence rows and
   warnings, then `weather_submit` with that hash.
3. Poll `job_inspect` by job ID. Inspect the emitted weather artifact and its
   manifest/QC IDs. A partial job can retain successful outputs.
4. Call `weather_export_compact` explicitly for a completed weather job if
   a ZIP mapping is needed. Export does not grant redistribution rights.
5. For an existing EPW artifact, call `weather_data_describe` with its ID,
   then `weather_visualize` with explicit artifact IDs, family and variable.
   The result carries a `VisualizationSpec`, first page and stable `view_id`;
   call `weather_data_page` for later rows. `weather_visualization_capabilities`
   distinguishes the five implemented families from planned ones. These tools
   make no provider request and render no chart. See the
   [visualization contract](../design/2026-09-26-weather-visualization.md).

## Place lists and descriptive sets

`weather_places_interpret(text, draft=None)` classifies place text as
`coordinates`, `list`, `single`, `descriptive` or `invalid`. Coordinates are
points only, latitude first; boxes and polygons return `UNSUPPORTED_GEOGRAPHY`
and out-of-range values `INVALID_COORDINATES`. A descriptive set such as "all
cities in America" returns `questions` (region, minimum population, limit) and a
`draft`; pass the draft back with the user's reply until `query` is complete.
Nothing is enumerated before then.

`weather_places_preview(places)` resolves up to 1,000 names or coordinates
without a confirmation step. Each name takes the geocoder's top match; rows with
several matches are `ambiguous` with a `candidate_count`, and names that do not
resolve stay as `unresolved` rows. Rows from an earlier preview can be passed
back unchanged so edits never re-geocode them. `weather_place_set(query)` lists a
clarified set from GeoNames by population. Both return compact rows (the
resolved rows are the request points), issues, attribution and a digest. The
MCP weather request point-list cap is 1,000 to match.
