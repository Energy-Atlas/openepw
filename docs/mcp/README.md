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

Tools are grouped by who calls them (`openepw.mcp.access`). Each result's text content is a
short summary for model context with the identifiers needed to continue; `structuredContent`
holds the bounded full data for renderers. Dict parameters publish inlined JSON schemas.
Summaries (`openepw.mcp.summaries`) never put data rows into text; an unknown or failed
summary falls back to a key-only stub (field names plus identifier values) and logs a warning.

| Group | Tools |
| --- | --- |
| Model may call | `weather_places_interpret`, `weather_geocode`, `weather_places_preview`, `weather_place_set`, `weather_locations_review`, `weather_product_offers`, `weather_assess`, `weather_plan`, `plan_inspect`, `job_inspect`, `artifact_inspect`, `weather_data_describe`, `weather_visualization_capabilities`, `weather_visualize` |
| Host on a person's action | `weather_submit`, `job_cancel`, `job_retry_failed`, `weather_export_compact`, `epw_upload`, `epw_register_path`, `weather_data_page` |
| Legacy | `weather_discover` (planning discovers internally), `weather_fetch`, `weather_inspect` |

The openepw chat's own agent mode adds host ask-tools that open forms (`review_location`,
`choose_products`, `ask_text`, `ask_choice`, `request_map_input`, `request_upload`,
`review_plan`). They are not MCP tools, and the chat reaches `weather_locations_review` and
`weather_product_offers` only through them; see the [agent README](../agent/README.md).

`weather_locations_review` returns points with fixed standard-time offsets (estimated from
longitude when missing), a standard-time note and a location key. `weather_product_offers`
returns named downloadable products with catalog availability per location.

Future-weather MCP endpoints are temporarily absent: `future_plan`, `future_submit` and
`weather_generate_future` are not registered. Compatibility requests using
`weather_plan(kind="future")`, `weather_assess(kind="future")`, or retry of an existing future
job return `FEATURE_SUSPENDED`. Existing plans, jobs and artifacts remain readable; this MCP
suspension does not change the Python scientific core or REST API.

`weather://artifacts/{artifact_id}` reads checksum-verified bytes under the
configured data root, up to 10 MB. A client may represent these as base64
blob content and may impose a lower host limit. The tested MCP SDK client
could read a full synthetic annual EPW. Inspect metadata/QC before requesting
bulk resource data. An artifact URI is an opaque local identifier, not a path
or authorization token. Large EPWs and ZIPs are never inline tool results.

## Approval

`weather_submit`, the legacy `weather_fetch` and `job_retry_failed` ask the client to confirm
with the person through MCP elicitation before any provider retrieval. A retry prompt names
the failed job and the original job's plan hash. Validation that cannot start anything runs
before the prompt, so a weather plan with no outputs is refused with `NO_EXECUTABLE_OUTPUTS`
before any confirmation is requested. A client without elicitation support receives
`APPROVAL_REQUIRED`; a declined confirmation returns `APPROVAL_DECLINED`. Jobs record
`approved_via` (`elicitation`, `api` or `chat`): how the original plan's submission was
approved. A retry through REST `/v1/jobs/{id}/retry` or the web chat inherits the original
job's value; a retry through MCP `job_retry_failed` is confirmed again and records
`elicitation`. The legacy console answers the confirmation for plans it was told to submit and
approves the original plan for `/retry` (`StdioMCPPort.approve`).

## Errors and limits

Tool failures, including invalid arguments, set `isError=true` and the text content is a bare
JSON object `{code, message, retryable}` with no prefix. Validation errors (`INVALID_REQUEST`)
add `details: [{loc, msg}]` naming the argument or field, without input values; unexpected
failures (`INTERNAL_ERROR`) add a `correlation_id` that is logged on the server. With MCP SDK
1.30 an unknown tool name also returns `isError=true`, but with the SDK's plain text
`Unknown tool: <name>` rather than JSON. Ordinary output does not include credentials, local
paths or full-year hourly arrays. Results are capped at 160 KB; plans and job summaries page or
truncate at 50 rows; an oversized query returns `RESOURCE_LIMIT`, so narrow it.

The data-root lock is per process: owners within one process (for example the API and its
in-process MCP server) share one job runner. A stdio `openepw mcp` started on a data root that
a running `openepw serve`, or any other process, already holds fails at startup with
`DATA_ROOT_BUSY`; use separate data roots. `openepw mcp` takes the lock on its first client
session and holds it across sessions until the process exits. Future-weather endpoints remain
suspended (`FEATURE_SUSPENDED`). A catalog `supported` answer means eligible to try retrieval;
only output QC describes retrieved-weather gaps. Every manifest currently records
`simulation_ready=false`; do not claim simulator certification.

## Example flow

1. Call `weather_assess` with an explicit location,
   product and period. If geocoding returns multiple candidates, select one
   before planning.
2. Call `weather_locations_review`, get the person's approval, call
   `weather_product_offers` and let them choose, then `weather_plan`; inspect its `plan_hash`,
   rows and warnings. After the person approves, call `weather_submit` with that hash and
   confirm when asked.
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
