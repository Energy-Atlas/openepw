# MCP Stage 3b — future baseline and method acceptance

Date: 2026-09-25. Branch: `feature/mcp`. Scope: registered user and fetched
baselines, complete annual preflight, two distinct future methods, stored plans,
member-level jobs, and REST/CLI access. All acceptance fixtures are synthetic;
the local Stage 1 snapshot and `.env` were untouched.

## Executed checks

| Check | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q` | 303 passed, 15 opt-in integration/snapshot tests skipped, 2 third-party deprecation warnings |
| `.venv/Scripts/python.exe -m ruff check src tests` | Passed |
| `.venv/Scripts/python.exe -m mypy src/openepw` | Passed for 56 source files |
| `.venv/Scripts/python.exe -m build` | Wheel and sdist built successfully |
| Stage 3b baseline, plan, execution, adapter and acceptance tests | User/fetched baseline IDs, both methods, partial jobs and negative cases passed |

## Anchor outcomes

| Story | Observed outcome |
| --- | --- |
| User baseline | A complete 8,760-row synthetic annual EPW registered as upload or trusted path is checksummed, given an opaque artifact ID, and accepted for SSP245 morphing over 2036–2065 with explicit 1985–2014 reference. External provider identity remains `input_epw` unless independently linked. |
| Fetched baseline ID | A complete Stage 3a weather job artifact at the same study point is passed directly to future planning. The plan records the exact weather artifact, source output, registered source manifest and QC IDs. Morphing produces a distinct future EPW with input lineage retained. |
| Hourly climate profile | A bounded synthetic ZIP and PUMA table are served through the actual HTTP Range/ETag/CRC path. Ten coherent no-leap annual members for 2045–2054 are available; the RCP8.5 typical selection emits one 8,760-row EPW with OEDI source lineage and the user baseline as comparison identity. A distant site is rejected. |
| Missing baseline values | A gapped NOAA Stage 3a sentinel output and synthetic missing/short annual EPWs fail before future planning with typed QC errors. Valid row count or EPW syntax alone does not pass. |
| Method and period contrasts | Morphing rejects RCP8.5; climate-profile selection rejects SSP245 and unsupported geography/window. An allowed pinned CMIP6 model-license field still leaves an unverified reference/climate window `unknown`; original store terms stay separate. |

REST accepts a bounded EPW upload, future planning by artifact ID and future job
submission by stored plan hash. It rejects a raw local path. CLI registers a
trusted path and executes a stored future hash. Normal JSON responses contain
artifact IDs and summaries, not hourly weather tables. Jobs persist individual
member outputs: one invalid member can fail while another succeeds, cancellation
keeps completed artifacts, restart verifies checksums, and retry selects only
unproduced output IDs. Legacy future plans without `BaselineRef` remain readable.

## Limits and Stage 4 handoff

- These are offline synthetic acceptance results. The earlier v0.1 live method
  checks remain separate evidence; Stage 3b did not repeat provider calls or
  consume billable API budget. No provider availability or simulation readiness
  is inferred from the fixtures.
- CMIP6 effective model licenses, original store terms and requested climate
  windows are distinct. A model-license match does not establish complete
  monthly data for a requested window; source decoding still checks that data.
- The PUMA archive path uses only its published RCP scenarios and two exact
  windows. Its user baseline is a comparison/site identity, not the hourly
  sequence transformed into the future output.
- `simulation_ready=false` remains in every manifest. Two warnings in the unit
  run arise from installed FastAPI/Starlette test-client dependencies; the one
  skipped test requires ignored local Stage 1 snapshots.
- Stage 4 should expose the same plan, job, baseline, manifest and QC IDs with
  bounded MCP results. It must not turn unknown catalog evidence into positive
  future-window or geographic availability.
