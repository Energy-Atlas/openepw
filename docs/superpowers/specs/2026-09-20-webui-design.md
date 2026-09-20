# OpenEPW web UI — draft design

Status: approved on 2026-09-20 for autonomous implementation. Local-first, single-user confirmed.
Branch: preserve `feature/webui`. Baseline backend: `b1f8d4a`.
Reference: `../energyatlas-ui`, `feature/agentic`, inspected commit `e52d513`.

## Confirmed intent

Build a simple, useful OpenEPW frontend in this repository under `ui/`. Reuse the
reference's React/FlexLayout foundations, visual language, themes, MapLibre/3D
interaction and agent-panel patterns. Remove EnergyAtlas branding, energy-model
panels, simulated workflows, fictional data and unnecessary menus. Add API docs
and a source-code link. Scripted agents execute real OpenEPW operations; no LLM.
Do not extract repositories or publish a UI-free PyPI release in this milestone.
The original brief's no-frontend constraint is superseded by this explicit request.

## Proposed defaults requiring review

- Local-first, single-user deployment, using the existing single-process backend.
  Remote shared-server/multi-user behavior is not part of this milestone. This is
  an assumption, not an answer to the earlier deployment question.
- Include both existing-weather retrieval and future generation. Manual operation
  comes first; scripted workflows invoke the same actions.
- Browser traffic uses REST. Keep the existing MCP service and document it; do not
  add a second browser MCP transport or change its loopback-only restriction.
- Desktop-first; compact widths use one primary view and collapsible panels.
- Preserve the six reference appearances plus System, selected from one settings
  popover. Default to System; do not duplicate theme controls across panels.
- Native inline implementation with a final independent review is the recommended
  execution method. Do not start it until the owner approves the draft.

## Architecture and alternatives

Recommended: adapt selected reference primitives into `ui/`, replace its domain
state with OpenEPW request/job/artifact state, and use typed HTTP contracts. A fresh
shell without reuse would reduce inherited coupling but lose working docking/theme
behavior. Copying the entire reference and deleting features risks preserving its
synthetic engine and broad domain imports; reject that approach.

React + TypeScript + Vite frontend; FlexLayout, React Aria, Zustand, Lucide and
Geist for the shell; MapLibre with its React wrapper for maps; ECharts for the
small result charts. Reuse versions/lockfile evidence deliberately, not the whole
reference dependency set. No AG Grid, React Flow, Dagre, LLM SDK or Vite LLM proxy.
Node 24 and TypeScript 6 are the reference baseline, subject to a checked clean
install. Python retains its declared 3.11+ support and independent packaging.

State boundaries:

- Backend owns discovery, planning, science, jobs, artifact identities and QC.
- UI owns request drafts, selected candidate/job/artifact, map view and layout.
- One typed action dispatcher handles manual and scripted operations.
- Request edits invalidate the displayed plan; execution must use the reviewed
  current plan. A cancelled browser request does not imply a backend job stopped.
- Persist versioned layout, appearance and small request drafts locally. Recover
  jobs from the backend. Do not persist credentials, weather arrays or executable
  pending approvals in browser storage. UI history must not invent server history.

Development: Vite proxies `/v1`, `/health` and `/openapi.json` to local FastAPI.
Production: explicit `openepw serve --ui-dir ui/dist` mounts assets at `/ui/`.
The API works without that argument or Node. Static fallback never captures API,
MCP or artifact paths. No permissive wildcard CORS. API keys stay server-side;
if bearer auth is configured, accept a session token in memory only, with
credentialed fetch/download requests. This is not a multi-user login system.

## Minimal information architecture

Header: OpenEPW, API Docs, Source Code, appearance/settings and reset layout.
Source Code points to `https://github.com/Energy-Atlas/openepw`.

Default workspace:

- Left Request dock: location search/coordinates, point list, bbox or polygon;
  Existing/Future mode; compatible provider/product/scenario/period controls.
  Advanced section contains required variables, explicit hybrid assignments and
  expert request JSON. No provider-specific menus until that provider is selected.
- Center Map and Results tabs, dockable side by side if desired.
- Right Agent dock, collapsible, with suggested real workflows and an action log.

Results contains a compact job list and the selected job/artifact detail. Request,
plan, downloads, charts, QC and provenance are sections within that view, not six
new panels. API Docs opens a document view without destroying the workspace.
Settings remains a compact popover rather than another permanent page.

## Real workflows

Existing weather: select geography -> set period/product/providers -> discover ->
inspect alternatives and limitations -> review plan -> execute -> monitor job ->
inspect QC/provenance and download. Never imply all sources supply every variable.
Candidate rows show actual metadata and unknown values explicitly. Selecting a
provider/product updates a request and re-plans; arbitrary candidate-ID execution
is not promised by the current backend.

