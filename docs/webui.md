# Local web UI

> **Current design:** [Map-first staged UI](superpowers/specs/2026-09-20-webui-workflow-redesign.md)
> is the implemented interaction contract. The older dock/tab workflow is superseded.

The UI is optional and lives in the same repository. Python is the canonical
service. Install the desired Python extras, run `npm ci --prefix ui` and
`npm --prefix ui run build` with Node 24, then from the root run:

```bash
openepw --env-file .env serve --ui-dir ui/dist
```

Open http://127.0.0.1:8000/ (redirects to `/ui/` when UI hosting is enabled). Default binding is loopback, one process and one
user. Existing CLI, Python and MCP workflows continue to work without a UI build.
The UI assets are not bundled into the Python wheel. Vite development uses
`npm --prefix ui run dev`, proxying API routes to port 8000. Override with
`OPENEPW_API_URL` in the Vite process environment. API docs are also at `/docs`.

## Using the workspace

- **Explore:** define place/geometry, fixed standard-time offset, period, no-leap
  output policy and sampling spacing/offsets. The Python sampler supplies the live
  authoritative point preview and execution-limit result. Providers are not chosen
  here. The floating map tools handle point/list/bbox/polygon drawing; numeric and
  GeoJSON entry remain usable if the map fails. Run discovers actual point availability.
- **Download:** inspect discovery evidence, choose one or more whole-query datasets,
  review the automatically refreshed plan, then Run. Every feasible dataset × point ×
  period produces its own EPW; unavailable combinations and partial failures remain
  explicit. Imported EPWs are parsed and checked with annual QC automatically before
  becoming eligible baselines, but passing that gate alone never labels them
  simulation-ready.
- **Project:** choose one active generated or imported EPW, one implemented future
  method and its real scenario/window controls. Run produces scenario projections,
  not forecasts. Monthly signals remain an optional local upload.
- **Map and inspector:** the center is always a 3D terrain globe. Coverage controls
  may show several attributed documented extents; these do not claim observed point
  availability. Sample markers expose dataset status in text as well as color. Select
  an EPW to inspect monthly temperature/precipitation and a variable-selectable full-
  year hourly heatmap. Leap days, gaps, units and TMYx source years are retained.
- **History and Agent:** History is an immutable job/artifact drawer. The right Agent
  is deterministic and dispatches the same registered actions as controls. Reversible
  edits apply directly until they would invalidate downstream work; those edits and
  starting jobs require confirmation. Stopping client waiting does not cancel an
  accepted server job.
- **Responsive layout and settings:** desktop sidebars retain fixed roles and resize;
  narrow windows retain the map and expose both sidebars as mutually exclusive
  drawers. System plus six curated appearances and the in-memory bearer token remain.

Drafts, panel sizes, selected coverage, theme and the last 100 submission-intent hashes/keys persist in
browser local storage. Credentials never persist there. Reload expires reviewed
plans and never automatically submits. Re-reviewing an unchanged plan reuses its
submission key to reconcile a lost response. A completed submission offers Prepare
intentional rerun for a genuinely new job. Clear browser storage to reset local UI
state; server artifacts/history are independent. Storage-disabled browsers retain
same-session safety but cannot preserve intent keys across reload.

If the server has bearer auth enabled, enter the token in Settings after each
reload. Provider credentials belong only in the ignored Python environment/TOML,
not the browser. A local server without bearer auth needs no session token.

## Development and validation

```bash
python scripts/export_openapi.py
python scripts/export_api_catalog.py
npm --prefix ui run generate
npm --prefix ui run typecheck
npm --prefix ui run lint
npm --prefix ui test
npm --prefix ui run build
npm --prefix ui run test:e2e
npm --prefix ui run test:e2e:production
```

Browser tests start isolated fixture services on 8011/5174; they do not reuse the
user's server. Windows defaults to installed Edge. On Linux set
`PLAYWRIGHT_CHANNEL=chromium` and install Playwright Chromium first. Tests exercise
the real Python pipeline with a clearly test-only synthetic provider. Live tests
are opt-in; see [acceptance](validation/webui-acceptance.md).

API reference: [Python](api/python.md), [MCP](api/mcp.md), live OpenAPI and interactive
Swagger through the UI. [Provenance](../ui/THIRD_PARTY_NOTICES.md) records adapted
reference definitions and third-party attribution. The source-code link points to
https://github.com/Energy-Atlas/openepw.

## Windows production map fix

The static server explicitly serves `.mjs` as JavaScript; Windows registry MIME
mappings otherwise can make MapLibre module workers fail despite HTTP 200. After
updating this backend, restart `openepw serve` and hard-refresh the browser. A
loaded map canvas alone does not prove worker/tile rendering; production tests now
verify the worker's shared-runtime import as well.
