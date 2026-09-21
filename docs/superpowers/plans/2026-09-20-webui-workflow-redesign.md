# Map-First Staged UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dock/tab workspace with the approved Explore → Download →
Project cockpit backed by truthful sampling, multi-dataset planning, coverage and
weather-visualization service contracts.

**Architecture:** Python remains canonical for sampling, discovery, planning and
weather summaries. Additive Pydantic/service/REST contracts generate the browser
types. The React app derives stage availability from versioned workflow state and
uses one action registry for header controls, panels and the scripted Agent.

**Tech Stack:** Python 3.11+, Pydantic, FastAPI, pytest; React 19, TypeScript,
Zustand, React Aria, MapLibre, ECharts, Vitest and Playwright.

**Spec:** [approved redesign](../specs/2026-09-20-webui-workflow-redesign.md)

## Global Constraints

- Work on `feature/webui`; use normal human authorship and `fix(topic): description` commits.
- Python/service logic is canonical; the browser must not implement a second sampler or weather transform.
- Preserve existing Python/REST/MCP/CLI behavior when new optional request fields are absent.
- Coverage means attributed documented extent; exact point availability comes only from discovery.
- Missing weather stays null and no parseable EPW is called simulation-ready without supporting QC.
- Keep both future methods distinct and preserve scenario, window, calendar and source-year semantics.
- Keep System plus all six curated appearances; credentials remain server-side or memory-only.
- Production modules contain no fixture success paths and offline tests perform no live provider traffic.

## Review Focus

1. A delayed sampling/discovery/plan response after an upstream edit must never restore stale state (Tasks 4 and 5).
2. Multiple dataset selections with one unavailable point must retain feasible outputs without silently substituting a provider (Tasks 2 and 5).
3. Partial-year, leap-year, noleap and TMYx artifacts must align monthly counts and heatmap cells without inserting data (Tasks 3 and 7).
4. Dense multi-dataset point glyphs and simultaneous coverage overlays must remain inspectable without color-only meaning (Tasks 6 and 7).
5. Reload, duplicate Run, reconnect and Agent submission must preserve one intentional job identity and require the documented confirmations (Tasks 4, 5 and 8).

---

### Task 1: Authoritative spatial preview and documented coverage

**Files:**
- Modify: `src/openepw/models/__init__.py`
- Modify: `src/openepw/planning/spatial.py`
- Modify: `src/openepw/service.py`
- Modify: `src/openepw/api/app.py`
- Create: `src/openepw/coverage.py`
- Test: `tests/unit/test_spatial.py`
- Test: `tests/unit/test_ui_api.py`

**Interfaces:**
- Produces `SpatialPreview`, `CoverageLayer`, `WeatherService.preview_spatial(request)`
  and `WeatherService.coverage(provider=None, product=None, year=None)`.
- Produces `POST /v1/spatial/preview` and `GET /v1/weather/coverage`.
- Later tasks consume the generated OpenAPI types without reimplementing these rules.

- [ ] Add failing spatial tests for a polygon/bbox preview, deterministic truncation,
  exact count, period-scaled execution limit and a too-dense query that returns an
  issue instead of allocating every point. Example assertions:

  ```python
  result = service.preview_spatial(request)
  assert result.total_count == 121
  assert result.locations == service.locations(request)[: result.returned_count]
  assert result.planned_output_count == 242
  assert result.executable is True
  ```

- [ ] Add failing API tests proving coverage entries carry `coverage_basis ==
  "documented"`, attribution/source/observed time, optional GeoJSON or raster
  metadata, and that an unknown extent has neither geometry nor tiles.
- [ ] Run `python -m pytest tests/unit/test_spatial.py tests/unit/test_ui_api.py -q`
  and confirm failures are missing models/routes rather than environment errors.
- [ ] Refactor spatial iteration into one canonical generator/count path. Preview
  collects only the deterministic render prefix, computes the exact count within a
  bounded evaluation budget, reports request/output limits, and leaves `sample()`
  behavior unchanged for existing callers.
- [ ] Add a small curated catalog using provider documentation already recorded in
  `docs/providers/`; begin with truthful global ERA5/Open-Meteo entries and unknown
  shapes for providers without approved geometry. Filtering never upgrades unknown
  coverage into a shape.
- [ ] Add thin service and REST adapters with Pydantic response models and structured
  issues. Run the targeted tests plus `tests/unit/test_service.py`.