Future: choose a generated EPW or upload one -> select method -> choose compatible
scenario/window/profile/reference period -> review plan and estimate -> execute ->
inspect/download results. Preserve method A versus B semantics, no SSP/RCP mapping.
Typical/extreme/ensemble are supported; sampled is unavailable with explanation.
For expert local monthly-signal use, add bounded JSON signal upload validated by
MonthlySignal; no arbitrary server filesystem paths. Historical and future forms
remain backed by the existing request models and scientific capability checks.

Job counts/status come from real server state. Display indeterminate progress when
no finer progress exists. Retain partial artifacts and surface per-item failures.
Downloading a valid EPW does not erase `simulation_ready=false` or missing-data QC.

## Map behavior

Search/select points, add/remove a point list, draw/edit a bbox or simple polygon,
and import a supported GeoJSON Polygon including holes. Backend spatial validation
remains authoritative; show its caps, dateline and polar restrictions. A polygon
vertex workflow needs finish/cancel/undo-last actions and keyboard alternatives.

Render requested locations and actual resolved source points with distinct marks;
show connecting displacement only for known source locations. Use returned source
resolution as metadata. Do not fabricate provider grid boundaries or worldwide
station coverage. Any sampling preview must use the same backend sampler as plans.

Retain flat/globe projection, pitch/rotation and optional terrain/hillshade.
Contextual 3D buildings may use actual basemap heights where supplied; omit them
when absent rather than importing synthetic districts or inventing heights.
Terrain is visual context, never an elevation correction to weather. Attribution,
loading/error states, WebGL fallback and resize-after-docking are required.
Map/terrain failure must not prevent coordinate entry or weather retrieval.

## Scripted agent, without a model

Name the panel Agent and visibly identify it as Scripted. Initial recipes:
Find sources for the current request; review/create a weather plan; run the current
reviewed plan and show results; plan/generate future weather from the selected
baseline; inspect the selected artifact's QC and provenance.

Recipe parameters come from the request form/selected artifact. Recipe steps await
actual HTTP responses; they do not replay a timed demo or synthesize results.
Submission has a clear Run action after plan review. Once submitted, monitoring
continues without repeated approvals. Cancel explicitly calls the job endpoint.
Logs distinguish tool inputs, observed outputs and concise rule-based explanations.
No fake reasoning or arbitrary natural-language promise. Omit model selectors,
permission-mode menus and queue/stir controls from the reference.

## Backend/API additions

Preserve existing endpoints and Python/MCP contracts. Add:

- `GET /v1/jobs?limit=20&cursor=...`: stable newest-first pagination over persisted
  jobs (submitted_at, id ordering), with an opaque validated cursor and max 100.
- `GET /v1/artifacts/{id}/preview`: EPW metadata and bounded weather preview;
  configurable start row, max 168 hourly rows, selected variables and monthly
  summaries. Include total rows, units, calendar, UTC interval-end timestamps and
  fixed standard offset. Missing values are null, never zero. Monthly solar is
  summed interval energy; state variables use mean/min/max with valid/expected
  sample counts. Omit wind-direction aggregation until circular semantics exist.
- `POST /v1/artifacts/signals`: at most 5 MB of MonthlySignal JSON records, at most
  10 records; validated structure/provenance; returns a registered ArtifactRef.
- Explicit response/error schemas and examples on all REST routes. The preview
  calculation belongs in the Python service layer, not duplicated in JavaScript.

Expose sampling preview only if needed by the map task: an additive endpoint that
calls the existing sampler with the same caps. Never implement another sampler.
Do not introduce broader capability or credentials-management APIs merely for UI.
Discovery already reports credential requirements; failures remain structured.

## API documentation and source access

An API Docs view covers REST, Python and MCP. REST comes from the running OpenAPI
schema, with request/response/errors/auth/examples and the existing interactive
FastAPI reference link. Python lists all public convenience functions and key
models; MCP lists six tools and artifact resources. Add checkable catalogs so
new exported functions/routes/tools cause a documentation parity test failure.
No manually invented endpoints or duplicate scientific documentation in the UI.

## Verification and delivery

Offline Python and frontend tests plus browser tests cover real application state
transitions using deterministic API/provider fixtures; production code contains
no fixture-based success path. Browser tests block real weather/model traffic and
stub basemap/terrain. Separately run a bounded opt-in real Open-Meteo workflow and
one future workflow, documenting failures without faking success.

Check production assets, MapLibre workers, docking resize, themes, keyboard focus,
compact layout, reconnect/reload, duplicate submission, partial failure, and API
schema parity. Core wheel installs without Node or frontend assets. UI builds from
its own package/lockfile and has separate CI. Include adapted-code provenance and
third-party notices; the reference has no root license file, so establish ownership
and license evidence for copied portions before public distribution. Do not copy
its downloaded district datasets or any credentials.

Success: a person can retrieve and inspect a real EPW and generate a future EPW
manually or through scripted actions, see truthful status/provenance, read all API
references and navigate to source code. No energy-model concepts, simulated jobs,
LLM access or repository extraction are introduced.
