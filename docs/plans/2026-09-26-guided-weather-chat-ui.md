# Guided weather chat UI — feature plan

**Status:** Product direction agreed in chat on 2026-09-26; implementation has not started. This document records the proposed delivery slices and acceptance criteria. It does not authorize future-weather UI work.

**Goal:** Give a user a guided, resumable chat interface for discovering and retrieving existing weather data, inspecting results, and downloading artifacts. A text request enters the same workflow and receives the same structured clarifications.

**Implementation base:** The current `feature/mcp` work and the canonical Python service, REST, MCP, job, artifact, and visualization contracts. Do **not** use, merge, cherry-pick, copy components from, or model the interaction on `feature/webui`. Build the chat-first interface independently. Preserve that branch and other contributors' work.

## Product contract

- The first screen offers **Guided workflow** and **Describe what I need**. Neither choice starts provider retrieval.
- Guided mode asks one actionable question at a time. Text mode extracts candidate request fields, shows what it understood, and asks the same question cards for missing or ambiguous fields. Users may switch modes without losing confirmed answers.
- The transcript scrolls upward and retains user answers, question cards, tool activity summaries, job events, visualizations, and artifact cards. The active question is visually distinct; old cards remain readable.
- A question can accept one option, multiple options, **Other…** with text, a map action, or open text. Suggested prompts insert a complete editable message into the input. Show the message box only for an open answer, **Other…**, or an explicit new text request. Sending queues a message and displays its pending state.
- A map card may accept a point, drawn area, or GeoJSON upload; show geocoder candidates as selectable points. Display availability overlays only with their evidence type, source/date, and uncertainty. A documented footprint must never be presented as verified availability at every location.
- Tool activity appears as a compact event such as `Used tool: weather_assess`, with a safe result summary and optional detail. Do not put secrets, raw provider responses, EPW bytes, or full hourly tables in the transcript.
- Results may include interactive charts from prepared visualization JSON and cards for one, several, or all downloadable artifacts. Retrieval, viewing, and downloading have distinct labels and effects.
- This workflow covers actual-year/historical and published reference weather products. It does not offer future-weather generation, future scenarios, or future-output visualizations while MCP future access is suspended.

## Guided journey

1. **Start:** choose guided or text. Offer brief example requests; the free-text path parses once, then confirms the proposed fields.
2. **Locate:** search a place, enter coordinates, select a point, draw an area, or upload valid GeoJSON. Ambiguous geocoding shows named candidates on a map and in an accessible list. An area is converted to the service's supported polygon, bbox, or sampled point request with a visible point-count estimate and cap.
3. **Choose weather meaning:** choose actual calendar years/date range or an available published reference product. Explain AMY/actual year versus TMY/TMYx/reference year before collecting incompatible period fields.
4. **Assess and select:** call read-only availability/discovery, show eligible, unavailable, unknown, credential-gated, and source alternatives. Multi-select only where the service can produce separate, explicit outputs. Never silently substitute a provider or shorten a period.
5. **Review:** show location input and resolved source positions, product and period, selected datasets, output count, access requirements, warnings, plan hash, and what will happen on Run. Corrections invalidate dependent answers and refresh the plan. Submission requires an explicit Run action on the current reviewed plan.
6. **Retrieve:** show queued/running/completed/partial/failed/cancelled job state, processed output count, and actionable errors. A browser refresh reattaches to the same job; it does not submit another. Stopping client waiting is separate from cancelling the server job.
7. **Use results:** list each output by location, dataset, and actual year or reference label. Offer inspect/QC, visualization, individual download, and a clear all-outputs option. A view request must consume existing artifacts and make no provider call.

At any point, users may revisit a confirmed answer. Later answers and a reviewed plan become stale only where their dependencies changed. Completed jobs and artifacts remain in immutable history.

## Architecture and ownership

| Unit | Responsibility | Boundary |
| --- | --- | --- |
| Python service | Geocoding, availability, planning, execution, QC, artifact and visualization semantics | Remains canonical; no weather calculations in UI or conversation coordinator |
| Conversation coordinator | Typed draft, pending question, confirmed answers, mode, ordered actions, references, and safe transcript events | May reuse ideas and tests from `harness`, but exposes a versioned browser contract rather than terminal text/menus |
| REST chat adapter | Create/resume sessions, accept answers/messages, read transcript and active card, return safe events | Calls the coordinator and existing service; no separate provider implementation |
| Browser | Render chat cards, map and charts; collect typed actions; transfer artifacts to user disk | Does not decide source eligibility, EPW quality, or scientific aggregation |

Use a private, durable session/event store scoped to one local user and data root. Store normalized request facts, event IDs, plan/job/artifact/view references, and safe presentation summaries. Retain a redacted, user-visible version of each message so the chat history survives reload; never persist its unredacted original, credentials, provider bodies, or EPW bytes in conversation state. The browser may keep only the session ID and non-sensitive display preferences locally. Preserve existing REST authentication and loopback defaults; do not create a remote multi-user service in this feature.

The REST contract should use discriminated, versioned card/event types: `mode_choice`, `single_choice`, `multi_choice`, `text_question`, `map_question`, `plan_review`, `tool_activity`, `job_progress`, `visualization`, `artifact_list`, and `error`. Every actionable option has a stable opaque ID. Answers include the current question ID and revision; stale submissions receive a typed conflict with the current card. A session processes one answer or free-text turn at a time. A second send enters a visible FIFO queue and can be withdrawn before processing. Repeated HTTP submissions carry an idempotency key and never create duplicate plans or jobs.

