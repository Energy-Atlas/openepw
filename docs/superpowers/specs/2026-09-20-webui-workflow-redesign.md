# OpenEPW map-first staged UI redesign

Status: approved on 2026-09-20 for documentation and subsequent implementation.

Reference implementation: `../energyatlas-ui`, especially its header Run split
button, compact analytical chrome, action registry, and chat transcript patterns.
The reference repository is a design source, not a runtime dependency.

This document supersedes the workflow, information architecture, layout, map-mode,
results-placement, raw-JSON, hybrid-control, and Agent interaction sections of
[the original web UI design](2026-09-20-webui-design.md). Its still-valid decisions
remain in force: Python owns scientific behavior; browser operations use REST;
local-first single-user deployment; real state and provenance only; optional UI
packaging; bounded uploads; in-memory credentials; all six curated appearances;
and no claim that a parseable EPW is simulation-ready.

This is an implementation contract, not a claim about the UI currently shipped.

## Product model

The workspace is one sequential weather workflow with three revisitable stages:

1. **Explore** defines geography, time, product and sampling, then discovers
   availability.
2. **Download** selects one or more datasets for the whole query, reviews the live
   plan, and obtains or converts existing weather into EPWs.
3. **Project** uses one active, validated EPW as the baseline for one of the two
   implemented future-weather methods and produces projected EPWs.

Use *Project* and *projection*, not *Forecast*, because these are scenario-based
future weather products rather than time-bound forecasts. Stage 2 product choices
are historical/date-range, AMY, TMY, TMYx and other supported published products.

The stages are ordered but not locked after completion. A user may navigate to a
completed stage. Navigation alone changes nothing; editing an upstream input marks
dependent discovery, plans and current selections stale. Prior jobs and artifacts
are immutable history and are never deleted by invalidation.

### Stage state machine

| Active stage | Entry requirement | Primary `Run` action | Successful transition |
| --- | --- | --- | --- |
| Explore | None | Validate the query, run authoritative sampling and discover all eligible providers | Enter Download after a current discovery response contains at least one candidate |
| Download | Current discovery, at least one dataset selected, current live plan | Submit the reviewed dataset/location/period plan | Stay while the job runs; enter Project after terminal completion with at least one usable EPW |
| Project | One active validated baseline and a current future plan | Submit the selected future method/scenario/profile | Stay in Project; select the new projected EPW and open its inspector after usable completion |

Stage state is derived rather than stored as an independent truth. The current
stage may be persisted as a view preference, but its unlocked/completed/stale
status is recomputed from current drafts, hashes, jobs and artifacts on reload.

The transition rules are:

- `Run` never advances optimistically. While work is pending, the active stage
  remains visible with real progress or an indeterminate state.
- A failed or candidate-free Explore run remains in Explore with field and service
  issues attached to the relevant controls.
- Download source changes re-plan automatically. `Run` is disabled, with its
  reason visible, until that plan matches the discovery and selected datasets.
- Dataset selections apply uniformly to the whole query. Every feasible selected
  dataset x sampled point x period combination becomes a planned EPW output.
  Unavailable combinations stay visible as scoped issues; they are not silently
  replaced by a different source.
- Partial Download success unlocks Project for successful EPWs while failed or
  unavailable combinations remain selectable for diagnosis and retry.
- With one usable EPW, select it automatically. With several, prefer the
  backend-ranked dataset at the currently selected map point, then the first
  sampled point; the user can replace it from the point popover.
- An uploaded EPW is registered in Download, parsed and validated automatically,
  then selected if usable. Warnings and `simulation_ready=false` remain visible.
- Editing Explore invalidates current Download and Project state. Editing Download
  invalidates its plan and any Project selection derived from that plan. An action
  that would invalidate completed downstream work requires confirmation.
- Project reruns create new immutable jobs and artifacts; they do not overwrite a
  prior projection.

### Run split control

The persistent top action is one compact split control modeled on the reference:

```text
+----------------+---+
|  ▶ Run          | ▾ |
+----------------+---+
```

