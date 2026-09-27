# Map-first guided weather chat UI — revised feature and implementation plan

> **For agentic workers:** Implement this plan task by task after owner review. Use
> the repository's verification and commit rules; keep the work on
> `feature/chat-ui`. This document proposes the product and delivery contract,
> not a claim that the rendering approach has already been proved.

**Status:** Approved for implementation by the owner's “implement” request on
2026-09-26. Work began on `feature/chat-ui` from `feature/mcp` commit `516e0ed`.
Acceptance remains pending; this status does not claim completion of the scene
or workflow.

**Goal:** Provide an optional browser experience in which a full-canvas globe
and map are the persistent workspace; a fixed chat overlay guides existing-
weather retrieval, and freely floating visualization panels inspect completed
weather artifacts. The close-range scene includes decorative buildings, optional
terrain, and real geometric cast shadows.

**Architecture:** The Python service remains the authority for weather,
availability, plans, jobs, artifacts, QC, and prepared visualization JSON. A
durable Python conversation coordinator exposes versioned REST events; a separate
React/TypeScript browser renders the map, chat, overlays, downloads, and charts.
The map scene and its lighting never change scientific outputs.

**Tech stack:** Python 3.11+, FastAPI/Pydantic/SQLite from the current package;
an optional React/TypeScript/Vite browser build using MapLibre GL JS, OpenFreeMap
vector tiles, Mapterhorn Terrarium DEM, and a browser chart renderer. A focused
rendering prototype selects the cast-shadow implementation and records its
dependency and compatibility choices before production integration.

**References:** [existing visualization contract](../design/2026-09-26-weather-visualization.md),
[post-retrieval conversation plan](2026-09-26-post-download-conversations.md),
[external Eaui map-scene handoff](../references/eaui-globe-terrain-shadows-handoff.md),
[architecture](../../ARCHITECTURE.md), [features](../../FEATURES.md).

## Owner decisions and branch boundary

**Owner revision, 2026-09-27 (supersedes the fixed rail and the scene-control
list below where they conflict):** remove the top-left OpenEPW brand box and
scene/view panel; make the chat float as message bubbles with small shadows
and no panel fill; show the text field only when the current session state
expects free text, otherwise show the current card's input (options, review
actions, or map input) with an explicit switch to typing. The owner chose
automatic 3D: district zoom enables decorative buildings and shadows without
controls; terrain and alternate appearances are not exposed in the UI.
Later the same day the owner asked for the Stage 1 availability mapping on
the map and chose **all sources at once with per-source toggles** over a
one-source picker. The owner then asked for one colour system across the
whole UI and chose a **monochrome** deep-ocean ladder for basemap, map
features, backdrop and chat, with amber kept only for the user's selection.
This supersedes the teal/slate roles in the design-direction palette below.

- Open directly on the full-canvas map. There is **one** chat experience: no
  Guided/Text mode choice, splash selector, or mode switch. Free text and
  structured choices feed the same request state.
- Chat stays visible in a fixed position on one side of the map. A requested
  chart is a freely movable, resizable overlay; chat and chart remain visible
  together. The map remains the canvas underneath both.
- Include a globe, optional 3D terrain, and geometric cast shadows. Use
  buildings available from the basemap as decorative scene geometry. Their
  heights and shadows are visual approximations, never building-model inputs,
  weather evidence, solar potential, or simulation results.
- “All features” covers the guided chat workflow, geographic input, evidence
  layers, weather retrieval, job progress, artifact download, and the currently
  supported prepared-data visualizations, as well as the globe scene above.
- This plan is edited and reviewed on `feature/mcp`. **After review, create
  `feature/chat-ui` from the then-current `feature/mcp` tip and put every new
  implementation commit there.** Do not implement on `feature/mcp`, use a
  worktree, or merge/cherry-pick/copy `feature/webui`. Preserve both branches.
  The Eaui checkout is a read-only design reference, not a code source.
- The owner's explicit UI request supersedes the older handoff's “no frontend”
  default for this optional browser client. Python, REST, MCP, and CLI still work
  without Node or a browser build. Future-weather UI remains suspended.

## Experience and visual composition

