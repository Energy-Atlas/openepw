# Agent request slots (slots phases b–d) — Plan

**Status:** written 2026-10-30 in phase 3 of the
[outstanding work plan](2026-10-30-outstanding-work.md). **Approved by the owner on 2026-10-31**
("Approved with the defaults you specified. Keep $1 spending cap. Start implementing phase 4."),
which ended phase 3. Implemented in phase 4 on `feature/agent-request-slots`; execution notes in §4.
Design and owner answers: [spec](../specs/2026-10-30-agent-request-slots-design.md) (§1, open
questions §14).

**Branch:** `feature/agent-request-slots`, created from `main` when phase 4 starts. Nothing is merged
into `main` or `deploy/staging` without the owner's go-ahead. Production (`feature/render-deploy`)
is not touched.

**Scope:** `src/openepw/agent/` (both modes and the CLI), its evals and docs. The web chat
(`web/chat-ui`, `chat/coordinator.py`), REST, the MCP server and `mcp/access.py` are not changed.

**Prerequisites:** the owner approves this plan and the spec, with any changes to the §14 defaults;
and sets a live check cap (suggested $1).

## 1. Decisions this plan builds on

- Four parts (place, preference, products, years) with derived statuses and stored origins
  (spec §3); values stay in the existing `Facts` fields.
- Targeted resets through one `Facts.change` (spec §4); any change resets the plan and its approval.
- Years in a question are proposed; plans use confirmed years only (spec §5).
- Request summary form and Change actions, handled by the host in both modes (spec §6).
- "Can I get …" handled by instructions, not a gate (spec §7).
- Guided mode gains the same parts and Change, and stays deterministic (spec §8).

## 2. Tasks

Each task is test-first where it changes behaviour. It ends with ruff, mypy and pytest passing,
plus the offline evals from task 3 onwards. Commits use `fix(agent): …` (or `fix(evals): …`,
`fix(docs): …`) with normal authorship and no trailers.

### Task 1 — Parts, statuses and origins (about 0.5 day)

- `state.py`: `Facts.proposed_years`, `Facts.origins`, `Facts.recheck`, all defaulted;
  `Facts.change(part, value, *, by, seq)` applying spec §4; `set_geography` stops clearing
  `chosen` and marks `recheck`.
- New `slots.py` (or functions in `state.py`): `parts(facts) -> list[Part]` with derived status
  and origin, used by the state block, the summary form and graders.
- Tests: each row of spec §4; status derivation; an old session JSON without the new fields loads
  and plans as before (spec §11, task 9).

### Task 2 — Questions and proposed years (about 0.5 day)

- `text.py`: `reads_as_question` (spec §5.1), with a table test of answers and questions.
- Agent `_note_years` and guided `_read_time_and_product` record proposed or confirmed years.
- `gates.py`: `build_requests` and `check_plan_request` use confirmed years and refuse a
  `recheck`; `next_need` returns `confirm_request` (spec §6.1); `NEED_TOOL` gains
  `confirm_request → review_request`.
- Confirmation by a form that shows the value (spec §5.4, open question 1): the product form
  answer confirms the years in its availability line.
- Tests: S55's input never plans 2018 without a confirmation; a plain "2018" still plans at once.

### Task 3 — Request summary and Change (about 1.5 days)

- `interactions.py`: form kind `request_summary`.
- `host.py`: `request_form(facts)`; the plan review gains `data.parts` and `change:<part>`
  options; the product form gains `data.selected` and `data.recheck`.
- Host Change path shared by both policies (spec §6.3): plan reset, pending call closed with
  `person_changed`, the part's form opened, a snapshot for Back; refused after a job started.
- Agent: ask-tool `review_request`; the `_answer_result` for the summary (approve confirms the
  proposed values; change goes to the host path).
- Guided: `confirm_request` opens the summary; deterministic "show my request" phrases.
- Tests: every Change from the plan review and the summary, in both modes; Back after a Change;
  Run still approves exactly the plans shown.

