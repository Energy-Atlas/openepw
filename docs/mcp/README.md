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
`baseline_register_path` to import an EPW beneath that resolved directory.
Without it, path registration is denied. `baseline_upload` is the portable
route: a client reads the file, base64 encodes it outside model context, and
calls the tool directly. The decoded size limit is 5 MB. REST multipart upload
and CLI `register-baseline` are alternatives when a host cannot send bytes.
Never paste EPW bytes into a model prompt.

## Tools and results

| Journey | Tools | Result to retain |
| --- | --- | --- |
| Geography and choices | `weather_geocode`, `weather_assess`, `weather_discover` | Explicit location candidate; occurrence-level reasons and evidence date |
| Planning | `weather_plan`, `future_plan`, `plan_inspect` | Immutable `plan_hash`, selected/output rows, baseline origin, warnings and estimated calls |
| Baseline import | `baseline_upload`, `baseline_register_path` | Checksummed `artifact_id`, row count and input QC |
| Execution | `weather_submit`, `future_submit` | Durable `job_id`; both require a stored `plan_hash` |
| Progress | `job_inspect`, `job_cancel`, `job_retry_failed` | State, counts, completed output IDs, issue codes and artifact IDs |
| Results | `artifact_inspect`, `weather_export_compact` | Checksum, media type, size, QC/manifest summary and resource URI |

`weather_fetch`, `weather_inspect` and `weather_generate_future` remain
v0.1 compatibility aliases for inline submission/inspection. New clients
should use the stored plan tools. Normal results are structured JSON capped at
80 KB; plans and job summaries page or truncate at 50 rows. An oversized
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
hourly arrays. A catalog `supported` answer means eligible to try retrieval;
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
4. For future morphing, call `baseline_upload` or reuse the weather artifact
   ID, then `future_plan` with explicit scenario/reference/climate windows.
   Submit its hash with `future_submit`.
5. Call `weather_export_compact` explicitly for a completed weather job if
   a ZIP mapping is needed. Export does not grant redistribution rights.