The map is the first view, initially at a neutral globe scale with a short chat
invitation such as “Where do you need weather?” It does not request browser
geolocation or assume Boston. A search, map action, or location mentioned in
chat moves the camera to the chosen place while preserving the user's confirmed
request facts. At close zoom the same view becomes a quiet street/terrain scene.

```text
Wide viewport
┌────────────────────────── full-canvas map / globe ──────────────────────────┐
│ map scene controls       geography, markers, evidence          attribution │
│                                                                          ┌──┴─┐
│       ┌────────── movable, resizable chart ──────────┐                 │chat│
│       │ prepared view, units, coverage, provenance    │                 │rail│
│       └───────────────────────────────────────────────┘                 │    │
│                                                                  ┌──────┤    │
│                                                                  │input │    │
└──────────────────────────────────────────────────────────────────┴──────┴────┘
```

The desktop chat rail is fixed at the right edge, with a stable width and
scrolling transcript. A narrow viewport uses a fixed bottom chat region that
keeps its input and latest prompt visible; floating views are constrained to
the remaining viewport and can be minimized without losing state. Panels do
not cause the map canvas to resize. Map camera padding and “focus selection”
keep the target visible outside overlays. Dragging/resizing a chart has mouse,
touch, and keyboard equivalents; chart controls, close/minimize, focus order,
screen-reader labels, and reduced-motion behavior are part of acceptance.

Design direction: the geographic surface carries the visual weight; UI chrome
is legible and restrained. Begin with an OpenEPW palette of deep ocean
`#173849`, pale cloud `#F3F7F7`, teal observation `#237E8B`, solar amber
`#D69B36`, and unknown slate `#647782`. Use IBM Plex Sans for prose and IBM
Plex Mono only for coordinates, units, and IDs. Review contrast against both
light and dark basemaps. Provide six curated map appearances inspired by the
reference's light, dark, monochrome, landform, clean technical, and dark
engineering intents; define OpenEPW's own tokens and styles rather than
copying Eaui components or palette code. Each appearance preserves readable
roads, labels, selection, weather markers, evidence legends, chart overlays,
and required attribution.

## User journey and conversation behavior

1. **Start on map:** The fixed chat offers a free-text prompt and concrete
   actions to search a place, choose a point, draw an area, or upload GeoJSON.
   Suggested prompts fill an editable message; there is no mode distinction.
2. **Understand the whole turn:** Extract all stated intentions in one pass:
   place/coordinates, actual years or dates, published reference product,
   requested datasets, view/download intent, and corrections. Preserve
   confirmed facts across turns and present only unresolved ambiguities.
   “Historical” and “AMY” mean the same actual-year path in this UI.
3. **Locate:** Geocoder candidates appear as numbered choices in chat, markers
   on the map, and an accessible list. A selected candidate is retained when
   the user next supplies year or product. Point lists, bbox, polygon drawing,
   and GeoJSON upload serialize to existing `WeatherRequest` geography types.
   Show requested versus resolved or sampled points and output count.
4. **Choose and assess:** Ask one actionable question at a time where needed;
   single choice, multiple choice, Other with text, coordinates, and map
   actions all return typed answers. Read-only catalog assessment/discovery
   shows supported-to-try, unavailable, unknown, and gated alternatives with
   evidence dates and conditions. It never promises weather completeness.
5. **Review and run:** Show confirmed geography, product/actual years,
   datasets, output count, access conditions, warnings, plan hash, and the
   current exact action. Run is an explicit click on the reviewed plan; typing
   or selecting map geometry does not start provider retrieval. Corrections
   invalidate only dependent facts and the stale plan.
6. **Track:** Show real tool-call and result events, queued/running/completed/
   partial/failed/cancelled states, and a progress bar with processed/total
   outputs. Refresh resumes the same session and job without resubmission.
   Cancel waiting and cancel server job are distinct actions.
7. **Use outputs:** Resolve artifacts from the verified job manifest by
   occurrence, location, source, and period. Inspect/QC, view, download one,
   and download all successful outputs are distinct from retrieving provider
   weather again. Uploading a user EPW is a separate analysis input and does
   not invent a provider or actual-year identity.
8. **Visualize:** A view request references existing artifact IDs and returns
   the service's immutable `VisualizationSpec` and paged rows. A new floating
   panel renders the supported family while chat remains fixed. Later prompts
   can compare, focus, minimize, or reopen a view without a new fetch.