- [ ] Commit `fix(api): add spatial preview and coverage contracts`.

### Task 2: Multi-dataset weather planning

**Files:**
- Modify: `src/openepw/models/__init__.py`
- Modify: `src/openepw/service.py`
- Modify: `src/openepw/jobs/worker.py`
- Test: `tests/unit/test_batch.py`
- Test: `tests/unit/test_models.py`
- Test: `tests/unit/test_jobs.py`

**Interfaces:**
- Consumes existing `DiscoveryResult.candidates` and default selection behavior.
- Produces optional `WeatherRequest.dataset_selections: list[DatasetSelection]`,
  `OutputSpec.dataset_selection`, and scoped `WeatherPlan.issues`.
- Absence of `dataset_selections` preserves current single-candidate/hybrid behavior.

- [ ] Add failing model tests for stable selection identity, duplicate rejection and
  backward-compatible request validation.
- [ ] Add failing planning tests with two providers and two points. Assert each
  feasible dataset/location/period has its own output and source task, unavailable
  combinations create scoped issues, and no candidate substitution occurs.
- [ ] Add a failing partial-job test proving one failed selected source retains the
  successful alternative and yields `partially_completed` with accurate totals.
- [ ] Run the three targeted test modules and observe the selection tests fail.
- [ ] Implement exact provider/dataset/product matching. Keep hybrid planning on its
  existing branch; multi-dataset outputs each reference one source task. Extend
  artifact/manifest output mapping with selection identity and keep the 1,000-output
  and 2,000-task limits.
- [ ] Run targeted tests plus provider/service tests and commit
  `fix(planning): support explicit dataset alternatives`.

### Task 3: Full-artifact visualization summaries

**Files:**
- Modify: `src/openepw/preview.py`
- Modify: `src/openepw/service.py`
- Modify: `src/openepw/api/app.py`
- Test: `tests/unit/test_preview.py`
- Test: `tests/unit/test_ui_api.py`

**Interfaces:**
- Produces `WeatherVisualization` through
  `WeatherService.visualize_artifact(id, variables)` and
  `GET /v1/artifacts/{id}/visualization?variables=...`.
- Response contains aligned timestamps, source years, units, nullable series and
  monthly summaries for one to four variables and no more than 8,784 rows.

- [ ] Add failing tests for 8,760/8,784 rows, partial-year input, noleap chronology,
  mixed TMYx source years, missing precipitation/DNI, precipitation/solar sums,
  state means and null JSON values.
- [ ] Add failing API bounds tests for unknown variables, five variables,
  non-weather artifacts and oversized input.
- [ ] Run `python -m pytest tests/unit/test_preview.py tests/unit/test_ui_api.py -q`
  and confirm the new assertions fail.
- [ ] Reuse one internal summary function for paged preview and visualization.
  Partial months compute expected intervals from the requested span, while absent
  heatmap coordinates are represented by the browser from real timestamp gaps.
- [ ] Add the service/route without changing paged preview. Run preview/API/EPW tests
  and commit `fix(api): add full weather visualization summaries`.

### Task 4: Generated contracts and staged workflow state

**Files:**
- Modify: `ui/openapi.json`
- Modify: `ui/src/api/schema.d.ts`
- Modify: `ui/src/api/client.ts`
- Create: `ui/src/app/workflow.ts`
- Modify: `ui/src/app/store.ts`
- Modify: `ui/src/app/actions.ts`
- Test: `ui/src/api/client.test.ts`
- Create: `ui/src/app/workflow.test.ts`
- Modify: `ui/src/app/actions.test.ts`

**Interfaces:**
- Consumes Tasks 1–3 REST contracts.
- Produces `Stage = 'explore' | 'download' | 'project'`, derived `WorkflowStatus`,
  versioned discovery/plan state, selected datasets/coverage, active weather artifact,
  inspector state, and a single typed `AppAction` registry/dispatcher.

- [ ] Regenerate OpenAPI and TypeScript contracts and add failing client tests for
  spatial preview, coverage, visualization and selected-dataset plan payloads.
- [ ] Add failing pure state tests for stage unlocks, partial success, backward
  navigation, upstream invalidation, stale async responses, uploaded-baseline
  eligibility and Project reruns.
- [ ] Add failing action tests for stage-specific Run, idempotent submission,
  confirmation metadata and artifact visualization selection.
