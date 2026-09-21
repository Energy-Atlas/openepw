# Web UI execution ledger

Plan: docs/superpowers/plans/2026-09-20-webui.md
Approval: owner confirmed local-first single-user and autonomous execution 2026-09-20.
Start: a5d7f66, feature/webui, clean checkout.

Ruling: preserve owner's existing checkout/branch; no new worktree. User explicitly selected it.
Ruling: use this tracked Windows-native ledger instead of skill shell scratch scripts; durable repository memory takes precedence.
Preflight: Task 1 typed REST -> Tasks 2/3/5/7 client/docs; additive contracts only.
Preflight: Task 2 state/actions -> Tasks 3/4/5/6; one dispatcher, server owns scientific calculations.
Preflight: Task 7 optional /ui hosting -> Task 8 built browser tests; API routes retain their own semantics.
Task 1: implemented; targeted API/preview/jobs suite 9 passed. OpenAPI exports offline. Type checking corrected numeric summary dictionary inference.
Tasks 2–8: pending.

Tasks 2–3: shell/client/manual retrieval implemented. TypeScript, ESLint and 5 unit tests passed. Browser retrieval with a real fixture backend passed discovery, execution, preview and download; compact workflow passed.
Tasks 4–7: first integrated map/future/agent/docs views exist; expanded acceptance in progress.
Ruling: TypeScript 5.9.3 replaces reference 6.0.3 because openapi-typescript 7.13.0 declares a TypeScript 5 peer; no forced dependency install. Cost: fewer new TS6 features, none used.
Ruling: include optional hosting early to test the actual built app rather than wait until final integration. Existing API behavior preserved.
Browser finding: Vite prebundling orphaned MapLibre workers; match reference optimizeDeps exclusion and production worker emission. Missing FlexLayout sourcemap stripped, not a real application source error.
Initial visual check: 1440x950 results screen inspected; dense two-column layout, actual download controls, chart units and QC warning visible.

Tasks 4–7: complete. Optional /ui hosting, generated REST/Python/MCP references, MapLibre terrain/hillshade/buildings/globe, requested/known source distinction, future uploads and real scripted dispatch integrated.
Review: independent read-only reviewer found stale preview after submit, lost source-year mapping, ineffective client cancellation; reproduced each in failing tests and fixed. Also fixed comma-list editing, persisted versioned drafts, guarded/deduplicated pagination, and persisted submission intent hashes for reload/retry reconciliation. Reviewed plans never auto-run after reload; explicit rerun creates a new key.
Acceptance: 77 Python passed / 15 live skipped; Ruff and mypy (42 source files) passed. 14 UI unit tests, typecheck/lint/build passed; 8 development and 8 production Edge browser scenarios passed. Six theme readability checks and Axe serious/critical check passed. Actual screenshot inspected for light/results and dark/map layouts.
Live: fresh empty-cache Open-Meteo 2024-02-14 Ithaca returned 24/24 temperature samples, no bundle issues. Real REST retrieval of 2023 baseline plus ACCESS-CM2 SSP245 2050 morph, preview and artifact download passed using the existing .local/live-cmip cache. This is not a fresh climate-download or all-provider acceptance claim.
Ruling: preserve current branch at delivery; no push/merge/publication. Finish-branch menu is unnecessary because the owner requested autonomous implementation on this branch and the approved plan already says preserve it.

Final acceptance expanded: 10/10 development and 10/10 production browser tests passed, including forced WebGL failure and partial/cancel UI states. Source-year and cancellation regressions remain green; 14 UI unit tests. Final Python suite 77 passed / 15 skipped. Generated artifact binary response now explicitly documented. Wheel/sdist built; core wheel installed without API/MCP/climate extras; archive exclusions checked. Final docs/ADR/roadmap and CI completed. Cross-OS/browser and full ten-output UI ensemble permutations remain documented follow-ups.

Post-delivery report: production map blank despite HTTP 200 worker response. Reproduced against owner's running server: .mjs files were text/plain because Windows MIME registry overrides Python's mapping. Initial production smoke was insufficient: canvas/click tests passed without verifying module worker execution. Static serving now explicitly uses text/javascript for .mjs. Added a forced-Windows-MIME regression and browser assertion that the actual worker imports its shared runtime. Verified real OpenFreeMap tile rendering in a fresh production browser and visually inspected the screenshot, with no page errors. Root now redirects to /ui/ when hosting is enabled; original favicon provided.
Future-plan diagnostics: empty baseline reproduces INVALID_ARTIFACT (400), now intercepted by shared UI dispatch with actionable upload/select guidance. Owner's exact 400 cause remains unconfirmed without its response message; no source availability claim is inferred from access logs.
Validation additionally exposed a SQLite connection leak: transaction contexts committed but did not close handles, intermittently preventing Windows catalog temporary-directory cleanup. Added deterministic closed-connection regression; JobStore now closes each connection after commit/rollback. This preserves transaction/idempotency semantics.