The transcript contains messages, questions, factual tool events, plan and job
cards, artifact lists, and view references. It retains earlier turns and the
current draft across reload. It does not store provider bodies, credentials,
EPW bytes, full hourly tables, or unredacted sensitive text. A greeting,
acknowledgment, “where is my file?”, and “show my 2016 data” must use the
current conversation context rather than starting an empty weather request.

## Map scene and geographic evidence

- OpenFreeMap supplies the basemap and its default `building` vector layer;
  preserve OpenFreeMap/OpenMapTiles/OpenStreetMap attribution. OpenMapTiles
  `render_height` may be derived from levels or a fallback, so buildings and
  their cast shadows are labelled **decorative, approximate map context**.
  Do not turn them into simulation geometry, source locations, or claims about
  any building. Verify the actual live style/source fields before relying on
  them; missing buildings or heights yield a visible scene limitation.
- Globe projection persists across style and appearance changes. 3D view
  enables tilt, extrusion, solar lighting, and shadow eligibility. Terrain is
  optional within 3D, uses Mapterhorn Terrarium DEM where available, and
  displays its source attribution. Terrain failure keeps the map and flat
  ground usable and makes shadow limitations explicit.
- One UTC/season solar state drives facade lighting, hillshade direction,
  and the cast-shadow renderer at the local scene. User controls expose 3D,
  terrain, terrain exaggeration, season/day, UTC time, light intensity,
  diffusion/haze, appearance, and shadow on/off in a compact scene panel.
  Values and labels distinguish visual sunlight from weather-file dates.
  Below the local horizon, direct cast shadows disappear. No globe-scale
  day/night terminator is promised by the close-range shadow control.
- Cast shadows are **geometric occlusion**, not dark extrusion faces or
  `hillshade-shadow-color`. At district zoom, basemap buildings cast onto
  ground and other buildings; terrain relief casts where DEM geometry is
  present. Ground, buildings, and shadows share the displayed elevation and
  exaggeration. Shadows update with camera, style, time, season, tile, and
  terrain changes. They remain visually subordinate to selection, labels,
  chart overlays, and weather markers. Shadow rendering pauses at globe
  overview, in flat mode, or when unavailable; the UI states why.
- A focused rendering prototype must establish a viable MapLibre custom-layer
  integration before production shadow work. Compare a shared-depth shadow
  pass and a synchronized scene/mesh approach against globe transition,
  terrain sampling, tile seams, style reloads, and browser performance. Record
  the chosen method, source licenses, limitations, and validation images in
  an ADR. The Eaui checkout has no existing cast-shadow implementation;
  MapLibre's single-model shadow example is a feasibility reference, not
  proof of the required terrain/building behavior.
- Map selection and evidence are separate layers. Availability overlays show
  evidence type, source, date, scope, and unknown regions. A documented
  footprint is not a verified point-level eligibility polygon; a license
  geography count is not a coverage polygon. Request-specific assessments
  remain authoritative for the selected points. Basemap and shadow failures
  never block coordinate entry, place search, GeoJSON upload, or chat review.
- Validate GeoJSON coordinate reference system, polygon holes, self-
  intersections, vertex/file size, requested-point cap, and antimeridian
  behavior against the service's existing geography contract. Do not silently
  repair or sample to fewer points. Show the exact service-accepted points
  before Run, and permit map/list/coordinate equivalents.

## System boundaries and proposed file map

| Unit | Files to create or extend | Owned behavior |
| --- | --- | --- |
| Conversation contract | `src/openepw/chat/{models,coordinator,store}.py` | Versioned session, facts, questions, revisions, ordered events, redacted messages, idempotency |
| Thin REST adapter | `src/openepw/api/chat.py`, `src/openepw/api/app.py` | Session/turn/action/event endpoints; existing service calls and auth/size limits |
| View REST adapter | `src/openepw/api/views.py` | Capabilities, describe, prepare, page through existing visualization service |
| Browser app | `web/chat-ui/{package.json,src/**}` | Optional build, fixed chat, map, scene controls, charts, artifact transfers |
| Browser map | `web/chat-ui/src/map/**` | Globe, basemap, terrain, buildings, shadows, drawing, markers, evidence |
| Browser views | `web/chat-ui/src/views/**` | Versioned spec validation, five initial renderers, floating windows and fallback |
| Tests and docs | `tests/chat/**`, `tests/unit/test_api*.py`, `web/chat-ui/tests/**`, `docs/**` | Offline contracts, browser/e2e journeys, architecture, limits, setup, validation |