- [ ] Run the targeted Vitest files and confirm failures.
- [ ] Implement pure derived state in `workflow.ts`; persist only drafts, current
  view, selected coverage IDs and panel sizes. Track request/discovery/plan versions
  so old promises cannot restore state.
- [ ] Extend the client and dispatcher. `runCurrentStage()` discovers in Explore,
  submits only a current Download plan, and submits only a current Project plan.
  Artifact selection fetches visualization and opens the inspector unless manually
  collapsed. Existing opaque idempotency intent behavior remains.
- [ ] Run targeted tests, typecheck and lint; commit
  `fix(ui): add staged workflow state and actions`.

### Task 5: Explore, Download and Project control surfaces

**Files:**
- Create: `ui/src/features/workflow/StagePanel.tsx`
- Create: `ui/src/features/workflow/ExplorePanel.tsx`
- Create: `ui/src/features/workflow/DownloadPanel.tsx`
- Create: `ui/src/features/workflow/ProjectPanel.tsx`
- Create: `ui/src/features/workflow/RunSplitButton.tsx`
- Modify: `ui/src/features/request/FutureForm.tsx`
- Modify: `ui/src/features/request/PlanReview.tsx`
- Replace: `ui/src/features/request/RequestPanel.tsx`
- Create: `ui/src/features/workflow/StagePanel.test.tsx`

**Interfaces:**
- Consumes derived workflow/actions from Task 4.
- Produces one left panel whose stable container renders stage-specific controls
  and one header Run split control with stage actions/settings.

- [ ] Add failing component tests for provider-free Explore, sampling offsets and
  limit reason, recommended Download selection, multiple toggles, automatic live
  plan, partial job/artifact list, imported EPW validation, single active baseline,
  implemented-only Project controls and visible disabled Run reasons.
- [ ] Implement structured Explore controls and remove provider, hybrid and raw JSON
  from this stage. Debounce authoritative spatial preview after geometry/sampling
  edits; keep the last confirmed points while updating.
- [ ] Implement grouped dataset cards using discovery metadata and selection reasons.
  Auto-select the backend recommendation, apply selections to the whole query and
  debounce plan refresh. Keep unavailable combinations visible.
- [ ] Implement Project as a reorganized existing Future form with active-baseline
  summary and projection-not-forecast copy. Uploads register in Download and select
  the valid artifact.
- [ ] Implement the accessible split button and stage-specific menu. Run component
  tests, typecheck and lint; commit `fix(ui): build staged workflow controls`.

### Task 6: Map-first cockpit, history and Agent

**Files:**
- Replace: `ui/src/app/App.tsx`
- Replace: `ui/src/shell/layout.ts`
- Modify: `ui/src/shell/shell.css`
- Create: `ui/src/shell/panels.ts`
- Create: `ui/src/features/results/HistoryDrawer.tsx`
- Modify: `ui/src/features/agent/AgentPanel.tsx`
- Modify: `ui/src/features/agent/runner.ts`
- Create: `ui/src/app/App.test.tsx`
- Modify: `ui/src/features/agent/runner.test.ts`

**Interfaces:**
- Consumes StagePanel and RunSplitButton from Task 5 and the shared action registry.
- Produces the desktop cockpit and narrow drawer shell; no FlexLayout/tab state is
  part of the active UI.

- [ ] Add failing shell tests for header stepper/lock state, stable left/right roles,
  persisted bounded widths, no center tabs, history drawer, mutually exclusive
  narrow drawers, Escape/focus restore and reduced-transparency fallback classes.
- [ ] Add failing Agent tests for shared action IDs, reversible edits, pending job or
  invalidation confirmation, real result cards and abort-vs-server-cancel copy.
- [ ] Build the full-bleed map shell with overlaid resizable sidebars, center-only
  inspector slot and compact header. Keep API docs/Source/appearance/token settings
  in global menus and server history in its own drawer.
- [ ] Restyle Agent as transcript/tool cards/suggestions/composer while keeping the
  deterministic label and recipes. All mutations dispatch shared actions; no LLM or
  invented language understanding is added.
- [ ] Run shell/agent tests, typecheck, lint and build; commit
  `fix(ui): replace dock tabs with map-first cockpit`.

### Task 7: Globe tools, coverage glyphs and weather inspector