Post-fix verification: 79 Python passed / 15 live skipped; 15 UI unit and 11 production browser tests passed; TypeScript, ESLint, Prettier, Ruff and mypy passed. Production assets rebuilt. Restart the running server and hard-refresh to load these changes.

## Map-first staged redesign

Plan: `docs/superpowers/plans/2026-09-20-webui-workflow-redesign.md`.
Specification: `docs/superpowers/specs/2026-09-20-webui-workflow-redesign.md`.

Implemented canonical spatial preview and documented coverage contracts, optional
whole-query multi-dataset planning, full-artifact visualization, versioned staged
state, Explore/Download/Project controls, Run split action, fixed-role cockpit,
History drawer, deterministic Agent transcript, floating globe tools, coverage
layers, segmented point statuses and the collapsible weather inspector.

Ruling: server-returned sample points are the only rendered execution preview.
Coverage metadata is independently attributed and cannot upgrade unknown extents or
stand in for discovery. Ruling: imported EPWs are eligible baselines after parsing,
but no UI label upgrades them to simulation-ready. Ruling: panel controls, Run and
Agent mutations remain entries in one registry; job starts retain confirmation.

Browser finding: the initial heatmap used value axes, which ECharts rejects for its
Cartesian heatmap renderer. The real browser suite exposed the error; both axes now
use complete day/hour categories while plotted cells still come only from returned
timestamps. Browser finding: failed coverage loading could retrigger on each busy
transition; a one-attempt guard now returns the workspace to Ready and preserves the
error in the Agent transcript.

Acceptance fixture now has complete and sparse datasets plus a deterministic partial
location failure. Development and production scenarios cover staged navigation,
partial success, inspector charts, History, Agent confirmation, responsive drawers,
keyboard focus, appearances/Axe, persisted drafts, WebGL fallback controls and the
MapLibre worker. Full verification results are recorded in webui-acceptance.md.

Final review corrections: debounced preview/planning retries after a busy request;
sample points carry canonical location ids; status/artifact joins are scoped by the
current plan, point and exact dataset/product selection; glyphs encode status as well
as dataset identity; no-leap heatmap ordinals and all-null variables remain explicit;
uploads must pass annual QC; execution limits count dataset × point × period outputs;
and one shared modal focus scope provides trapping, inert background content, Escape
handling and opener restoration. Current-plan reruns, jobs and downstream-invalidating
edits require confirmation. Stable coverage colors follow provider/dataset identity.

## Browser-test simplification handoff — 2026-09-21

Larger stream: stabilize and maintain the map-first web UI after implementation.
Current item: propose a faster, smaller E2E suite; no test simplification has been
implemented or approved yet. The branch is `feature/webui` with a clean working tree
before this note. Recent CI failures were caused by an external-tile route stub that
did not intercept HTTPS requests; `59a481b` corrected it and the subsequent UI CI
run passed. Long failing browser runs, including retries/timeouts, dominated elapsed
time; one incorrect intermediate hypothesis added an avoidable CI cycle.

Proposal for owner review: retain one real-backend Explore → Download → Project and
inspector path; one offline map/network interception check; one responsive/focus/Axe
check; and one production-build worker-loading smoke check. Move preview request
counts/no-retry behavior and partial-success state permutations to existing fast
unit/integration tests with controlled timers. Remove fixed browser sleeps. Run the
full browser set once against development hosting, and only the worker smoke against
production hosting. Keep partial-job behavior covered at an appropriate integration
boundary; do not delete coverage solely to shorten CI. Measure before/after runtime
and preserve evidence that the production module worker executes.

Status: proposal only, awaiting the owner's decision before editing test code or CI.

## Browser-test simplification implemented — 2026-09-21

Owner approved implementation in session on 2026-09-21. Ten browser tests became three:
offline map + module-worker execution (`@production`), the real-backend Explore →
Agent confirmation → multi-dataset Download → Project inspector/history path, and one
appearances/Axe/narrow-drawer focus/draft-reload/WebGL-failure test. The production
script now runs only `--grep @production`. Every non-loopback request is stubbed or
aborted; fixed sleeps were removed. The live-tile check waits for intercepted terrain
tile requests, and it no longer counts the stubbed style (its old `openfreemap.com`
pattern never matched the real `.org` host). Worker evidence is now stronger: the test
evaluates the MapLibre worker's global scope for `registerWorkerSource` and `worker`,
which exist only after the module and its shared runtime execute. A served-but-throwing
`maplibre-gl-shared.mjs` failed the new test; the previous 200/content-type check would
have passed it.