The main segment invokes the active stage's primary action. Its accessible name is
specific (`Find availability`, `Download weather`, or `Generate projections`) even
when the visible label stays `Run`. The menu contains only valid stage actions and
settings: refresh/re-sample in Explore; refresh availability, retry failures and
intentional rerun in Download; review/rerun in Project. Destructive reset and
appearance settings do not belong in this menu. Disabled controls remain visible
and expose a concise reason beside or beneath the control.

## Map-first cockpit

The globe is the continuous visual workspace. There are no Map, Results or API
Docs tabs and no interchangeable dock tabs. Stage controls and Agent have stable
roles; their contents change with context but their containers do not.

### Desktop wireframe

```text
┌─ OpenEPW ──── [1 Explore] ─ [2 Download] ─ [3 Project] ─── History  ▶ Run ▾  ⚙ ─┐
│┌─ STAGE CONTROLS ──┐                                              ┌─ AGENT ─────┐│
││ stage title/status │   [floating geometry/layer tools]             │ Scripted now ││
││                    │                                                │             ││
││ current controls   │              3D GLOBE + TERRAIN                │ transcript  ││
││                    │                                                │ tool cards  ││
││ upstream summary   │        sampled/status points and coverage      │ approvals   ││
││                    │                                                │             ││
││ plan/job/artifacts │  ┌─ WEATHER INSPECTOR ────────────────┐  │ suggestions ││
││                    │  │ monthly temp + precip | hourly heatmap │  │             ││
│└─ persistent footer ─┘  └─ collapsible / height-resizable ──────┘  ├─ composer ──┤│
└────────────────────────────────────────────────────────────────────────────┘
```

The map renders full-bleed behind two restrained, translucent cockpit surfaces.
Both sidebars use the same container anatomy: fixed header, scrollable body and
fixed footer/composer. Their roles never swap. Desktop widths are independently
resizable within usable minimum/maximum bounds and persist locally. The lower
inspector occupies only the center span and has a remembered, resizable height.

The header keeps the brand at left, a keyboard-operable stepper in the middle,
and history, Run and global settings at right. API documentation and Source Code
move to the global overflow/help menu. History opens a drawer containing all jobs,
artifacts, QC/provenance links and download actions; the left panel shows only the
current stage's relevant jobs and outputs.

### Narrow-screen wireframe

```text
┌─ OpenEPW ─ [Explore ▾] ─── ▶ Run ▾ ─┐
│ [Controls]                      [Agent]│
│                                        │
│          3D GLOBE + TERRAIN            │
│       floating map tools/layers         │
│                                        │
│ ┌─ Weather inspector handle ─────┐ │
│ └─ selected artifact when expanded ─┘ │
└────────────────────────────────────────┘
```

Controls and Agent become mutually exclusive modal drawers over the map. Closing a
drawer restores focus to its trigger. The Run control and stage status remain
available. The inspector expands as a bottom sheet. Do not revert to the current
compact view tabs or stack all three regions into one long page.

### Visual system

Retain System plus the six curated appearances and their shared chrome/data token
contract. Preserve Geist, compact type, quiet seams, shallow elevation and the
reference's analytical density. Sidebars must remain legible over the map in every
appearance; translucency is restrained and automatically becomes opaque when
reduced transparency or contrast requirements demand it.

Use semantic color only with an icon, label, pattern or shape. Map datasets retain
stable palette assignments across coverage, point glyphs, legends and charts.
Respect reduced motion for camera flight, drawer movement, progress and inspector
expansion. Do not introduce decorative cards, oversized headings or ornamental
gradients.

## Stage surfaces

### Explore

The left panel contains place search and selected coordinates, product family,
year/date range, fixed standard-time offset, required sampling spacing and X/Y
offsets, count/limit feedback, and concise upstream-free help. Provider and dataset
selection are absent. Structured controls replace the raw request JSON editor.

