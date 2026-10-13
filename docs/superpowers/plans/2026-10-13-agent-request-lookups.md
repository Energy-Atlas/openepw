# Agent request lookups (slots phase a) — Plan

**Status:** draft for the owner's approval, 2026-10-13. Not started. Design and owner answers:
[spec](../specs/2026-10-13-agent-request-lookups-design.md) (§1).

**Branch:** `feature/agent-request-lookups`, created from `main` at 6a9f53d. Not merged into
`main` or `deploy/staging` without the owner's go-ahead. Production (`feature/render-deploy`) is
not touched.

**Scope:** agent mode only (`src/openepw/agent/`), its evals and docs. Guided mode, the MCP server,
`mcp/access.py`, the web chat (`chat/coordinator.py`) and REST are not changed.

## 1. Decisions this plan builds on

- One host lookup tool, `look_up_products`; no MCP tool is added or unhidden (spec §3.1).
- Host grounding checks: seen points within 0.05°, years the person wrote, at most 25 points
  (spec §3.2).
- A fixed host label for a place that is not approved, code `LOOKUP_UNAPPROVED` (spec §3.4).
- Plans, approvals, gates and guided mode are unchanged (spec §3.6).
- Eval changes are small and additive: one grader, coverage ids, S50's graders split by mode and
  three new tasks (spec §7).

## 2. Tasks

Each task ends with ruff, mypy and pytest passing, plus the offline evals in task 4 onwards, and a
commit `fix(agent): …` (or `fix(evals): …`, `fix(docs): …`) with normal authorship and no trailers.

### Task 1 — Seen points

- `agent/text.py`: `written_points(text)` returns decimal coordinate pairs the person typed
  ("42.44, -76.5", "42.44 -76.50"), within the valid ranges.
- `agent/state.py`: `SessionState.seen_points: list[tuple[float, float]]`, capped at 2,000 (oldest
  dropped).
- `agent/policy_model.py`: after a successful `weather_geocode`, `weather_places_preview`,
  `weather_place_set` or `weather_places_interpret`, and after each `review_location`, record the
  points found in the result's data (a bounded walk over `lat`/`lon` and `latitude`/`longitude`
  pairs). Typed text adds `written_points` in `on_text` and in a form answered with text.
- Tests (`tests/agent/`): `written_points` cases (pairs, ranges, years not taken for coordinates);
  points recorded from a stubbed geocode and a review; the cap.

### Task 2 — `look_up_products`

- `agent/tools.py`: `LOOKUP_TOOLS` with the tool's schema (spec §3.1); `model_tools` lists it in
  agent mode. `WRAPPED` is unchanged.
- `agent/host.py`: `lookup_summary(data, approved, points)`, building the result in spec §3.3 from
  `weather_product_offers` data (statuses from `available`/`unverified`/`sites`, the station for
  one place, at most 5 points and 30 products, the fixed note), and `lookup_label(points)` for the
  fixed line.
- `agent/policy_model.py`: `_execute` sends `look_up_products` to a new `_lookup`:
  1. locations: the arguments, or the approved review's geography; neither is `GATE_REQUIRED`;
  2. checks: more than 25 points is `INVALID_ARGUMENTS`; points not seen are `UNGROUNDED_POINT`;
     years not written are `YEARS_NOT_WRITTEN` (refusals are kind `refused`);
  3. `s.tool("weather_product_offers", by="lookup", …)` with years defaulting to `facts.years`;
  4. if the points are not the approved review's, emit the label once per distinct point set
     (`SessionState.shown_notices`, keyed by a short hash of the rounded points);
  5. return `lookup_summary` through `tools.shape`'s cleaning and data marking.
  `facts` is not modified.
- Tests: unapproved lookup (label once, facts unchanged, no form); approved lookup (no label);
  omitted locations without approval (`GATE_REQUIRED`); ungrounded point; unwritten years; over 25
  points; catalog not loaded (note and statuses); `weather_plan` after a lookup without a product
  choice still gets `GATE_REQUIRED` `choose_products`; the inner call is recorded `by: lookup`.

### Task 3 — Prompt

- `agent/policy_model.py`: the availability sentence in `_scope` and the "what is available" rule
  in `_RULES` change as in spec §3.5. `GREETING` is unchanged.
- Tests: the existing prompt tests are updated; the tool-list hash in eval records changes (expected).

### Task 4 — Evals

- `evals/graders.py`: `forms_absent` (failure code `UNEXPECTED_FORM`): none of these form kinds was
  shown. A grader fixture in `grader_fixtures.yaml`.
- `evals/coverage.yaml`: `lookup.products` and `lookup.label`.
- `S50`: agent-mode graders (`tools_in_order` [`weather_geocode`, `look_up_products`],
  `codes_present` [`LOOKUP_UNAPPROVED`], `reply_contains` [`1950`], `forms_absent`
  [`product_choice`, `plan_review`], `submitted` false), and the form-line graders for guided mode
  only. The script moves to geocode, lookup and an answer.
- New tasks (next free ids, agent mode):
  - the product form's availability line for a request ("AMY 1950 for Austin"), the old S50 path;
  - "Does NSRDB have 2023 for Ithaca, NY?" answered after a lookup with no form;
  - approve Ithaca, then "what's available for 2018 here?": a lookup without a label
    (`codes_absent` [`LOOKUP_UNAPPROVED`]), then choose products and a plan; only Run submits.
- Checks: `openepw eval lint`, `openepw eval` (guided, offline) and
  `openepw eval --mode agent --scripted` under the `local` and `hosted` profiles; all tasks pass.
  `openepw eval catalog` is regenerated if its output is tracked.

### Task 5 — Documentation

- ADR 0005: a dated note (spec §8).
- `docs/agent/README.md`: the lookup, its checks and label; the task count.
- The slots proposal: owner answers recorded, link to this spec; phase (c) reduced to Back per slot.
- The agent chat design (`2026-10-05`): a one-line pointer to this spec where it describes the
  wrapped tools.
- `FEATURES.md` and `ARCHITECTURE.md`, if they describe the agent's tools.

### Task 6 — Verification and report

- Full ruff, mypy (never piped into `tail`) and pytest runs; the offline eval runs from task 4.
- Report results to the owner, with the limits below. No merge, push to `deploy/staging` or deploy
  without the owner's go-ahead. Pushing the feature branch to `origin` is a backup only.
- **Live check (opt-in, asks the owner first):** S1, S12, S50 and the three new tasks, 3 trials each,
  hosted profile. That is about 18 trials, a few cents at the 2026-10-12 rate (about $0.20 for 132
  trials), capped with `--max-cost 1`.

## 3. Risks and limits

- **Years from questions.** A year in a question ("does it have 2023?") is recorded as a written
  year and can reach a later plan, as today. Phase (b) adds proposed and confirmed years.
- **Seen points after Back.** Back restores the earlier list; the model may need to geocode again.
- **Offline evals** use the stub service without a catalog, so lookup statuses offline are "not
  verified". Catalog-backed statuses are covered by unit tests with a stubbed offers result, and
  live only through the opt-in check.
- **Parallel eval work.** The owner allowed eval changes. Conflicts with the other agent's branch are
  most likely in `graders.py` (one added grader), `coverage.yaml` and S50. They are resolved at merge
  time, keeping both sides.
- **Web chat.** Staging's web chat does not use the agent, so nothing here is visible on staging.

## 4. Execution notes

(Filled in while the work runs: findings, assumptions, deviations and results.)
