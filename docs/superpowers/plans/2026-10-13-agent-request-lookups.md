# Agent request lookups (slots phase a) — Plan

**Status:** **approved by the owner on 2026-10-26** (decision 1 of the branch review, in
conversation). Implemented and verified on 2026-10-27 (tasks 1–6; results in §4). Merged into `main` (`0483872`)
and `deploy/staging` (`3ac7e3d`) on 2026-10-30 with the owner's go-ahead. The owner also asked for this plan and its spec to be
merged into `main` before implementation. Design and owner answers:
[spec](../specs/2026-10-13-agent-request-lookups-design.md) (§1).

**Branch:** `feature/agent-request-lookups`, created from `main` at 6a9f53d. The implementation is
not merged into `main` or `deploy/staging` without the owner's go-ahead. Production (`feature/render-deploy`) is
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

2026-10-27, on `feature/agent-request-lookups` after merging `main` (`f0d11e0`, a fast-forward):

- **Seen points are recorded in the session,** not in `policy_model`: `AgentSession.tool` records
  the points in results of `weather_geocode`, `weather_places_preview`, `weather_place_set`,
  `weather_places_interpret` and `weather_locations_review`, whoever called them; typed text and
  text or map answers at a form add theirs. Guided-mode steps and map answers therefore count too,
  which matters after a switch from guided to agent mode.
- **Typed coordinates** are read only as decimal pairs ("42.44, -76.5") or hemisphere pairs
  ("42.44N 76.5W"), so years and counts are never coordinates. Seen points are kept once each to
  four decimals.
- **The lookup's note** is the host's own text and is not passed through the outside-text cleaning
  (which cut it to 120 characters); names, labels and stations are.
- **Offline statuses:** the eval stubs carry bundled coverage, so offline some products are
  `listed` although `catalog_loaded` is false. The risk note in §3 assumed all were "not verified".
- **S12** ("what's available in Phoenix?") is an availability question as well. With the new
  instructions a model answers it with a lookup, so S12 gets per-mode graders like S50 (agent: geocode,
  lookup, no product or plan form; guided: the product form). The spec said no other task changes.
- **S55** asks "What's available for 2018 here?" at the years question, because the eval runner
  answers each form kind the same way; the text answer records 2018, the lookup for the approved
  place shows no label, and the plan and Run follow.
- **Eval lint** knows `look_up_products` and checks `forms_absent` values against the form kinds.
- Commits: `87ecea7` (seen points), `d33e86a` (lookup), `86babc7` (instructions), `0baf65f` (evals),
  then the docs.

**Verification (task 6, 2026-10-27).**
- ruff and mypy clean; pytest 1,080 passed, 20 skipped; `eval lint` 43 tasks, no issues; offline
  evals: guided 25/25, agent scripted 43/43 under `local` and under `hosted`.
- **Live check** (owner-approved, hosted profile, `gpt-6-luna`, 3 trials each; records in
  `.local/openepw/evals/2026-10-27-lookups-live-hosted*`): first run 12/18 for $0.050. S1, S12,
  S53 and S54 passed every trial; S12 and S54 answered with a lookup and no form.
  - **S50 failed 3/3:** the model read "Can I get actual-year weather for 1950 in Austin?" as a
    polite request for files and went to the product form, whose availability line also answers.
    Making the instructions force a lookup would risk turning real requests into lookups, so S50
    now requires what both paths share (`shown_contains` 1950, no plan, nothing submitted) and
    tracks the lookup, its label and the absence of forms as soft checks. New grader
    `shown_contains` (code `MISSING_SHOWN_TEXT`): a reply, notice or form shows the text.
  - **S55 failed 3/3 on order only:** typed at the years question, "What's available for 2018
    here?" is also a years answer, and the model planned straight away. Its hard checks (no label,
    years 2018, submitted only by Run) passed; the lookup order is now soft.
  - Re-run of S50 and S55: 6/6 for $0.020 (soft misses recorded). Total live spend $0.07.
- **Finding for phase (b):** with the current instructions the model answers clear questions ("what's
  available", "does NSRDB have …") with a lookup, but treats "can I get …" and questions typed at a
  form as requests. Proposed and confirmed slots (phase b) would let a question at a form be answered
  without closing it.
