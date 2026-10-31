# Agent request slots (slots phases b–d) — Plan

**Status:** draft for the owner's review, written 2026-10-30 in phase 3 of the
[outstanding work plan](2026-10-30-outstanding-work.md). The owner's approval ends phase 3; the
tasks below are phase 4. Design and owner answers:
[spec](../specs/2026-10-30-agent-request-slots-design.md) (§1, open questions §14).

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

(Phase 4.)