Geometry editing exists only in Explore. A compact floating SVG toolbar provides
pan/select, point, multi-point, bounding box, polygon, move/edit, delete, undo,
finish/cancel and GeoJSON import. Icons have tooltips, accessible names and visible
selected states. Drawing supplies live measurements; polygon and box changes plus
sampling changes request a debounced authoritative preview. While dragging, keep
the last confirmed preview visible and label it as updating rather than drawing a
second client-side sampling answer.

Sample points appear before discovery. If the exact sample/output count exceeds
the executable limit, render the deterministic capped prefix, show the complete
count and limit, and disable Run until area, spacing, offsets or periods change.

### Download

The left panel summarizes the locked Explore query and lists discovery candidates
grouped by dataset, not repeated as an unstructured row for every point. The
backend-ranked candidate is selected initially with its reasons visible. Users may
select any number of standalone datasets for the whole query. Hybrid variable
assignment is deliberately omitted from this redesign.

Each dataset row shows product, documented/observed temporal availability,
resolution, credentials, missing requested variables, limitations and attribution.
Selections update a compact plan summary automatically: feasible outputs, omitted
combinations, estimated work, expected EPWs and warnings. Plan generation is not
an extra Run click.

During execution, the same panel shows job state, successful/failed counts, retry
actions and the current stage's artifacts. A point glyph segment and its popover
retain unavailable and failed states after partial completion. Clicking a point
opens its dataset/artifact picker; choosing an artifact makes it the active weather
state and opens the inspector unless the user manually collapsed it afterward.

### Project

The left panel lists the active baseline with location, source dataset, period,
calendar, QC/provenance warnings and a link back to its Download artifact. When
several EPWs exist, baseline replacement happens through the map point popover or
the baseline field; the projection run still consumes exactly one active EPW.

Expose only implemented capabilities: monthly morphing or coherent hourly climate
profile, compatible SSP/RCP scenario, target year/published climate window,
reference period where applicable, typical/extreme/ensemble profile, supported
extreme options, models, members and bounded local monthly-signal upload. Do not
render speculative risk controls or sampled-weather controls. Keep the statement
that a scenario projection is not a forecast beside the plan summary.

The map retains Download statuses and coverage selections. Geometry is read-only;
return to Explore to change it. Projected artifacts join the point popover and may
be selected for inspection. A successful Project run stays in Project.

## Map data and inspection

The map always requests globe projection and terrain; projection, terrain,
hillshade and 3D-building toggles are removed. Terrain and buildings are visual
context only and never alter weather elevation. If terrain, tiles or WebGL fail,
show the failure and retain coordinate/search controls and all non-map workflows.

Coverage and availability are distinct:

- A **coverage layer** is an attributed, provider-documented spatial/temporal
  extent. It may be vector or raster, is qualitative unless its source says
  otherwise, and never proves availability or completeness at a point or year.
- **Point availability** comes from the current discovery response for the exact
  query. It may be available, credential-gated, incompatible, unavailable,
  unknown, failed or complete.

Explore begins without an automatic coverage backdrop. After discovery, enable
the recommended/selected relevant layers and retain user toggles across stages.
The layer control permits multiple simultaneous overlays with independent opacity,
ordering, attribution and a compact legend. Unknown coverage has no invented
geometry.

For multiple datasets, each sampled point is a radial glyph with one equal angular
segment per selected dataset in stable order. There is no display cap: segments
become thinner as selections grow, while the accessible popover and legend remain
the authoritative detail. Dataset hue identifies the source; fill/pattern plus a
label identifies status. Clustering may reduce overlapping locations but must not
aggregate away selected-dataset or failure details after expansion.

### Weather inspector

The inspector is available for any selected Download or Project EPW. It is closed
when no weather artifact is selected and opens on selection; after a user manually
collapses it, background updates do not reopen it. This version shows one artifact,
not a baseline/projection comparison.

The left visualization is a monthly climate chart: mean dry-bulb temperature as a
line and total liquid precipitation as bars, with valid/expected counts. The right
is a day-of-year x hour-of-day heatmap, defaulting to DNI and offering every
supported numeric weather variable. Missing values use the theme's no-data token,
never zero. If precipitation or DNI is absent, state that explicitly and retain a
variable selector rather than fabricating a series.