Moved coverage: one-preview-per-query-version with a slow in-flight preview
(`ExplorePanel.test.tsx`, fake timers); partial Download advancing to Project with
explicit history counts and `SOURCE_UNAVAILABLE` (`HistoryDrawer.test.tsx`); and the
sampled polygon partial-source job through the same fixture app over REST
(`tests/unit/test_ui_fixture_jobs.py`, about 6 s). The existing no-retry, busy-deferral,
Refresh sample preview and partial-unlock unit tests stay.

Local measurement (Windows, Edge, one worker): development hosting 10 tests 62.7 s →
3 tests 15.2 s; production hosting 10 tests 43.0 s → 1 test 3.6 s. Also passed:
TypeScript, ESLint, Vitest 14 files/54 tests, Python 100 passed/15 live skipped, Ruff.
Repo-wide `format:check` warns on this Windows checkout's CRLF files; the changed UI
files pass Prettier. CI has not yet run this change.

## Implementation review and fixes — 2026-09-21

Owner requested a progress review, then approved fixing the findings. The review
(spec conformance, correctness audit, docs/CI state) found four correctness bugs, two
small defects, spec deviations and doc drift; the acceptance record now lists the
spec items still unimplemented.

Fixed with regression tests (each confirmed failing without its fix):

- Inspecting a projected EPW replaced the Project baseline, disabling Project Run
  after every projection. Only eligible baselines now change it.
- History and earlier-session weather EPWs could not unlock Project. `WeatherJob`
  now carries `kind`, derived by `JobStore` from the stored plan (including legacy
  rows); weather jobs in History count as eligible baselines. On load the UI
  reconciles recent jobs, resumes monitoring an unfinished job, and returns a
  restored locked stage to Explore.
- Download and Project shared one idempotency key and submitted flag, so one blocked
  the other and could reuse the other's key. They are now per plan kind.
- A job's completion auto-selection was dropped when another action was running; it
  now waits for the action to finish unless the user selected something meanwhile.
- Escape in a modal also closed the narrow drawer beneath it; field errors used a
  literal U+FFFD separator.

Spec alignment: confirmations are limited to completed downstream work from the
current plan (or clearing a downloaded baseline); narrow screens get a labelled
stage selector that reaches earlier stages; the map is inert beneath an open narrow
drawer. Removed dead code: unused `ResultsView`, `ApiDocs` and `RequestPanel`, the
`flexlayout-react` dependency, its Vite CSS plugin, and old compact-tab/FlexLayout
CSS. `api-catalog.json` is still generated, served and parity-tested. ROADMAP,
ADR 0003 and limitations no longer describe docking.

## UI issue fixes — 2026-09-21

Owner reported: an incorrect heatmap color gradient, a Download confirmation drifting
to the page corner, other Download layout problems, and no download progress hint;
and asked to fix these plus the open spec items autonomously. Reproduced in a real
browser against the fixture backend with an opt-in `OPENEPW_UI_FIXTURE_DELAY`, using
desktop light/dark and 700 px screenshots before and after each change.

Root causes and fixes:

- Heatmap: the ECharts visual map had no `dimension`, so cells were colored by their
  row index (the last data dimension), producing a left-to-right time ramp instead of
  values. It now maps dimension 2 on the sequential palette with a visible legend
  scaled to the observed range (previously forced to include 0 and 1, flattening
  pressure and temperature). Days are category indexes from the first rendered day
  (previously shifted by one, dropping the last day); missing hours use the no-data
  color. The fixture was constant, which hid this; it now has seasonal and diurnal
  cycles.
- Monthly axis labels were formatted in the viewer's zone from UTC month starts, so
  every month was labelled one month early west of UTC; they now format in UTC.
- Confirmation: `.run-confirmation` was styled as an absolute popover under Run but
  portalled to `<body>`, so it landed at the document's bottom-right and stretched
  the page. It is now a centered modal with a backdrop and plan facts.
- Progress: the worker saved failed counts only at the end; it now persists
  completed and failed counts after every output. The UI shows a progress card
  (bar, processed/failed, elapsed) at the top of Download/Project and a compact bar
  in the status bar; indeterminate states animate (static under reduced motion).
- Layout: stage panels kept the Explore scroll position, hiding new content; they now
  reset on stage change and when a job starts. Duplicate dividers, the Fit-selection
  and zoom controls overlapping the inspector/Agent panel, hidden attribution (now
  visible and underlined for WCAG link contrast), non-wrapping Agent suggestions, the
  cramped baseline card and the narrow History button's missing name were fixed.

