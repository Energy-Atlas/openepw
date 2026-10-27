# Agent request lookups (slots phase a) — design

**Status:** approved by the owner on 2026-10-26, with its plan. Nothing is implemented yet. This is phase (a)
of the [request slots proposal](2026-10-12-agent-request-slots-design.md). Plan:
[agent request lookups plan](../plans/2026-10-13-agent-request-lookups.md).

**Scope:** the agent (`openepw.agent`, agent mode, CLI `openepw chat`). The web chat on Render
staging still runs `chat/coordinator.py` and is not changed; moving it onto the agent (P4/P5 of the
[agent chat design](2026-10-05-mcp-agent-chat-design.md)) is separate and not started. Guided mode
and external MCP clients are not changed.

## 1. Owner answers to the proposal's questions (2026-10-13)

| # | Question | Answer |
| --- | --- | --- |
| 1 | Product preference and years before the location is approved? | **Yes.** Concrete offers still only after approval. Built in phase (b). |
| 2 | Look up offers for a place that is not yet approved (read-only)? | **Yes, labelled.** The answer names the point used and says it is not yet approved; nothing is stored; choosing still needs approval. |
| 3 | Does a slot change keep or reset the plan and its approval? | **Always reset**, as now. |
| 4 | Text typed at an open form | **As now:** text closes the form and becomes its answer (small talk is still intercepted); the model may reopen the form. Phase (c) shrinks to Back per slot. |
| 5 | Phasing | **Phase (a) only**, then the owner decides (b)–(d). |
| 6 | Spec and plan before code | **Yes** (the owner's brief). |

The owner also allowed changes anywhere in `src/openepw/agent/evals/` (tasks, graders, schema),
although another agent is working on the eval framework in parallel; see §7.

## 2. Problem this phase solves

Availability questions ("does NSRDB have 2023 for Ithaca?", "can I get 1950 in Austin?") are
answered only by the product form, after the location review: `weather_product_offers` is reachable
only through the `choose_products` ask-tool, which opens a form and suspends the model. The model
never sees the offers, so it cannot answer in words. The 2026-10-12 label misses G09, G10 and G16
were fixed with a stopgap: the product form states what is listed for the years asked (S50).

Phase (a) lets the model look availability up and answer in words, without a form and without
changing what a plan may contain.

## 3. Design

### 3.1 One new host lookup tool: `look_up_products`

A model tool defined by the host (like the ask-tools and scope tools in `agent/tools.py`), not a
new MCP tool. It calls the MCP tool `weather_product_offers` and returns a compact summary. It opens
no form, stores nothing in the session facts, and is not a gate step.

```text
look_up_products(locations?, years?, product?, provider?)
  locations  a point {lat, lon, name} or a list of up to 25; omitted = the approved locations
  years      calendar years; omitted = the years the person wrote, else the latest full year
  product    historical | tmy | tmyx | published (a filter, as for choose_products)
  provider   a provider name (a filter)
```

Why a host tool and not the MCP tool unhidden:

- The MCP result is built for the product form (option ids, `request` objects, per-location map
  tags) and is cut to 4 KB and 10 list items before the model sees it. A host summary is built for
  answering in words.
- The summary leaves out the `request` objects, so a lookup can never feed a plan. Plans still take
  their datasets from offers the person chose on the product form (`gates.check_plan_request` is
  unchanged).
- `weather_locations_review` and `weather_product_offers` stay hidden from the agent's model
  (`tools.WRAPPED`), so the ADR 0005 rule "a review is always a form" still holds. External MCP
  clients keep both tools, unchanged.

Place candidates are already read-only model tools (`weather_geocode`, `weather_places_preview`,
`weather_place_set`, `weather_places_interpret`). A separate preview of standard-time offsets
before review is not needed for availability answers and moves to phase (b).

### 3.2 Grounding checks (host, before the call)

| Check | Rule | Refusal code |
| --- | --- | --- |
| Points | Each point lies within 0.05° in latitude and longitude of a point the session has seen: a point in a result of `weather_geocode`, `weather_places_preview`, `weather_place_set` or `weather_places_interpret`, a point in the current or approved review, or a decimal coordinate pair the person typed. | `UNGROUNDED_POINT` ("resolve the place with weather_geocode first") |
| No locations | Omitted locations need an approved review. | `GATE_REQUIRED`, need `weather_geocode` (resolve the place first) |
| Years | Every year must be among the years the person wrote (`facts.years`). | `YEARS_NOT_WRITTEN` ("use only years the person wrote, or omit years") |
| Size | At most 25 points per lookup. | `INVALID_ARGUMENTS` |

Refusals go back to the model as tool results (kind `refused`), so they do not count as invalid
calls and do not trigger the guided fallback.

The tolerance, 0.05° (about 5 km), allows the model to round a geocoder's four decimals to two and
still rejects a guessed coordinate for a different place. Seen points are kept in the session state
(`SessionState.seen_points`, capped at 2,000; Back restores the earlier list, so the model may need
to geocode again after Back).

Years keep today's meaning: `_note_years` records every year the person types, including years in a
question ("does it have 2023?"). Those years can later reach a plan, as they can today. Phase (b)
separates "proposed" from "confirmed" years; phase (a) does not change this.

### 3.3 The result the model sees

The shape, with illustrative statuses (labels are the real product labels; the station name and
distance are placeholders, not catalog values):

```json
{"place": {"approved": false, "count": 1,
           "points": [{"name": "Austin, Texas, United States", "lat": 30.27, "lon": -97.74}]},
 "years": [1950], "years_assumed": false, "catalog_loaded": true,
 "products": [{"label": "ERA5 actual year · Open-Meteo", "kind": "actual year", "status": "listed"},
              {"label": "NOAA ISD station observations", "kind": "actual year",
               "status": "not verified; checked when planning", "station": "<station> · <km> km"}],
 "note": "Listed means eligible to try retrieval, not quality assured. Products not shown are not offered for these places and years. Nothing is chosen: to get files, review the location and choose products on the form."}
```

- `status` comes from the offer counts: `listed` (all places), `listed at k of n places`, or
  `not verified; checked when planning` (no catalog evidence). A product the catalog does not list
  for these places and years is left out, as on the product form. Without a loaded catalog,
  `catalog_loaded` is false and the note says most products are not verified here.
- Station products carry the station and distance for one place, as on the product form.
- At most 5 points and 30 products are listed; counts give the rest.
- Outside strings (names, labels) pass `guard.clean_tool_data` and the result is marked as data, as
  for every tool result (`tools.shape`).

### 3.4 The label for a place that is not approved (owner answer 2)

When a lookup runs for points that are not the approved review, the host shows a fixed line before
the model's answer, once per distinct set of points in the session:

> Availability checked for Austin, Texas, United States (30.270, -97.740); this location is not
> approved yet. You'll confirm it before choosing products.

The line names at most three places, then "and N more". It is an `assistant` event with code
`LOOKUP_UNAPPROVED`. The host writes it, not the model, because the model does not reliably write
text beside tool calls (the reason `decline_part` is a host tool). A lookup for the approved
locations shows no label.

### 3.5 Prompt changes

- The scope line "Questions about availability … the product form states what is listed" becomes:
  "Questions about availability (which products or years exist for a place): resolve the place, call
  look_up_products and answer in words from its result only. Do not open a form unless the person
  asks for files."
- Rule text "For 'what is available' questions review the location and use choose_products without
  planning" is replaced by: "A lookup chooses nothing: to get files, the person still approves the
  location (review_location), chooses products (choose_products), gives years and runs the plan
  (review_plan)."
- Rule 2 ("after approval call choose_products; the person chooses") is unchanged.

### 3.6 Unchanged guarantees

- Plans are built only from the approved review, offers chosen on the product form and years the
  person wrote (`gates.build_requests` and `check_plan_request` are unchanged).
- One approval answers one submission (`host.run_plans` is unchanged).
- Host-only tools stay host-only (`mcp.access` is unchanged; `look_up_products` is not an MCP tool).
- Guided mode does not see the lookup and stays deterministic.
- Text at an open form behaves as now (owner answer 4).

## 4. Events and tracing

- The lookup emits `tool` events named `look_up_products` (`by: model`). Its inner
  `weather_product_offers` call is recorded with `by: lookup`, so graders and traces can tell a
  lookup from the product form's call.
- Refusals emit a `tool` event with `phase: refused` and the refusal code, like gate refusals.

## 5. Cost

One more model step for an availability question (geocode, lookup, answer). Requests that go
straight to files are unchanged. The lookup reads the local catalog only: no live provider calls,
in line with the owner's rule of no live point checks at product-list time.

## 6. Later phases (for context; not designed here)

- **(b)** Slots with value, origin, status (proposed, confirmed, stale) and source event; years and
  product preference before the place (owner answer 1); targeted invalidation, with the plan and its
  approval always reset (answer 3); a location-offset preview lookup. Existing tasks whose
  `forms_in_order` or `tools_in_order` assume a fixed order then move towards outcome checks.
- **(c)** Back per slot only (answer 4 keeps text-at-form behaviour).
- **(d)** Guided-mode parity.

## 7. Evals

- **S50** (availability question, "Can I get actual-year weather for 1950 in Austin?") gets
  mode-specific graders: in agent mode, a lookup answer (`tools_in_order` [`look_up_products`],
  `codes_present` [`LOOKUP_UNAPPROVED`], `reply_contains` [`1950`], no product form, nothing
  submitted); in guided mode, the product form's availability line, as now. Its offline script moves
  to the lookup path.
- **New tasks:** the product form's availability line in agent mode for a request (the old S50 path);
  a provider question ("does NSRDB have 2023 for Ithaca, NY?") answered without a form; a lookup
  after approval that shows no label and then continues to the product form and a plan.
- **New grader:** `forms_absent` (none of these form kinds was shown). New coverage ids for the
  lookup and its label.
- **Refusals** (ungrounded point, unwritten years, no approved locations, a plan after a lookup
  without a product choice) are unit tests, not eval tasks: a live model rarely produces them, so
  live trials would test nothing.
- No other existing task changes in phase (a): lookups add steps, and the order graders check
  subsequences.
- **Coordination:** the owner allowed changes to `evals/`. The changes are kept small and additive
  (one grader, coverage ids, task files) so they merge easily with the parallel eval-framework work.

## 8. Documentation

ADR 0005 gains a dated note (lookups are read-only, open no form and record nothing; reviews and
choices are still forms). The agent README describes the lookup and its label. The slots proposal
records the owner's answers and links this spec.