The coordinator uses typed confirmed facts and an explicit dependency graph,
not transcript rereading, for memory. It may reuse extraction concepts from
`harness` but remains server-side and browser-neutral. The model can propose
intent fields from a complex message; deterministic validators, service
assessments, and the user confirm ambiguous facts. A model cannot invent
availability, plan hashes, outputs, QC, or chart values.

The REST contract uses stable session/event IDs, discriminated versioned cards,
opaque choice IDs, and question revision numbers. Core actions are create/
resume session, send turn, answer current question, update geography, review/
run plan, inspect/cancel/retry job, read events by cursor, and prepare/page
views. A stale action returns the current card and a typed conflict. A session
has one writer; a second send enters a visible withdrawable FIFO queue.
Idempotency keys cover retries and double clicks, especially Run. Poll events
with a cursor first; streaming may later reuse the same event shapes.

The browser uses the existing REST authentication and loopback defaults. It
never stores bearer keys in local storage, logs, URLs, chart specs, traces,
or conversation events. Durable server state is private to the local data
root. Local browser storage holds only the session ID and harmless appearance/
window preferences. Bound uploads, geometry, event payloads, visualization
pages, chart count, and map/shadow resources.

The visualization REST adapter calls `WeatherService.visualization_capabilities`,
`describe_weather_data`, `visualize_weather`, and prepared-page access. It
does not implement scientific aggregation. The browser handles the five
implemented families (`time_series`, `annual_series`, `monthly_series`,
`histogram`, `spatial`); planned families and unknown schema versions show a
readable unsupported state. All plots display units, time/calendar meaning,
artifact/source labels, expected/valid/missing counts, nulls and partial
results. An irregular spatial result uses points; only a complete grid uses
a matrix. No plot implies simulation readiness.

## Delivery tasks and reviewable outputs

Each task ends with focused tests, a reviewable behavior, and a moderate
`fix(topic): concise description` commit on `feature/chat-ui`. Work can be
committed within a task at coherent contract, scene, or test boundaries.

### Task 1 — Branch, contracts, and optional browser skeleton

- After plan review, create `feature/chat-ui` from the current `feature/mcp`
  tip; record the starting commit and inspect collaborators' changes. Add
  the independent optional browser build, API client, typed session/card/
  event/view contracts, and a map-canvas shell with a fixed chat overlay.
- Define a single no-mode journey and the page's responsive panel geometry.
  The map fills the viewport; browser build dependencies remain optional to
  `pip install openepw`.
- Verify typecheck/build and a browser smoke test that opens on a full map
  with one chat input and no mode selector. Commit the scaffold and contracts.

### Task 2 — Globe, terrain, decorative buildings, and scene controls

- Integrate MapLibre/OpenFreeMap, globe continuity, six appearance tokens,
  attribution, close-range 3D buildings, Mapterhorn DEM/hillshade, and solar
  controls. Verify live basemap building layer and height fields; record the
  observed style/schema and fallback behavior without copying Eaui code.
- Keep all scene effects display-only and restore them after style changes.
  Make tile/DEM load, ready, failed, retry, and paused states legible; retain
  coordinate entry when map services fail.
- Offline map-state tests cover control transitions and style reload. Browser
  smoke and manual visual captures cover globe→district, terrain true scale
  and exaggeration, six appearances, attribution, and a failed tile source.

### Task 3 — Real cast shadows

- Run the rendering prototype early, before expanding the rest of the UI.
  Use controlled building polygons/heights and a small DEM fixture to verify
  one building shadows ground and another building, and relief blocks direct
  light. Select and document the renderer only after testing globe/local
  projection, map depth/layer order, DEM alignment, and style reload.
- Integrate live basemap building geometry and the terrain mesh within bounded
  close-range tile and performance limits. Use the same local sun vector and
  displayed terrain exaggeration as the visible scene. Treat approximate
  basemap height explicitly as display-only.
