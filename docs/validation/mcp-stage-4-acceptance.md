# MCP Stage 4 — local stdio contract acceptance

Date: 2026-09-25. Branch: `feature/mcp`. Scope: structured local MCP guidance,
stored plan hashes, bounded user baseline registration, durable jobs, compact
inspection/export and checksum-verified resources. Stage 1 snapshots and
`.env` were not changed or read. All tests used synthetic data.

## Executed checks

| Check | Observed result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q` | 311 passed, 15 opt-in live/snapshot tests skipped, 2 third-party deprecation warnings |
| MCP-focused and Stage 3 regression tests | Real stdio sessions, direct tool calls, baseline and NOAA gap cases passed |
| `.venv/Scripts/python.exe -m ruff check src tests` | Passed |
| `.venv/Scripts/python.exe -m mypy src/openepw` | Passed for 56 source files |
| `.venv/Scripts/python.exe -m build` | Wheel and sdist built |

The real client was MCP Python SDK 1.30.0 on Windows. It negotiated protocol
`2025-11-25`, listed tool/resource schemas, returned structured results and
`isError=true` for invalid EPW base64, and read a synthetic annual EPW through
`weather://artifacts/{artifact_id}` as a base64 blob. The tested host allowed
that resource size; other hosts may not.

## Observed journeys

| Story | Result |
| --- | --- |
| A — actual-year plan and job | A local synthetic provider produced a stored weather plan hash, durable job, output artifact ID and explicit compact export artifact. Plan inspection preserved the selected candidate and output identity. This was an offline one-day fixture, not a new Ithaca live-provider acceptance. |
| C — both future baseline paths | In one real stdio session, the client uploaded a complete 8,760-row user EPW and separately referenced a fetched weather artifact by ID with verified manifest/QC companions. Both planned and completed SSP245 morph jobs. Baseline origin stayed distinct. |
| G — NOAA gap | Under `warn`, the sentinel-bearing EPW remained linked to manifest `simulation_ready=false` and `MISSING_CRITICAL_VARIABLE` QC. Under `error`, the manifest row failed and no EPW was emitted. |
| Invalid/access cases | Bad base64 returned a typed tool error. An unallowlisted path was denied. Submitted plan hashes were checked against kind and stored plan integrity; artifact reads used opaque IDs and checksums. |

Stage 3a's separate acceptance covers the full duplicate OneBuilding batch and
partial outcome mapping. The Stage 4 adapter exposes those rows through
`weather_plan`, `plan_inspect` and `job_inspect`; Stage 6 will exercise the
combined story through a launched client.

## Contract and limits

The new tool names and migration aliases are documented in
[the client contract](../mcp/README.md). Normal results cap at 80 KB; occurrence
and job summaries show up to 50 rows, uploads cap at 5 MB decoded and resource
reads cap at 10 MB. Error envelopes carry a safe code/message/retryability and
never echo tool arguments. The protocol fixture confirms that SDK 1.30 requires
typed return annotations for structured result fields. Its v1 SDK negotiated a
newer protocol than the Stage 4 plan's 2025-06-18 reference; this was a wire
observation, not a change in weather semantics.

The catalog map and CMIP6 license-scope research are not promoted into service
eligibility. A supported result still means only that retrieval may be tried.
No live provider or billable model calls were made in Stage 4; all live matrix
cells remain for the bounded Stage 5/6 checks. No simulator run, human session,
remote MCP auth or other desktop client was tested.
