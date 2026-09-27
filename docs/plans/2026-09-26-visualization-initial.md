# Initial weather visualization implementation plan

> **For agentic workers:** Use the approved visualization design as the
> contract, write failing tests before each implementation slice, and commit
> at the schema, calculation, interface and documentation boundaries.

**Goal:** Return reproducible, framework-neutral visualization JSON for five
initial weather view families, while advertising the complete planned family
catalog.

**Architecture:** The Python visualization service verifies existing EPW
artifacts, computes bounded prepared data and stores immutable views. MCP and
CLI adapt that same service. No plotting library or frontend is involved.

**Tech stack:** Python 3.11+, pandas, Pydantic, existing ArtifactStore,
FastMCP, argparse, pytest.

**Spec:** [weather visualization contract](../design/2026-09-26-weather-visualization.md).

## Global constraints

- Work on the current `feature/mcp` checkout; preserve other contributors' work.
- Do not modify `.env`, call a live provider, invent source identity or generate
  future weather.
- Preserve Gregorian leap, no-leap, synthetic TMY and EPW sentinel semantics.
- Keep scientific calculations outside MCP, CLI and server imports.
- Cap source count, prepared rows, page size and MCP response bytes.

## Review focus

- NOAA-style missing critical values yield null complete-period statistics,
  with explicit valid/missing coverage and optional observed-only partials.
- The uploaded EPW has unverified year/provider identity; a published TMY is
  labelled reference rather than used as an actual-year trend.
- A future-job output cannot enter visualization preparation during the MCP
  suspension, while existing artifact inspection still works.
- A 2024 Gregorian source keeps February 29 and 8,784 expected hours; an
  explicitly no-leap source keeps its declared 8,760-hour calendar.
- An irregular spatial set stays points; duplicate coordinates and mixed
  periods/sources do not become an invented grid.

## Task 1 — Versioned request/spec schemas and family catalog

Create `src/openepw/visualization/models.py` and `catalog.py`; test with
`tests/unit/test_visualization_contract.py`.

- [ ] Write tests for the initial/planned family catalog, forbidden unknown
  options, variable units and allowed aggregations; verify they fail.
- [ ] Add Pydantic request/spec models and a registry with initial status for
  `time_series`, `annual_series`, `monthly_series`, `histogram`, `spatial`.
  Record every other family from the spec as planned.
- [ ] Run the contract tests and commit `fix(visualization): define json contract`.

## Task 2 — Source inspection and prepared-data core

Create `src/openepw/visualization/engine.py`; add service delegates in
`src/openepw/service.py`; test with synthetic EPWs in
`tests/unit/test_visualization_engine.py`.

- [ ] Write failing tests for checksum-verified source loading, calendar and
  temporal-kind metadata, future-output rejection, and variable missing counts.
- [ ] Write failing analytic tests for hourly paging input, annual/monthly
  mean/sum, histogram edges/counts, spatial point/grid layout, missing/null
  policy and leap/noleap coverage.
- [ ] Implement only those operations. Return typed errors for planned
  families, invalid units, mixed periods and resource limits.
- [ ] Run the core tests and commit `fix(visualization): prepare weather views`.

## Task 3 — Immutable view storage and paging

Create `src/openepw/visualization/store.py`; test with
`tests/unit/test_visualization_store.py`.

- [ ] Write failing tests for deterministic view IDs, restart/replay,
  checksum corruption, offset/limit validation and page metadata.
- [ ] Store canonical result JSON by normalized request plus source hashes,
  using atomic writes in the private data root. Return the first page and
  provide a bounded page API that recovers the spec at offset zero.
- [ ] Run store tests and commit `fix(visualization): persist prepared views`.

## Task 4 — MCP and CLI adapters

Modify `src/openepw/mcp/server.py` and `src/openepw/cli/main.py`; test with
`tests/mcp/test_visualization.py` and `tests/unit/test_visualization_cli.py`.

- [ ] Write failing real-stdio tests for capabilities, describe, prepare,
  paging, unsupported family and future-output suspension. Write a failing
  CLI test that expects JSON for the same prepared view.
- [ ] Register the four tools from the spec and add CLI `visualize` and
  `view-page` commands. Let the Python service perform every calculation.
- [ ] Run interface tests and commit `fix(mcp): expose weather visualization json`.

## Task 5 — Conversation routing, verification and docs

Modify the local harness only where needed to route a clearly requested data
view to these tools, then synchronize active docs and the post-retrieval plan.

- [ ] Write failing harness tests for a simple monthly summary and for a
  planned family returning a useful unsupported answer without retrieval.
- [ ] Add bounded tool/result messages and JSON/spec display in CLI; no chart
  rendering or raw hourly model prompt.
- [ ] Run the full offline suite, Ruff, focused mypy and `git diff --check`.
  Update `ARCHITECTURE.md`, `FEATURES.md`, `docs/mcp/README.md`,
  `docs/harness/README.md`, `docs/limitations.md` and the parent plan.
- [ ] Commit `fix(harness): route visualization requests` and report any
  pre-existing verification limitations.
