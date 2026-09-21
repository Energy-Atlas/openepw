# Local web UI

> **Approved redesign:** [Map-first staged UI](superpowers/specs/2026-09-20-webui-workflow-redesign.md)
> is the implementation contract for the next UI revision. The operating guidance
> below describes the currently shipped interface until that redesign is built.

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

- **Request:** enter a point or select one geocoding result explicitly. Choose the
  fixed standard-time offset, provider and product/year or date range. Find sources,
  inspect actual candidate limitations, review a plan, then run it. Unknown source
  resolution stays unknown. Advanced JSON exposes full API options, including
  point lists, grid offsets, output caps, variable selection and explicit hybrids.
- **Map:** select points, multiple points, two bbox corners or polygon vertices;
  finish/cancel/undo polygon drawing. Import GeoJSON Polygon/Feature, including
  holes, in Advanced request. Numeric/JSON alternatives remain available when
  tiles or WebGL fail. Globe, pitch, real-height buildings, terrain and hillshade
  are context only. No source grid cells are inferred from nominal resolution.
- **Results:** refresh server history, select a job, inspect partial failures and
  download its weather, QC, manifests and additional files. Preview pages contain
  up to 168 hourly rows; monthly summaries show valid/expected counts. Missing
  values stay missing. Synthetic chronology and actual source-year labels remain
  visible. Use an existing weather artifact as a future baseline.
- **Future:** upload a baseline EPW or use its opaque artifact ID. Choose monthly
  morphing or hourly climate profiles, the correct scenario and real climate
  window, then plan/run. Local monthly signal JSON upload is available. Sampled
  generation is explicitly unavailable. Provider/archive restrictions remain those
  documented by the Python backend.
- **Agent:** expand the right border or use the header button. Five scripted recipes
  call the same actions as manual controls. There is no LLM or natural-language
  interpreter. The log records actual tool attempts/results. Stop client operation
  aborts waiting client requests; an accepted job continues until Cancel server job.
- **Settings:** System or six themes, optional in-memory session bearer token,
  and Reset layout. Drag dock tabs/splitters; narrow windows use compact tabs.

Drafts, layout, theme and the last 100 submission-intent hashes/keys persist in
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