### Task 4 — Model context and instructions (about 0.5 day)

- `_state_block` becomes the parts table (spec §9); `_replied` adds `proposed_years` and the hint
  (spec §5.3).
- `_scope` and `_RULES`: "can I get" as lookup then form (spec §7); proposed parts confirmed
  before planning.
- Tests: snapshot of the state block for each status; the instruction text names
  `review_request`.

### Task 5 — CLI (about 0.5 day)

- `render_form` for `request_summary` and the parts list on `plan_review`; `parse_reply` reads
  "ok" and "change <part>"; `/request` command; `/help`.
- Tests: rendering and parsing for each part; `/request` with nothing proposed.

### Task 6 — Evals (about 1 day)

- Runner answers `request_summary` and `change:<part>` (spec §11); lint knows the new form kind,
  ask-tool and grader.
- Grader `part_status` (`PART_STATUS`).
- S50 and S55 updated; nine new tasks from spec §11 (S56 onwards), with coverage ids.
- Offline: guided, agent scripted under `local` and `hosted`, all passing.

### Task 7 — Live check (within the owner's cap)

- Spec §11 live set, 3 trials each, hosted profile, after asking the owner. Records go to
  `.local/openepw/evals/`, results and spend to §4 of this plan.
- Misses that are model judgement (for example skipping the lookup for "can I get") are recorded
  and tracked as soft checks, as in phase (a). Hard checks (no unconfirmed plan, nothing submitted
  without Run) must pass.

### Task 8 — Documentation (about 0.5 day)

- ADR 0005 note; agent README (forms, gates, parts, CLI commands, evals); ARCHITECTURE; FEATURES;
  limitations (web needs P4; sessions after phase 4 cannot be read by older code); the proposal's
  and this plan's status lines; the outstanding work plan's phase 4 notes.

### Task 9 — Verification and report

- Full checks; execution notes in §4; the branch pushed; a report for the owner's review with what
  changed, deviations and the live results.

Total about 5 days, as estimated in the outstanding work plan.

## 3. Risks and limits

- **No web change:** people on staging use the legacy web chat and see none of this until P4.
- **Live model behaviour:** "can I get" handling depends on the model following instructions; the
  gate guarantees safety, not the extra lookup.
- **Session compatibility:** forward only (spec §3.3).
- **Eval churn:** S50 and S55 change; other `forms_in_order` tasks should not, since the summary
  appears only for proposed parts. Any task that changes is listed in §4 with the reason.
- **Merge overlap:** none expected; `src/openepw/agent/` has no other open branch as of 2026-10-30.

## 4. Execution notes

### Phase 4 (2026-10-31)

Started on the owner's word ("Approved with the defaults you specified. Keep $1 spending cap.
Start implementing phase 4."). Branch `feature/agent-request-slots` from `main` (`a0ce906`).
Commits: `9b6142b` (tasks 1–6), `8daf71e` and `9466a4e` (fixes from the live check), then this
documentation and the S56 grader change.

**Built (tasks 1–6, 8).**
- `state.py`: `Facts.proposed_years`, `origins`, `recheck` (defaulted), `confirmed_years`,
  `Facts.change` and `confirm_years`; `set_geography` keeps the chosen products to recheck.
- New `slots.py`: derived statuses, part values and origins in words, the request summary form
  and the Change options.
- `gates.py`: plans use confirmed years; `recheck` and proposed years block a plan (need
  `choose_products` or `confirm_request`); `NEED_TOOL` maps `confirm_request → review_request`.
- `text.reads_as_question`; agent `_note_text` (years and product words) and guided
  `_read_time_and_product` record proposed years.
- `host.py`: `fetch_offers`, `refresh_offers` (new years or preference: still-offered products
  stay confirmed, others `recheck` with `PRODUCTS_RECHECK`), `choose` (confirms the years the
  product form shows), `confirm_request`, `change_part`, `answer_summary`, `place_form`; the plan
  review gains `data.parts` and Change options; the product form gains `data.selected` and
  `data.recheck`; the years form hint shows the current years.