Preserve 8,760 and 8,784-row calendars without compressing leap day. Tooltips show
fixed local-standard timestamps, units, missing status and TMY/TMYx source-year
labels. Synthetic chronology remains explicit. Chart controls, tables and download
actions are keyboard accessible.

## Agent and shared actions

The right panel adopts the reference chat anatomy: transcript, concise assistant
messages, expandable tool-result cards, inline confirmation cards, suggested
prompts and a persistent composer. It remains visibly **Scripted** in the initial
implementation; free-form text is not presented as generally understood.

All controls, Run menu entries, scripted recipes and a future model adapter invoke
one typed action registry. The registry covers query/location/geometry edits,
sampling, stage navigation, dataset selection, plan refresh, job submission and
cancellation, retry, model/scenario/profile selection, artifact/baseline selection,
inspection, layout and appearance. An eventual model receives a bounded state
digest and the same actions rather than direct store or HTTP access.

Reversible control edits execute immediately. Starting network/download/processing
jobs and invalidating completed downstream work require an inline confirmation.
An explicit confirmation invokes exactly the same action as the top Run control.
Tool results report observed responses; the transcript never fabricates progress,
availability or reasoning. Cancellation distinguishes aborting a client wait from
cancelling an accepted server job.

## Additive service contracts required by the UI

Names below are the target public contract. Python service functions own the
behavior; REST is a thin adapter and generated TypeScript consumes OpenAPI. Existing
Python, CLI, REST and MCP behavior remains compatible when optional fields are
absent.

### Authoritative spatial preview

`POST /v1/spatial/preview` accepts the current `WeatherRequest` and calls the same
Python sampler and validation used by discovery/planning. It returns:

```text
SpatialPreview {
  locations: Location[]          # deterministic prefix safe to render
  total_count: integer           # exact sampled point count
  returned_count: integer
  planned_output_count: integer  # points x requested periods
  execution_limit: integer
  executable: boolean
  truncated: boolean
  issues: Issue[]
}
```

The endpoint does not contact providers. It returns a capped preview plus a
structured resource-limit issue instead of allocating an unsafe array. Point,
point-list, bbox and polygon results use canonical backend ordering.

### Documented coverage catalog

`GET /v1/weather/coverage` accepts optional provider, product and year filters and
returns `CoverageLayer[]`. Each layer has a stable ID, provider, dataset, label,
`vector | raster | unknown` kind, optional GeoJSON geometry or approved tile
template, documented temporal extent, resolution only when sourced, attribution,
source URL, limitations, `coverage_basis=documented`, and `observed_at`.

Every geometry or tile source must be traceable to provider documentation or an
approved redistributable artifact. A dataset with only narrative or unknown
coverage returns metadata with kind `unknown` and produces no map shape. A matching
extent does not change point availability.

### Multiple dataset selections

Add optional `dataset_selections: DatasetSelection[]` to `WeatherRequest`:

```text
DatasetSelection {
  provider: string
  dataset: string
  product_id?: string
}
```

An empty/absent field preserves current provider ranking and single-candidate
planning. A non-empty field matches each selection against discovery candidates at
every location and plans all feasible selection/location/period outputs. Extend
output specs, artifacts and manifest records with their selection identity.
Unavailable matches produce location- and selection-scoped issues; they do not
fall through to another source. Reject the plan only when no output is feasible.

The existing `providers` field remains a discovery filter for non-UI callers. The
UI sends it empty in Explore so discovery considers every configured provider, then
uses `dataset_selections` in Download.

### Full-artifact visualization

`GET /v1/artifacts/{id}/visualization?variables=...` accepts one to four supported
numeric variables and returns a bounded `WeatherVisualization` for one EPW:

```text
WeatherVisualization {
  location: Location
  calendar: string
  total_rows: integer            # at most 8,784
  timestamps: string[]           # fixed local-standard interval starts
  source_years: (integer | null)[]
  units: map[string, string]
  series: map[string, (number | null)[]]
  monthly: MonthlySummary[]
  synthetic_chronology: boolean
  simulation_ready: boolean
  warnings: string[]
}
```