**Files:**
- Modify: `ui/src/features/map/MapView.tsx`
- Modify: `ui/src/features/map/selection.ts`
- Create: `ui/src/features/map/GeometryToolbar.tsx`
- Create: `ui/src/features/map/CoverageControl.tsx`
- Create: `ui/src/features/map/PointGlyph.tsx`
- Create: `ui/src/features/results/WeatherInspector.tsx`
- Replace: `ui/src/features/results/WeatherCharts.tsx`
- Modify: `ui/src/features/map/selection.test.ts`
- Create: `ui/src/features/results/WeatherInspector.test.tsx`

**Interfaces:**
- Consumes spatial preview, coverage, selected datasets and visualization responses.
- Produces Explore-only geometry editing, persistent coverage controls, segmented
  point/artifact popovers and the one-artifact monthly/heatmap inspector.

- [ ] Add failing geometry tests for point/multipoint/bbox/polygon move/delete,
  finish/cancel/undo, measurement text, keyboard alternatives and Explore-only edit
  availability.
- [ ] Add failing coverage/glyph tests for simultaneous layer order/opacity,
  attributed unknown extents, unlimited radial segments, status text/patterns and
  point artifact selection.
- [ ] Add failing inspector tests for monthly temperature/precipitation, default DNI,
  variable switching, 8,784 rows, partial-year gaps, missing variables, TMYx source
  years, manual collapse persistence and Project artifact selection.
- [ ] Keep globe projection and terrain requested without exposing toggles. Adapt the
  current draw logic to the floating SVG toolbar and render only backend preview
  points. Preserve numeric/GeoJSON fallback when MapLibre fails.
- [ ] Render approved vector/raster coverage sources with attribution and stable
  palette ordering. Use accessible HTML marker buttons with conic-gradient segments;
  the popover/legend supplies complete non-color status detail.
- [ ] Build the resizable center-bottom inspector with an ECharts monthly climate
  chart and day-of-year/hour heatmap derived only from returned timestamps/series.
- [ ] Run map/inspector tests, typecheck, lint and build; commit
  `fix(ui): add staged map layers and weather inspector`.

### Task 8: Browser acceptance, docs and handoff

**Files:**
- Modify: `tests/ui_server.py`
- Replace: `ui/e2e/workspace.spec.ts`
- Modify: `docs/webui.md`
- Modify: `ARCHITECTURE.md`
- Modify: `FEATURES.md`
- Modify: `docs/validation/webui-acceptance.md`
- Modify: `docs/validation/webui-ledger.md`

**Interfaces:**
- Consumes all earlier tasks; changes no public runtime contract beyond documenting it.
- Produces deterministic offline acceptance evidence and current operating guidance.

- [ ] Extend the fixture provider with two datasets, one partial location failure,
  documented coverage and complete/missing weather variants. Production code must
  not import it.
- [ ] Browser-test Explore sampling/discovery, multi-dataset Download, partial
  completion, point selection, inspector charts, Project, history, Agent
  confirmation, desktop resize, narrow drawers, keyboard focus and map fallback.
- [ ] Run visual QA at desktop and narrow widths in light, dark and one monochrome
  appearance; capture screenshots outside tracked source and fix material overflow,
  overlap, contrast or focus defects.
- [ ] Regenerate API/schema/catalog artifacts and update architecture, features,
  user guidance and acceptance evidence to distinguish implemented behavior from
  remaining limitations.
- [ ] Run `python -m pytest -q`, Ruff, mypy, UI format check, typecheck, lint, unit
  tests, build and both browser suites. Record environment-only failures exactly.
- [ ] Perform one fresh whole-branch review; fix Critical/Important findings in one
  test-first pass and ledger any rulings/minors.
- [ ] Commit `fix(ui): verify staged weather workspace` and leave the branch clean
  without pushing or merging.

## Planning self-review

- Spec coverage: every product-model, layout, stage, map, inspector, Agent, service,
  state/failure and accessibility section maps to Tasks 1–8.
- Compatibility: Tasks 1–3 are additive; Task 2 preserves legacy planning when
  selections are absent; the old UI is replaced only after Task 4 contracts exist.
- Type consistency: backend names consumed by Tasks 4–7 match the contracts produced
  in Tasks 1–3; `Stage`, `WorkflowStatus` and `AppAction` are defined once in Task 4.
- Placeholder scan: no unresolved implementation decisions remain; unavailable science and
  LLM/hybrid/raw-JSON features remain explicit exclusions from the approved spec.