- Test morning/noon/evening direction and length, local night, flat terrain,
  exaggerated relief, tile edges, camera movement, style swap, unavailable
  DEM/geometry, and unsupported graphics. Capture real-renderer screenshots;
  flat browser terrain stubs alone cannot prove shadows. A prototype failure
  is reported as a material blocker for this required feature, not relabelled
  as hillshade or quietly removed from scope.

### Task 4 — Durable single-flow conversation

- Implement the typed Python coordinator, redacted SQLite session/event
  store, REST adapter, question revisions, single-writer queue, and model
  interpretation of complete multi-intent messages. Confirmed location,
  product, years, dataset, pending plan, job, artifacts, and views persist
  across turns and reload. Structured selections and free text update the
  same state.
- Render the fixed chat rail, accessible choice cards, Other/text answer,
  pending send, tool-call/result messages, corrections, and event cursor.
- Offline tests cover “Cambridge MA, 2012–2014 historical” in one turn,
  follow-up year/product/location memory, ambiguous geocoding, stale choice,
  duplicate send, queued correction, redaction, and reload. Browser tests
  verify keyboard and screen-reader paths and no mode choice.

### Task 5 — Geographic input, evidence, planning, and Run

- Add map point selection, point lists, bbox/polygon drawing, GeoJSON upload,
  geocoder markers and accessible candidate list; serialize to the existing
  typed geography models and show exact accepted/sampled points. Surface
  source/date/uncertainty on every availability layer and assessment.
- Connect service geocode, availability, discover, weather plan, and explicit
  Run. Show all plan warnings and output rows; corrections stale the affected
  plan. No provider call occurs from a map gesture or read-only assessment.
- Tests cover holes, invalid/oversized geometry, service point cap,
  antimeridian behavior, map failure/coordinate fallback, map/list parity,
  unknown coverage, plan revision and double-click Run idempotency.

### Task 6 — Job lifecycle, contextual follow-ups, and downloads

- Connect real job events/progress, cancellation, failed-output retry,
  manifest-based artifact mapping, and inspection. Reattach after refresh
  without another job. Explain missing EPW values/QC without claiming that
  retrieval eligibility or a syntactically valid EPW proves simulation
  readiness.
- Download one verified artifact through REST. “Download all” creates the
  service's compact export and transfers its ZIP to the user's disk with the
  complete mapping; failed outputs are excluded and reported. Use safe
  filenames/checksums and browser collision behavior. Accept a separate
  uploaded EPW for analysis through a bounded, generic input path.
- Tests cover multi-location/multi-year identities, partial/cancelled jobs,
  stale older artifacts after a failed new job, refresh during run, “where is
  my file?”, one/all downloads, retry scope, and zero new provider calls
  for inspect/download follow-ups.

### Task 7 — Floating visualizations and prepared-data adapter

- Expose visualization capability/describe/prepare/page through thin REST
  routes. Resolve user phrases to explicit artifact IDs from the current
  manifest; do not infer them from list order. Render the five implemented
  families in movable/resizable panels over the map with chat always visible.
- Support multiple panels with bounded count and pagination; retain view IDs
  in the session. Show provenance, units, coverage and partial/null warnings
  adjacent to each plot. Provide table/JSON fallback for unsupported family,
  chart failure, and assistive technology.
- Contract/browser tests cover each family, irregular spatial points versus
  complete grid, missing NOAA values, leap-year/calendar labeling, uploaded
  EPW identity, unknown spec version, panel drag/resize/keyboard control,
  reload, and no provider retrieval on a view request.

### Task 8 — End-to-end acceptance and project memory

- Exercise synthetic journeys through real REST and browser: map-first
  complex request, area selection, source uncertainty, review/Run, partial
  job, progress, refresh, chart overlay, one/all downloads, and an uploaded
  EPW. Use bounded opt-in live checks only for remaining map/tile/rendering
  risks; do not put credentials into browser artifacts or traces.
- Run Python contract/API tests, browser unit/accessibility/e2e tests,
  typecheck/build, and real-renderer scene checks on the target desktop.
  Record commands, outcomes, browser/device limits, data attribution, and
  shadow quality/performance limits. Update `ARCHITECTURE.md`, `FEATURES.md`,
  roadmap, UI startup guidance, limitations, and ADR/validation records.
