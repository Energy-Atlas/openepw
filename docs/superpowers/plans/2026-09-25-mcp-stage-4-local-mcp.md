# Stage 4 implementation plan: local MCP contract

Status: draft for owner review, 2026-09-25. Implement after Stage 3a/3b service acceptance and review of the coordinated plan.

> **For agentic workers:** Use `superpowers:executing-plans` after approval; test the actual protocol session, then implement and commit coherent increments. Checkboxes are execution tracking, not new human gates.

**Goal:** Let a local MCP client discover weather choices, plan and run historical or future work, manage jobs and inspect artifacts/QC through small understandable tools.

**Architecture:** The stdio MCP server is a thin typed adapter over `WeatherService`, `JobRunner`, `PlanStore` and `ArtifactStore`. Tools exchange compact JSON with IDs; resource templates expose checksum-verified artifact content. No provider, QC or climate algorithm moves into MCP.

**Tech stack:** Existing optional `mcp>=1.20,<2` and FastMCP, Python/Pydantic and pytest. Check the installed SDK and its [v1 documentation](https://py.sdk.modelcontextprotocol.io/v1/) before using a protocol feature. The [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools) and [resources](https://modelcontextprotocol.io/specification/2025-06-18/server/resources) specifications define the intended 2025-era wire semantics. Current SDK 2.x differs; migration is a separate compatibility decision, not an assumption in this plan.

**Spec:** [Coordinated stages](2026-09-25-mcp-remaining-stages.md), [program allocation](../../plans/2026-09-24-production-mcp-program.md), [Stage 3a plan](2026-09-25-mcp-stage-3a-weather-fetch.md), [Stage 3b plan](2026-09-25-mcp-stage-3b-future-weather.md).

## Contract decisions for review

| User action | Proposed tool/resource | Canonical service operation and compact result |
| --- | --- | --- |
| Interpret a place | `weather_geocode` | Candidate points/areas, ambiguity, source and selected coordinates; never silently choose an ambiguous name |
| Compare choices | `weather_assess` / `weather_discover` | Per-occurrence supported/unsupported/unknown, alternatives, source health/access, evidence date and reason |
| Inspect weather or future work | `weather_plan` / `future_plan` | Stored `plan_hash`, selected/alternative choices, batch rows or baseline reference, warnings, estimates |
| Register a local baseline | `baseline_register` | Bounded allowed local path → checksummed artifact ID plus input QC, or explicit path/access error |
| Start work | `weather_submit` / `future_submit` | Existing `plan_hash` + optional idempotency key → durable job ID/state; no implicit provider switch |
| Continue work | `job_inspect`, `job_cancel`, `job_retry_failed` | Counts, per-output/batch outcomes, error codes and artifact IDs; preserve completed work |
| Inspect/export result | `artifact_inspect`, `weather_export_compact` | Role/media type/size/checksum/resource URI, QC and mapping summaries or ZIP artifact ID |
| Read artifact | `weather://artifacts/{artifact_id}` resource | Checksum-verified EPW, manifest, QC or export content subject to host/resource size behavior |

These names are the proposed public contract; confirm them with a real client session and document any rename before Stage 5 builds against them. Keep existing six v0.1 tools as aliases for a documented transition if renaming is feasible without ambiguous semantics; do not claim an approved stable API can be broken routinely. Tool descriptions must state what is evidence, what triggers network retrieval, when an output may have gaps and how to inspect QC. Return service error `code`, safe message, relevant occurrence/output/job IDs and retryability. Follow protocol error versus tool execution error semantics supported by installed SDK; never serialize credential-bearing exceptions.

For local baselines, require a configured allowlist of filesystem roots and a byte cap; canonicalize before reading and register a snapshot in the artifact store. If the host cannot grant such a root, guide the user to Python/CLI or REST upload and then use the artifact ID. Ordinary MCP calls never accept arbitrary raw file paths for execution. Artifact resource reads may exceed a host's budget; normal tool responses return metadata and a URI, and acceptance tests document which clients can read the binary/text resource. Keep EPW hourly data out of ordinary JSON results.

## Shared guardrails

- Carry duplicate requested occurrences and their supported/unknown/unsupported/failure states, exact source task sharing, per-output QC and missing policy unchanged from Stage 3a. A catalog `supported` outcome is only retrieval eligibility.
- Future tools retain registered baseline identity, method/scenario/reference and climate windows, and method-specific site/variable limits from Stage 3b. `future_submit` executes an inspected plan, not an LLM-reconstructed plan.
- Stdio stdout contains protocol messages only; diagnostics go to stderr with redaction. Startup recovers jobs, shutdown closes the runner, and client disconnect leaves durable jobs inspectable on reconnect.
- Restrict resource and tool payloads, input sizes, job polling and bounded geocode/discovery result counts. IDs are validated and file reads are confined to the data root. Preserve the existing single-process-per-data-root model.
- No mandatory hosted service, authentication rollout, or public remote MCP deployment in this stage.

### Task 1: Protocol fixture and schema snapshot

**Files:** Modify `src/openepw/mcp/server.py`; create `tests/mcp/test_contract.py` and a documented contract table under `docs/mcp/`.

- [ ] Build a real SDK client session over stdio using the installed v1 SDK: initialize, list tools/resources, call a harmless tool, read a small synthetic resource and shut down. Pin the observed protocol/SDK version in the acceptance record. Compare SDK behavior with the official specification, especially structured results and `isError`.
- [ ] Write failing schema/description tests for the proposed tool set, bounded result envelopes, typed codes and a redacted error. Add Pydantic request/result adapters and an explicit compatibility map for old v0.1 names. Keep the tool wrappers free of weather science.
- [ ] Run the focused protocol tests; commit `fix(mcp): define typed local tool contract`.

### Task 2: Guidance, geography and plan tools

**Files:** Modify `mcp/server.py` and focused support modules if needed; add `tests/mcp/test_guidance.py`.

- [ ] Write failing MCP-client tests for ambiguous place names, explicit point and area inputs, two duplicate occurrences, supported/unknown/unsupported alternatives, source freshness/access, plan hash and unsupported future method/site. Verify the server does not turn metadata eligibility into weather quality.
- [ ] Route `weather_assess`, `weather_discover`, `weather_plan` and `future_plan` to shared service methods. Return a concise plan summary plus its immutable hash; expose detail only through a bounded inspect operation/resource where needed. Enforce caller selection of ambiguous geography.
- [ ] Run focused tests plus Stage 2 recommendation and Stage 3a/3b planning tests; commit `fix(mcp): expose guided planning`.

### Task 3: Baselines, durable jobs and partial outcomes

**Files:** Modify `mcp/server.py`, CLI/config only where needed; add `tests/mcp/test_jobs.py`.

- [ ] Write failing client-session tests for allowed/disallowed local baseline registration, weather/future submit by `plan_hash`, idempotency, disconnect/reconnect, inspect/cancel/retry and a mixed batch with a shared source and rejected occurrence. Assert job and artifact IDs match the Python service.
- [ ] Implement thin calls to baseline registration, `PlanStore` and `JobRunner`; expose per-output statuses and issue codes. Avoid an implicit execution step in `weather_plan`/`future_plan`. Invalid IDs and access errors return safe structured results.
- [ ] Run focused tests and restart/retry regressions; commit `fix(mcp): manage local weather jobs`.

### Task 4: Artifact inspection, resources and export

**Files:** Modify `mcp/server.py`; add `tests/mcp/test_artifacts.py`.

- [ ] Write failing tests for manifest/QC and EPW resource reads, checksum mismatch, path traversal, oversized ordinary tool response, compact export mapping and resource behavior in a real stdio client. Include the NOAA gap under `warn` (sentinel and QC) and `error` (failed row, no EPW).
- [ ] Bind `artifact_inspect` and compact export to the artifact/job store. Return IDs, size, media type, checksum and bounded QC/mapping summary; keep bulk bytes behind resource reads or explicit local artifact access. Do not present a sentinel-bearing EPW as simulation-ready.
- [ ] Run focused tests and artifact/security regressions; commit `fix(mcp): expose verified artifacts and QC`.

### Task 5: Client setup and Stage 4 acceptance

**Files:** Create `docs/validation/mcp-stage-4-acceptance.md`, client setup examples under `docs/mcp/`; update `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/limitations.md` and relevant CLI help.

- [ ] Exercise stories A, B, C and G from the coordinated plan through a launched stdio client, including invalid schemas, disconnect/reconnect, shutdown, output limits and redaction. Add a small opt-in live smoke only if permitted; record what was actually run.
- [ ] Run full unit/MCP tests, Ruff, mypy and build. Compare generated tool schemas with documentation, record installed SDK/protocol version and client resource limits. Review the whole branch and resolve material findings.
- [ ] Commit `fix(docs): record Stage 4 MCP acceptance`.

## Exit and Stage 5 handoff

Stage 4 exits when a real local MCP client can perform the anchor workflows using inspected plans, durable jobs and checksum-verified artifacts; geography ambiguity, partial batch outcomes, future method limits and NOAA QC remain visible; and setup examples work with the tested SDK version. Stage 5 treats this tool/resource schema as its dependency and does not call private service internals.