- Agent: ask-tool `review_request`; parts table in the state block; `_replied` adds
  `proposed_years` and the hint; instructions for "can I get" and confirmed parts; Change answers
  go to the host path; text at a Change form is read by the host rules.
- Guided: Change, the summary (need `confirm_request` and "show my request"), targeted resets.
- Session: `show_request` / `open_request_summary` (with `return_to`); store `last_seq`.
- CLI: `/request`, `ok` and `change <part>` at the summary and plan review, `ok` keeps a
  preselection, `[selected]` marks.
- Evals: form kind `request_summary`; runner answers `change:<part>`, lists of review answers
  used in turn, and `selected`; setup `unlisted` (offers the stub does not list for some years);
  grader `part_status` (`PART_STATUS`) with fixtures; coverage ids `slots.*`; tasks S56–S63 and
  changes to S50 and S55; mutations `questions-off`, `confirmation-off`, `recheck-off`,
  `change-off`, each caught by at least one task.

**Routine choices and deviations.**
- Origins add `model` to `text | form | host`: a preference set only by the model's filter is
  `proposed`, which needs a distinct origin.
- Approving the summary confirms years and a model-set preference, not the place: a place is
  confirmed only on the location review, which shows the standard-time offsets.
- Proposed years are kept in `years` and fetched with the offers, so the product form can show
  them and confirm them (§5.4); any years change drops the stored offers, which are fetched again
  before the next plan.
- Guided mode still clears the years when only typical-year products are chosen (existing rule);
  the design's "years kept" applies to agent mode and to place and preference changes.
- The summary opened by `/request` remembers the open form (`return_to`); in agent mode approving
  it reopens that form (a model question stays open); in guided mode the host continues in gate
  order.
- In agent mode, text typed at a form opened by a Change is read by the host's guided rules, so
  "2019" at the Change years form needs no model call. Other host-opened forms are unchanged.
- Adding `Setup.unlisted` changes every task's hash (its default is part of the dump), so eval
  comparisons with earlier baselines show all tasks as changed.
- The approval result gains a `next` hint and the state block says the product form confirms the
  years it shows; both came from the live check below.

**Live check (task 7).** Hosted profile, model `gpt-6-luna`, stub providers, 3 trials each of S50,
S55, S56, S57 and S61. Records in `.local/openepw/evals/2026-10-31-slots-live*` (ignored).

| Run | Code | Result | Cost |
| --- | --- | --- | --- |
| `slots-live` | `9b6142b` | 9/15: S55, S56, S57 3/3; S50 0/3 (after approval the model wrote "choose a product" without opening the form); S61 0/3 (task asked for TMYx, which the stub never offers; the model rightly opened no form) | $0.059 |
| `slots-live-2` | approval hint, S61 rephrased | S61 3/3; S50 0/3 (the model now showed the request summary before the product form) | $0.015 |
| `slots-live-3` | state-block hint | S50 3/3, S55 3/3 (lookup skipped twice, soft) | $0.027 |
| `slots-live-final` | `8daf71e` | 11/15: S50 0/3 (text instead of the form again); one S55 trial reviewed the approved place again after the lookup, then asked in text | $0.059 |
| `slots-live-final-2` | `9466a4e` | 14/15 as graded then; S56 #3 took a valid other path (years asked before the review, confirmed on the product form) and passes under the revised S56 graders (re-graded from the record) | $0.063 |

Total spend about $0.22 of the $1 cap. In every trial of every run the hard safety checks held:
no plan used a year that was only asked about, nothing was submitted without Run, and no host-only
tool ran for the model. The remaining variation is model judgement (stopping with text where a
form should open), tracked as soft checks in S50 and S56 as task 7 provides.

**Not done.** No web change (P4 is not in any phase; the owner did not decide question 4).
Nothing is merged into `main` or `deploy/staging`.
