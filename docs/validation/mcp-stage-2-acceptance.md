# MCP Stage 2 — local availability acceptance

Date: 2026-09-24. Branch: `feature/mcp`. Scope: shared local catalog,
eligibility, recommendations, and Python/REST/CLI access. The existing MCP
`weather_discover` exposes the shared assessment; the final MCP tool contract
belongs to Stage 4. This is separate from the v0.1 Stage 2 acceptance.

## Verification performed

| Check | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/unit -q` | 213 passed, 1 opt-in skipped, 2 third-party deprecation warnings, 45.28 s |
| `OPENEPW_TEST_STAGE1_SNAPSHOT=1` on `test_original_local_snapshot_counts` | 1 passed, 9.23 s; reads preserved ignored Stage 1 snapshots |
| `.venv/Scripts/python.exe -m ruff check src tests scripts/mcp_research` | All checks passed |
| `.venv/Scripts/python.exe -m mypy src/openepw` | No issues in 51 source files |
| `.venv/Scripts/python.exe -m build` | Wheel and sdist built successfully |
| Editable local install; `openepw catalog import --from .local/mcp-availability` | Offline import and activation succeeded: 38 evidence sources, 22,301 products, 55,897 sites, 48,315 entries, 61 accepted review records |
| Local `openepw availability` NOAA 2024 point query | One occurrence, eight bounded options (five supported, three unknown), active snapshot reference; no provider weather request |

The wheel contains the availability code and the small accepted OneBuilding
review registry. It does **not** contain the raw inventories, normalized
`analysis.json`, source weather, local SQLite catalog, or credentials. The
original ignored `.local/mcp-availability/` files remain in place. Stage 1
`collect` was not run. The installed environment initially contained an older
non-editable `openepw` copy; it was replaced with a local editable install before
the CLI smoke test.

The opt-in test verified the source checksum pins and previously accepted Stage 1
counts: 154,841 NOAA station/year rows; 56 reviewed metadata matches, three
approximate localities, two name/code conflicts; 636 coherent CMIP6 seven-variable
combinations; and 2,368 OEDI sites with both ten-year scenario windows. Those
counts describe metadata membership, not downloaded weather quality.

## Contract checks

- Catalog generations stage and activate atomically; failed imports/refreshes
  leave the last good generation readable. A request reads one generation.
- Per-occurrence assessments preserve duplicate input points. Candidate identity
  stays provisional until the native source identity is verified.
- NOAA listed years remain sparse. A station operating span and monthly report
  counts do not prove missing years or complete hours.
- TMY source reference years and selected months are distinct from actual-year
  weather. OEDI future membership requires scenario/site/year and archive ETag;
  CMIP6 coherence does not certify a requested climate window.
- Stale or incomplete evidence is unknown unless an independent adapter
  incompatibility excludes the option. Access requirements and service health
  remain separate from scientific eligibility.
- Accepted OneBuilding annotations retain exact source-checksum pins. Changed
  relevant source bytes invalidate reviewed coordinate authority; approximate
  localities and name/code conflicts are not silently promoted.
- The REST, CLI and existing MCP discovery tests compare shared snapshot,
  eligibility and occurrence facts. Normal output is capped at 50 ranked options
  per occurrence with an explicit truncation issue.

## Limits of this acceptance

The default tests are synthetic and offline. The local snapshot import is an
opt-in read of already captured metadata. No new live metadata call, hourly
weather retrieval, EPW generation, simulator run, or weather QC was performed
for MCP Stage 2. `supported` means eligible to attempt retrieval; it is not
simulation-ready weather. OneBuilding redistribution and EPW-coordinate authority
remain unresolved. Automatic refresh normalizes only the supported JSON metadata
formats; other raw formats retain the last good generation and report a failure.
Stage 3a will handle verified fetch equivalence/output mapping, Stage 3b future
execution from a chosen baseline, and Stage 4 the final MCP interface.