Start with bounded event polling using a cursor, plus existing job inspection for progress. Streaming can be added later without changing event shapes. Persist server event IDs so refresh and polling do not duplicate transcript entries. Render only allowlisted tool names and redacted summaries; tool progress is evidence of an actual call, not a fabricated narration.

Map input must serialize to existing typed geography models. Reject invalid geometry, overly large GeoJSON, too many sampled points, and unsupported coordinate systems with a recoverable question. Preserve uploaded geometry and requested coordinates as user input; show sampled or resolved provider points separately. Map failure must leave place search, coordinate entry, and GeoJSON upload usable.

Chart cards consume the existing `weather_visualize`/`weather_data_page` prepared-view contract through a thin REST adapter or equivalent Python service route. The browser pages bounded rows and renders supported families only. Show units, temporal kind, source IDs, coverage/missing counts, and partial-result warnings beside each plot; unknown families get a readable fallback rather than a blank card.

## Delivery slices

### 1. Conversation contract and durable state

- Define versioned card/action/event schemas, the workflow dependency graph, question revisions, and session persistence. Keep the guided path deterministic; use a model only for text interpretation, never as the authority for a provider claim or plan.
- Add tests for reload, short answers, corrections, stale choices, queued messages, idempotent retries, single-writer behavior, and redaction. A queued message must not race a running tool call or silently overwrite the active draft.
- Commit at the contract and persistence boundary using repository `fix(topic): description` convention.

### 2. Browser chat shell and guided retrieval

- Create an optional independent browser build and REST adapter on the current branch. Implement mode selection, transcript, single/multiple choice, **Other…**, conditional input box, suggested prompts, keyboard and screen-reader paths, and the plan review card.
- Connect geocode, availability, discovery, plan, submit, inspect, retry/cancel where supported, and artifact lists to real service responses. Show one concise `Used tool` event per actual invocation and a matching outcome.
- Test a complete synthetic point/year request, a text request with clarification, ambiguous geocoding, correction before Run, and a partial multi-output job. Verify no retrieval occurs before Run.

### 3. Spatial cards and availability evidence

- Add point selection, area drawing, GeoJSON upload, selectable geocoder markers, sampled-point preview, and an accessible list/coordinate fallback. Use one canonical typed geography payload for map and text inputs.
- Add only evidence-backed overlays with visible legend, timestamp/source, and labels for documented extent versus request-specific assessment. Unknown coverage stays unknown.
- Test polygon holes, antimeridian/bbox behavior where the service supports it, invalid/oversized uploads, point caps, map load failure, and map/list selection equivalence.

### 4. Results, views, and downloads

- Resolve output cards through verified manifest mappings, not list order or guessed filenames. Show success, omission, failure, and cancellation separately. A failed new job must not make older artifacts appear to be its results.
- Render the initially implemented visualization families from prepared JSON. Provide variable/aggregation/period controls only when capabilities allow them; preserve leap-year, reference-product, missing-data, and source labels.
- Provide individual artifact download and an explicit all-outputs path. Clearly distinguish transfer of an existing artifact from a new provider retrieval. Checksum-verified transfer, safe filenames, and no accidental overwrite are required.
- Test that inspect/view/download follow-ups produce zero new provider plan/submit calls and that a multi-location, multi-year result resolves the requested output unambiguously.

### 5. Acceptance and project memory

- Run offline Python contract/API tests, browser unit and accessibility tests, and one end-to-end synthetic journey with map, reload, partial job, chart, and downloads. Use opt-in live checks only where they answer a specific remaining risk.
- Document the new UI contract, local startup, data and credential boundaries, current limitations, and exact verification results in architecture, features, roadmap, harness/UI docs, and validation records. Do not claim a syntactically valid EPW is simulation-ready.

## Acceptance scenarios

1. A new user selects Guided, answers location/product/year questions, reviews one current plan, runs once, refreshes during execution, and receives the same job and artifact cards.
2. A user types “2016 and 2017 weather near Cambridge,” chooses one geocoder candidate from map or list, receives the same remaining questions as Guided, and sees two correctly labelled output rows when available.
3. A user draws an area or uploads GeoJSON; the UI shows exactly the service-accepted sampled points and bounds before plan submission. Invalid geometry is corrected in place.
4. A user selects two datasets; each feasible dataset × point × period output is visible, and unsupported combinations are explained. No source is silently substituted.
5. A user requests a monthly GHI plot from completed EPWs. The chart shows `Wh/m2`, missing-hour coverage and any null/partial values; the action does not fetch weather again.
6. A user downloads one EPW and then all successful outputs. The transfer status and resulting browser download are clear; failed outputs are excluded and reported.
7. A reload retains the safe transcript and active question. Replaying a response, double-clicking Run, or resending after a lost HTTP response creates no duplicate job.
8. Future-weather requests get a concise unavailable response in this UI, and no future plan or job call is made.

## Exclusions and sequencing notes

- No future-weather workflow, historical TMY/XMY generator, arbitrary plot-code execution, public hosting, mandatory distributed services, or standalone provider logic in the browser.
- The post-retrieval conversation/download plan remains a dependency for rich phrases such as “download my 2016 file”; its current draft status must be resolved before that slice is marked complete.
- The browser UI is optional packaging. Python, CLI, REST, and MCP remain usable without installing its build dependencies.
- This plan does not start implementation. Review its scope and delivery order before code work.