Spec items implemented: retry of only failed outputs (`POST /v1/jobs/{id}/retry`,
confirmed from the Run menu); Download rows with years, interval, resolution,
access, provisional status, limitations and attribution, and Run gated when a plan
has no outputs; shared dataset colors with a map legend, unknown/incompatible point
states, ordered coverage overlays with limitations and auto-enable after discovery;
Explore previews independent of old dataset selections with corrected limit wording;
an inspector variable list, valid-hour coverage, synthetic-chronology label, EPW
download and paged table; a Project baseline card with location, period, calendar,
source years, origin and QC; a narrow bottom-sheet inspector; Enter/Escape to finish
or cancel drawing; stage and job-completion announcements; quiet routine previews;
reduced-motion camera moves; and expandable Agent tool cards. Remaining open items are
listed in the acceptance record.

Verification: Python 103 passed / 15 live skipped; Ruff, format and mypy passed;
Vitest 98 across 20 files; TypeScript, ESLint and Prettier (line-ending agnostic)
passed; production build passed; Playwright 3 development and 1 production passed;
generated contracts have no drift. Each root-cause test was confirmed to fail without
its fix. CI has not run these commits.

## Remaining spec items 2–4 — 2026-09-21

Owner asked to implement items 2–4 of the open-item plan autonomously (item 1, ranked
EPW auto-selection, remains open).

- Appearance and panel sizing now go through the action registry. Appearance is
  persisted in the workspace store (migrating `openepw.appearance.v1`); `setPanelSize`
  clamps and never waits on a busy request. The scripted Agent parses appearance,
  resize and reset-panel commands.
- Applied shapes can be edited: an Edit tool reopens points, point lists, boxes and
  single-ring polygons as draggable, focusable handles with a live outline; arrows
  nudge, Delete removes down to the minimum, Enter applies, Escape discards. Point
  edits keep names, ids and offsets. Handle keys are stopped natively because MapLibre
  listens on the map container; clicks on markers no longer add vertices.
- Provisional previews: complete area shapes being drawn or edited are sampled 600 ms
  after the last change with superseded requests aborted; the result is faded points
  and a "not applied" status kept out of the store, so Run and the authoritative
  preview are unaffected.

Browser checks against the fixture: drawing and editing by drag and keyboard applied
246 → 440 samples without panning the globe; Escape discarded; one provisional
request per settled drag; authoritative count and Run state unchanged until finish.
Verification: Python 103 passed / 15 skipped; Ruff and mypy passed; Vitest 111 across
22 files; TypeScript, ESLint and Prettier passed; build passed; Playwright 3
development and 1 production passed. The native key-stop test fails without its fix.

## Ranked EPW selection and hour-of-day shift — 2026-09-21

Item 1: discovery now exposes `ranked_candidate_ids` (per location, best first, same
rule as `selected_candidate_ids`). A finished Download opens the best-ranked EPW at the
point whose details were last opened on the map (or the first planned point), falling
back down the ranking when the best dataset failed there; popovers list EPWs in that
order. Jobs from other plans and projections keep bundle order.

Owner-reported hour shift in the hourly matrix, investigated: the chart was correct;
the EPWs were not. Stored data are UTC interval ends and local time is UTC plus the
location's fixed offset. The UI sent offset 0 for every point by default and sampled
area points were always UTC, so providers that honor the requested offset (Open-Meteo,
ERA5, ISD) wrote UTC-labelled EPWs, while published NSRDB and OneBuilding TMYx files
keep their own zone. Reproduced live: Ithaca 2024-06-21 from Open-Meteo peaks in GHI at
local 18:00 with offset 0 and 13:00 with UTC−5.

Ruling: adopt a longitude-based nominal standard time, `floor(lon/15 + 0.5)` hours, as
the UI default for new points, geocoded places and sampled areas
(`SamplingSpec.standard_offset="longitude"`, additive; API default stays UTC and the
default is excluded from plan hashes so stored plans validate). A legal time-zone
lookup would need a new dependency with share-alike boundary data and is not adopted
without owner approval. Offsets remain editable; the Explore panel warns when an offset
is an hour or more from the longitude's with a one-click fix, saved drafts migrate to
longitude-based sampling, and the inspector and baseline card state each file's zone
and flag a mismatch. The browser fixture now follows local solar time and the Open-Meteo
UTC window, so a correct offset puts its daily peak near noon.

Verification: Python 105 passed / 15 skipped; Ruff, format and mypy passed; Vitest 125
across 24 files; TypeScript, ESLint, Prettier and build passed; Playwright 3 development
and 1 production passed. Browser check: default offset UTC−5, DNI peak at local hour 12,
area points sampled at −300, and the complete dataset's EPW opened first. The ranking
monitor test fails when bundle order is restored.