The service rejects non-weather artifacts, unknown variables, inputs longer than
8,784 hours and more than four variables. Partial-year inputs preserve their actual
timestamps; incomplete months report their applicable expected interval count and
unrepresented day/hour heatmap cells remain null. Radiation and liquid
precipitation monthly values are sums of valid interval quantities; state variables
use mean/min/max. All summaries include valid/expected counts. Missing samples
remain null. The existing paged preview endpoint stays available for tabular/raw
inspection.

Uploaded baselines continue through the bounded artifact upload endpoint. After a
successful parse, the client immediately requests inspection/QC data and registers
the artifact in Download. Parse success is eligibility for Project, not a
simulation-readiness assertion.

## Interaction states and failures

| State | Required presentation |
| --- | --- |
| Empty Explore | Location prompt, visible geometry tools, no sample or coverage claims |
| Sampling | Last confirmed points remain visible with an updating label; Run is disabled |
| Sample limit exceeded | Capped points, exact total/limit, corrective controls and blocking issue |
| Discovering | Current query summary and cancellable client wait; no optimistic advance |
| Empty discovery | Remain in Explore; provider issues and unknowns are explicit |
| Download planning | Prior plan is marked stale until the matching plan response arrives |
| Credential-gated selection | Requirement is visible; Run disabled only when no selected output is executable |
| Download running | Real job state and counts; controls cannot submit a duplicate intent |
| Partial completion | Successful artifacts selectable; failures retained by point/dataset; Project unlocked |
| Interrupted connection | Job identity retained; reconcile from server history before offering a rerun |
| Upstream edit | Confirmation when completed downstream work becomes stale; artifacts remain in History |
| Project without baseline | Run disabled with direct instruction to select or upload an EPW |
| Project failure | Remain in Project with baseline and plan intact; show retry only when safe |
| Missing chart variable | Explicit no-data message and other variables remain selectable |
| Map/terrain failure | Non-map controls remain usable; never interpret rendering failure as no coverage |

## Accessibility and verification contract

- The header stepper, split button, menus, drawers, resize handles, geometry tools,
  layer ordering, point popovers and inspector are fully keyboard operable.
- Split-button segments have distinct names and focus; menu focus returns to the
  trigger. Disabled Run reasons are programmatically associated with the button.
- Drawing offers finish, cancel and undo keyboard commands. Focus does not become
  trapped on the map canvas. Point glyph details are available without hover.
- Status never relies on color alone. Legends expose dataset and state text, and
  chart no-data patterns meet every appearance's contrast contract.
- Drawers trap focus only while modal, close with Escape, and restore trigger
  focus. Inspector expansion preserves the selected map point.
- Announce stage changes, job terminal states and validation errors through a
  restrained live region; routine map movement is silent.

Implementation acceptance must cover:

- fresh Explore through successful Download and Project;
- returning upstream, confirming invalidation, stale-state recovery and immutable
  job history;
- multiple datasets over multiple points, unavailable combinations and partial
  success;
- uploaded EPW auto-validation and baseline selection;
- 8,760- and 8,784-row visualization, partial-year date-range visualization,
  TMYx source years, missing precipitation, missing DNI, null heatmap cells and
  synthetic chronology;
- documented vector/raster/unknown coverage, multiple overlay order/opacity and
  the distinction between extent and observed point availability;
- Run keyboard/menu/disabled behavior, agent confirmation policy, duplicate-submit
  protection, cancellation and reconnect;
- desktop resize persistence, narrow drawers, bottom-sheet inspector, reduced
  motion, map fallback and every curated appearance.

Browser fixtures may supply deterministic documented coverage and weather data but
production code must have no fixture success path. Live provider tests remain
opt-in and may establish only the exact query they observed.

## Deliberate exclusions

This redesign does not add a model-backed agent, new future-risk science, sampled
future generation, hybrid-source controls, raw request JSON editing, comparison
charts, arbitrary server paths, provider credential storage, fabricated coverage,
or a frontend scientific sampler. Those require separate approved work.
