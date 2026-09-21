# Web UI acceptance — staged map-first redesign

Status: **implemented and accepted for the local-first, single-user scope** on
2026-09-20. Branch `feature/webui` is preserved; no push, merge or publication was
performed. Earlier backend acceptance remains in [v0.1-acceptance.md](v0.1-acceptance.md).

## Delivered

The active workspace is Explore → Download → Project. A reference-inspired Run
split control gates each transition. Versioned state rejects stale spatial,
discovery and plan responses; upstream edits invalidate dependent working state
without deleting immutable jobs or artifacts. Partial Download success unlocks
Project, and Project can be rerun against one selected validated EPW.

The center is a full-bleed MapLibre terrain globe. Explore alone exposes floating
point/list/bbox/polygon tools and the Python sampler supplies authoritative preview
points, exact counts and execution-limit status. Coverage overlays use attributed
documented metadata with explicit unknown extents; they never imply point/year
availability. Dataset status markers provide text and patterns in addition to
color, with artifact selection from point popovers.

Download supports optional whole-query multi-dataset selection. The planner emits
each feasible dataset × point × period EPW and preserves unavailable combinations
as scoped issues. Imported EPWs must pass parser and annual QC validation before
becoming eligible Project baselines, and are not called simulation-ready merely for
passing that gate. The collapsible inspector uses the bounded
full-artifact response for monthly temperature/precipitation and selectable hourly
heatmaps; 8,760/8,784 calendars, nulls, units, gaps and TMYx source years remain
explicit.

Desktop stage and Agent sidebars keep stable roles and bounded resizable widths.
Narrow screens retain the map and expose both as mutually exclusive drawers with
Escape/focus restoration. The deterministic Agent, panels and header use one action
registry. Reversible edits apply directly until they would invalidate current
downstream work; invalidating edits and jobs require confirmation. History is a
separate immutable job/artifact drawer. System plus all six curated appearances
remain available.

## Deterministic browser acceptance

The offline fixture registers two datasets. One carries complete weather fields;
the other deliberately omits precipitation/DNI and fails at part of a sampled
polygon. It is imported only by the test server. Development and production suites
cover:

- authoritative sample preview, fixed globe/terrain controls and attributed coverage;
- discovery, multiple dataset selections and automatically refreshed planning;
- complete and partial jobs, asynchronous Project advancement and History details;
- EPW selection, monthly/hourly charts, leap-year labeling and manual inspector collapse;
- deterministic Agent confirmation, narrow drawers, keyboard focus and persisted drafts;
- light, dark and monochrome visual checks with Axe serious/critical auditing;
- numeric Explore controls when WebGL is unavailable; and
- MapLibre module-worker loading from production static hosting.

Screenshots and traces stay in ignored `ui/test-results/`. Manual desktop and narrow
checks found no material panel overlap or hidden primary map surface. Browser-only
MapLibre warnings about globe fog/style rebuilding were observed; no console error
remained after correcting the heatmap axes.

## Verification actually run

Windows, Python 3.14.7 and Node 24.21.0 with installed Edge:

| Check | Result |
| --- | --- |
| Full Python offline suite | 98 passed, 15 opt-in live checks skipped; two upstream deprecation warnings |
| Ruff | Passed |
| mypy | Passed, 43 source files |
| UI Prettier, TypeScript and ESLint | Passed |
| Vitest | 50 passed across 12 files |
| Vite production build | Passed |
| Playwright development hosting | 7 passed |
| Playwright FastAPI production hosting | 7 passed |
| Appearance/Axe review | Light, dark and monochrome screenshots; no serious/critical violations |
| Generated contracts | OpenAPI, TypeScript schema and API catalog regenerated without drift |
| Git | Whitespace check passed; branch left unpushed and unmerged |

## Scientific and interface boundaries

- Python owns sampling, availability, planning, normalization, EPW generation,
  provenance and visualization aggregation.
- Coverage is documented extent. Discovery is observed point availability.
- Missing values remain null/gaps. Uploads must pass annual structural QC, but that
  gate is not simulation-readiness certification.
- Future results are scenario projections, not forecasts; both approved methods
  retain their distinct semantics.
- Browser cancellation stops local waiting only. Server cancellation is separate.
- Provider credentials remain outside requests, plans, browser storage and reports.

## Remaining limits

- The initial JavaScript bundles remain large; code splitting is a follow-up.
- Map styles/tiles/terrain have independent network availability and licensing.
- Safari, Firefox and physical mobile devices are not accepted here; the automated
  suite uses installed Edge on Windows.
- Coverage catalog entries are deliberately sparse and only assert extents supported
  by provider documentation.
- The inspector displays one active artifact at a time; side-by-side comparison is
  not implemented.
- The Agent is scripted, not model-backed natural language.
- Multi-user hosting, repository extraction and package publication remain out of scope.

Operating guidance: [webui.md](../webui.md). Design contract:
[map-first staged UI](../superpowers/specs/2026-09-20-webui-workflow-redesign.md).
Execution record: [webui-ledger.md](webui-ledger.md).
