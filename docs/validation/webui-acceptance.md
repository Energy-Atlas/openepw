# Web UI acceptance — staged map-first redesign

Status: **core workflow implemented and accepted for the local-first, single-user
scope** on 2026-09-20; a spec-conformance review on 2026-09-21 found gaps that remain
open (see [Unimplemented spec items](#unimplemented-spec-items)). Branch
`feature/webui` is pushed but not merged; no publication was performed. Earlier backend acceptance remains in [v0.1-acceptance.md](v0.1-acceptance.md).

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
polygon. It is imported only by the test server. Since 2026-09-21 the browser suite
is three tests against development hosting, one of which also runs against
production hosting:

- offline map rendering with every external host stubbed, and evaluated MapLibre
  module-worker execution (development and production);
- authoritative sample preview, fixed globe/terrain controls, attributed coverage,
  discovery, multi-dataset selection, Agent confirmation, a completed Download,
  asynchronous Project advancement and a completed Project job using synthetic local
  signals, monthly/hourly charts, leap-year labeling, inspector collapse and History; and
- light, dark and monochrome screenshots with Axe serious/critical auditing, narrow
  stage selection, drawers and focus restoration, persisted drafts without job
  submission, and numeric Explore controls when WebGL is unavailable.

Partial-source jobs are verified over REST against the same fixture app
(`tests/unit/test_ui_fixture_jobs.py`). Preview request counting, failed-table
explicit retry behavior, partial-job display, reload reconciliation, baseline
eligibility, per-plan submit keys, confirmation scope and narrow-layout behavior
are Vitest tests.

Screenshots and traces stay in ignored `ui/test-results/`. Manual desktop and narrow
checks found no material panel overlap or hidden primary map surface. Browser-only
MapLibre warnings about globe fog/style rebuilding were observed; no console error
remained after correcting the heatmap axes.

## Verification actually run

Latest run, 2026-09-21, Windows, Python 3.14.7 and Node 24.21.0 with installed Edge:

| Check | Result |
| --- | --- |
| Full Python offline suite | 105 passed, 15 opt-in live checks skipped |
| Ruff and mypy | Passed; mypy 43 source files |
| UI TypeScript and ESLint | Passed |
| UI Prettier | Passed with `--end-of-line auto`; the repo-wide check flags only CRLF line endings on this Windows checkout |
| Vitest | 128 passed across 25 files |
| Vite production build | Passed |
| Playwright development hosting | 3 passed |
| Playwright FastAPI production hosting | 1 passed (`@production` worker smoke) |
| Generated contracts | OpenAPI and TypeScript schema regenerated for job `kind` and `POST /v1/jobs/{id}/retry`; no drift |
| Manual visual check | Desktop light/dark and 700 px narrow screenshots of Explore, Download confirmation, running progress, Project inspector, table and History against a delayed fixture |

The 2026-09-20 acceptance ran the earlier ten-test browser suite (development and
production) with 98 Python and 50 Vitest tests; see the ledger.

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

## Unimplemented spec items

The 2026-09-21 conformance review against the
[redesign spec](../superpowers/specs/2026-09-20-webui-workflow-redesign.md) listed
gaps; all were implemented on 2026-09-21 (see the ledger). No listed redesign-spec
item remains open. Known modelling limit: the UI's longitude-based standard time can
differ from a site's legal zone; it is shown and editable, not looked up.

Operating guidance: [webui.md](../webui.md). Design contract:
[map-first staged UI](../superpowers/specs/2026-09-20-webui-workflow-redesign.md).
Execution record: [webui-ledger.md](webui-ledger.md).
