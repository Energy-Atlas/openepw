# MCP Stage 3a — weather fetch, batch and export acceptance

Date: 2026-09-25. Branch: `feature/mcp`. Scope: canonical Python service,
stored weather plans, durable local batch jobs, row-level QC/provenance,
compact export and thin REST/CLI access. The final MCP contract belongs to
Stage 4. This stage used offline synthetic data; no Stage 1 collection ran.

## Executed checks

| Check | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/unit -q` | 282 passed, 1 opt-in Stage 1 snapshot test skipped, 2 third-party deprecation warnings |
| `.venv/Scripts/python.exe -m ruff check src tests` | Passed |
| `.venv/Scripts/python.exe -m mypy src/openepw` | Passed for 56 source files |
| `.venv/Scripts/python.exe -m build` | Wheel and sdist built successfully |
| `test_stage3a_acceptance.py` | Actual-year and published-product offline anchors passed |
| `test_noaa_gap_output.py` | Sparse NOAA `warn` and `error` variants passed |

The acceptance anchors create plans, submit jobs by their stored hashes, inspect
checksummed manifest/weather artifacts, and request compact exports. REST tests
submit a stored hash and download the ZIP. CLI tests execute a stored hash. No
ordinary JSON response contains an hourly weather table.

## Anchor outcomes

| Story | Observed outcome |
| --- | --- |
| A: full actual year | One 2024 point, one executable synthetic station selection and one unavailable explicit alternative. The job is `partially_completed`: one EPW with 8,784 rows, one unresolved row, and `simulation_ready=false`. The explicit alternative is retained in the mapping. |
| B: published product batch | Four requested occurrences including a duplicate point and one known exclusion. Three distinct output artifacts came from one verified exact URL task; final rows are three `succeeded` and one `unsupported`. Compact export has four mapping rows and one equivalent weather member. |
| G: sparse NOAA reports | `warn` emits an EPW with field-specific missing sentinels, `MISSING_CRITICAL_VARIABLE` QC and `simulation_ready=false`; `error` emits no EPW and records a failed row. Neither path writes textual `None` or `NaN` to the EPW. |

The output/occurrence identities, selected product, inclusive actual period,
source coordinates, task IDs, artifact IDs and per-variable lineage remain
separate. The manifest counts requested occurrences, output intents, native
tasks, shared tasks, unsupported/unresolved rows and emitted artifacts. A
failed or cancelled row carries no weather artifact. Retry selects only
outputs without a verified successful artifact. Restart preserves a verified
output and retries a checksum-corrupt one.

## Limits and carry-forward

- These synthetic anchors validate flow and accounting, not provider-side
  availability, EPW simulation readiness or a real-client conversation.
- `supported` catalog eligibility still means eligible to attempt retrieval.
  Hourly completeness and required variables are checked after retrieval.
- The original accepted Stage 1 snapshot, annotations and local inventories
  remain unchanged. The merged NSRDB `tdy-2023` display grid is not active
  eligibility evidence. No live provider smoke was needed for this offline
  acceptance; Stage 6 will record bounded live/client results and any skips.
- Compact export is local and explicit. It does not grant redistribution rights
  for OneBuilding or other third-party data. A future baseline can use an EPW
  artifact ID, but Stage 3b must validate its own method and baseline contract.
- Two deprecation warnings originate in the installed FastAPI/Starlette test
  client dependencies. One opt-in test depends on ignored local Stage 1 files.