- Review the `feature/chat-ui` diff against this plan and the repository
  rules. Do not merge, deploy, or publish as part of this task without the
  owner's separate direction.

## Acceptance scenarios

1. First load shows a usable full-canvas globe and fixed chat, with no mode
   chooser. A user enters “UBEM for Cambridge, MA, 2012–2014 historical”; the
   session retains place, actual years and intent, asks only for unresolved
   choices, and never mistakes “2012 buildings” for a weather year.
2. The user chooses a geocoder candidate on map or list, reviews an exact
   plan, clicks Run once, refreshes while it executes, and receives the same
   job and correctly mapped artifact cards. A duplicate Run makes no job.
3. A drawn area or uploaded GeoJSON shows the service-accepted points and
   cap before Run. Invalid shape, holes, dateline edge cases and map outage
   have explicit recoverable behavior.
4. A source footprint is shown with its evidence date and uncertainty; a
   region with unknown coverage is not colored as verified availability.
5. The globe zooms into a 3D district without losing camera or theme. Terrain
   toggles and exaggeration work. Decorative basemap buildings cast visible
   shadows onto ground and each other, relief casts where DEM is present,
   shadows move with UTC time, and direct shadows vanish at local night.
   Labels, markers and selection stay readable. A failed DEM or shadow pass
   reports its state while map and chat remain usable.
6. Chat stays fixed while a monthly GHI view opens in a freely floating chart;
   both are visible. The chart has `Wh/m2`, source/year/calendar and missing-
   hour coverage. Move, resize, minimize, reopen and keyboard controls work.
   No provider fetch occurs.
7. A multi-output job lets the user download one successful EPW and a compact
   all-successful-output ZIP to user disk. The output mapping is complete;
   failed rows are reported, and “download” never means provider retrieval.
8. A user EPW upload can be described or visualized without invented source
   or actual-year identity. Future-weather requests receive a concise
   unavailable response; this UI makes no future plan/job call.

## Review focus and external dependencies

| Likely failure | Required check and expected behavior |
| --- | --- |
| Basemap has no usable building features at a location/zoom | Decorative 3D/shadows state says unavailable; weather workflow continues |
| DEM and building meshes disagree in elevation | Real-renderer test shows attached geometry at 1× and exaggerated relief before acceptance |
| Globe/custom-layer projection or style reload breaks shadows | Camera/style tests restore correct shadow or report pause, never display detached geometry |
| Long chat session reuses an old location, year, job or artifact | Manifest and confirmed-fact tests keep each reference tied to the intended turn |
| Partial weather data enters a chart | Null/partial rules, coverage, unit and temporal labels survive REST and browser rendering |

External map tiles have no service-level guarantee. OpenFreeMap states that its
public instance requires attribution and offers no SLA; Mapterhorn provides a
Terrarium tile endpoint and source attribution. The browser must stay useful
when either is unavailable. Building `render_height` is approximate under the
OpenMapTiles schema; it is never presented as surveyed height. Source references:
[OpenFreeMap service and attribution](https://openfreemap.org/),
[OpenMapTiles building schema](https://github.com/openmaptiles/openmaptiles/blob/master/layers/building/building.yaml),
[Mapterhorn tiles](https://mapterhorn.com/data-access/),
[Mapterhorn attribution](https://mapterhorn.com/attribution/),
[MapLibre globe/custom-layer examples](https://maplibre.org/maplibre-gl-js/docs/examples/),
and [MapLibre's single-model shadow example](https://maplibre.org/maplibre-gl-js/docs/examples/add-a-3d-model-with-shadow-using-threejs/).

## Exclusions and execution gate

No future-weather workflow, historical TMY/XMY synthesis, building-energy or
PV/shading calculation, scientific use of decorative building geometry,
arbitrary plot code, public multi-user hosting, mandatory distributed service,
or reuse of `feature/webui`/Eaui code. The scene's season/time is display-only
and is not a weather-file transform.

The owner approved implementation on 2026-09-26. Work on `feature/chat-ui`
began from `feature/mcp` commit `516e0ed`. The local implementation and
remaining acceptance limits are recorded in the [validation record](../validation/2026-09-26-chat-ui.md)
and [scene decision](../decisions/0004-map-first-chat-scene.md). Integration into
another branch and publication are separate decisions.
