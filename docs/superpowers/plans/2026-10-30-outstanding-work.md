# Outstanding work after the 2026-10-30 release — phase plan

**Status:** phases and their contents agreed with the owner on 2026-10-30 ("Valid findings … group
them by phases"; "Ensure these plans are written down"). Each phase starts only on the owner's word, with the
prerequisites listed for it.

| Phase | State |
| --- | --- |
| 1 | Done 2026-10-30. The test isolation fix (`fix/offline-test-isolation`) was merged into `main` on the owner's go-ahead the same day |
| 2 | Deferred, not worked (owner, 2026-10-30): LangSmith is not available for now |
| 3–7 | Not started |

This list replaces the scattered open items in the older plans. Each item names its source so that
detail stays where it was first written.

## How each phase runs

- The agent implements a phase on its own, without supervision, up to the phase's end. It then
  stops for one owner review.
- Each phase uses one purpose-named branch from `main`, which is pushed at the end. A phase that
  produces a spec or plan for approval stops there; building it is a later phase.
- Repository rules apply throughout: [AGENTS.md](../../../AGENTS.md); `fix(topic): description`
  commits with normal authorship and no trailers; ruff, mypy, pytest and the offline evals before
  each commit.
- Merging into `main` or `deploy/staging`, pushing open-data, Render pins, deletions and any spend
  stay with the owner. Live model runs and research requests only go ahead within the cap or budget
  approved for that phase.
- Findings, assumptions and deviations go into the phase's execution notes, in this file or in a
  plan the phase creates. Chat history is not project memory.
- Effort is the agent's working time, excluding owner review, and is a rough estimate.

## Phase 1 — Docs and test cleanup (about half a day)

Branch: `docs/phase-1-cleanup`. Prerequisites: none.

Owner answers (2026-10-30):
- **Merge:** at the end, the phase's docs-only changes and this plan may merge into `main` without
  a separate go-ahead. `deploy/staging` is not touched. Any code change still waits for the
  owner.
- **ROADMAP:** restructure it into short sections for each completed line of work (MCP stages,
  agent chat, availability, staging) with links, then the phases. Condense the long paragraphs;
  the history stays in git and the linked records.
- **Flaky test:** up to about one hour of machine time. That allows several full runs, some in
  random order or under parallel load, then targeted reruns.
- **Cleanup (1.4, added):** delete the merged branches `feature/agent-request-lookups`,
  `feature/availability-followups` and `docs/record-staging-pin`, locally and on origin, and their
  worktrees. Each is first confirmed fully merged into `main`; nothing unmerged is deleted.
  `feature/webui`, `feature/account-login` and `feature/render-deploy` are never touched.

| # | Item | Source | Done when |
|---|---|---|---|
| 1.1 | Bring the ROADMAP up to date with the agent chat, availability and staging work since Stage 6, and link this plan | [ROADMAP](../../../ROADMAP.md) | ROADMAP lists these phases and their status |
| 1.2 | Fix stale status lines: the [slots spec](../specs/2026-10-12-agent-request-slots-design.md) ("not merged"), the [evals design](../specs/2026-10-10-agent-evals-design.md) ("Not built yet") and the [NSRDB geospatial design](../specs/2026-09-24-nsrdb-geospatial-availability-design.md) ("owner review is required"; check whether the 2026-10-13 coverage masks superseded it) | the documents | Each status matches what is in `main` |
| 1.3 | Find the flaky test: one failure in a slow 8-minute run on 2026-10-30, none on rerun. Rerun the suite under load and record any failure | 2026-10-30 release | The test is named and fixed, or documented as timing-sensitive |
| 1.4 | Delete the merged branches and their worktrees (see the owner answers above) | Owner answer 2026-10-30 | Each confirmed merged, then deleted locally and on origin |

## Phase 2 — Finish the agent evals (about 3 days)

**Deferred, not worked (owner, 2026-10-30):** "Let's say langsmith is not available for the
moment - can we mark this stage as unworked and continue to the next stage?" Nothing in this phase
was started. When it resumes, 2.1 (task 10) and the offline part of 2.3 need no LangSmith; 2.2 does,
and the live judge pass in 2.3 still needs a cap.

Branch: `feature/agent-evals-judges`. Source: the [agent evals plan](2026-10-10-agent-evals.md),
tasks 8–11, which wait there.

Prerequisites:
- A LangSmith key, or 2.2 stops at the fake-client tests.
- The owner confirms that LangSmith calls are allowed. The MCP stage roadmap ruled them out; the
  later evals plan approves E3.
- A spending cap for one live judge pass (suggested $2).

| # | Item | Done when |
|---|---|---|
| 2.1 | Task 10: `openepw eval grade-sessions` grades saved real chat sessions with the always-on rule graders | Runs offline and finds a planted invariant break |
| 2.2 | E3, task 8: live eval runs go to LangSmith as a dataset and experiments with grader feedback | Tested with a fake client; offline and scripted runs are never sent; a tracing failure never fails an eval |
| 2.3 | E5, task 9: model judges for wrong declines, unsupported availability claims, answer correctness and helpfulness. They are calibrated against the owner's labels in `.local/openepw/labelling/pack-2026-10-12/labels.reviewed.csv` | Agreement and Cohen's kappa reported; judges stay soft; one live judge pass recorded within the cap |
| 2.4 | Task 11: the agent README (evals, testing and trace guides), ARCHITECTURE, FEATURES, limitations and the evals plan's execution notes | Updated |

This phase was meant to come before phase 4, so the slots work is measured with the judges. While
it is deferred, phase 4 measures the slots with the rule graders only (see 4.2).

## Phase 3 — Design request slots (b)–(d) (about 1 day)

Branch: `docs/agent-request-slots`. Source: the
[slots proposal](../specs/2026-10-12-agent-request-slots-design.md) §5–§6. The owner's 2026-10-13
answer (6) requires a spec and plan before code; their approval ends this phase.

| # | Item | Done when |
|---|---|---|
| 3.1 | Phase (b): each request part has its own status and origin, parts can be answered in any order, and a change resets only the parts that depend on it. It must cover the live-check finding of 2026-10-27: "can I get …" and text typed at an open form are taken as requests, not lookups (S50, S55) | Spec and plan with open questions |
| 3.2 | Phase (c): forms that do not block; Back for each slot. Text at an open form stays its answer (owner answer 4) | Same documents |
| 3.3 | Phase (d): guided-mode parity, keeping guided mode deterministic | Same documents |

The guarantees from the original brief stay:
- plans are built only from confirmed values;
- one approval per submission;
- host-only tools stay host-only;
- guided mode stays deterministic.

## Phase 4 — Build request slots (about 5 days)

Branch: `feature/agent-request-slots`. Prerequisites: phase 3 approved; a live check cap (suggested
$1).

| # | Item | Done when |
|---|---|---|
| 4.1 | Build (b), (c) and (d) to the approved phase 3 plan | ruff, mypy, pytest and the offline evals pass |
| 4.2 | Eval tasks for the slots, with phase 2 judge checks if phase 2 has been done by then; otherwise rule graders only | Agent and guided suites pass offline |
| 4.3 | Live check | Results recorded within the cap |
| 4.4 | Agent README, ARCHITECTURE, FEATURES, and an ADR or ADR amendment | Updated |

## Phase 5 — Conversations after a download (about 3–4 days)

Branch: `feature/post-download-conversations`. Source: the
[post-retrieval conversations plan](../../plans/2026-09-26-post-download-conversations.md), whose
status is still "planned". The phase first updates that plan against later decisions: the agent
chat, the web chat and the accounts on staging. A material conflict is escalated before code.

| # | Item | Done when |
|---|---|---|
| 5.1 | Download finished artifacts to the person's own disk from the chat | Works over REST, MCP and the CLI through the shared service |
| 5.2 | Analytical follow-ups: factual questions and structured summaries about retrieved data | Follow-ups keep the same job, output, location and year, with no new provider retrieval |
| 5.3 | Evals and docs | Pass offline; docs updated |

## Phase 6 — Availability data, round 3 (about 4–5 days, about 2.5 without 6.5)

Branch: `feature/availability-round-3`. Sources: the
[2026-10-27 record](../../validation/availability-followups-2026-10-27/README.md) ("For the owner's
review", "What this does not establish") and [ROADMAP](../../../ROADMAP.md) (GHCNh).

Prerequisites:
- A research budget (suggested: 40 metadata requests, 10 probes, 150 MB, 10 OneBuilding
  downloads).
- Whether 6.5 is in: the owner deferred GHCNh on 2026-10-27 (Q6).

| # | Item | Done when |
|---|---|---|
| 6.1 | Read the 7 unparsed workbook rows (2 CWEC, 3 TMY, 1 IMGW, 1 ITMY) | Parsed, or documented as unreadable |
| 6.2 | Re-check the 5 left-out families (CTZ2016, CTZ2022, CTZ2025, LuxTMY, ITMY) against OneBuilding's current pages | Added if the published paths now resolve; paths are never guessed |
| 6.3 | Near-shore sea for PVGIS: a few probes to test a sea-distance rule | Rule adopted, or points stay unknown, with the evidence recorded |
| 6.4 | Himawari-8 re-binning at 2–3 more places and years | Results recorded against the 1% annual and 10% hourly RMSE thresholds |
| 6.5 | GHCNh successor adapter and inventory (only if the deferral is lifted) | Offline tests and one live acceptance |
| 6.6 | New catalog generation, matrix, memory check, round trip; open-data package on a local branch | Ready for the owner to push and pin |

## Phase 7 — Platform and science backlog (about 2 days for 7.1–7.2, 3–4 days for 7.3)

Branch: `feature/platform-backlog` (7.1–7.2) and `feature/science-backlog` (7.3–7.5). Source:
[ROADMAP](../../../ROADMAP.md), "Follow-ups after v0.1". It may be split into two reviews.

| # | Item | Done when |
|---|---|---|
| 7.1 | Linux and macOS CI, and an EnergyPlus smoke check on a generated EPW | CI passes on GitHub; EnergyPlus reads the file |
| 7.2 | A job retention and cleanup policy | Implemented and documented |
| 7.3 | More NSRDB products and intervals; DNI/DHI derivation for CDS data | Validated against reference data, with limits recorded |
| 7.4 | Reuse previous verified runs to speed up repeat requests | Design only |
| 7.5 | Sampled future-weather generators | Design only; unclear scientific choices are escalated |

## Owner decisions outside the phases

| Item | Why it is the owner's |
|---|---|
| The 4 owner-reviewed TMY files with new coordinates; near-shore sea behaviour | Owner review list of 2026-10-27 |
| OneBuilding redistribution terms; the ISHRAE, CSWD and RMY terms; MetEireann | Licensing |
| Telling OneBuilding that the CTZ and LuxTMY published paths return 404 | An external message |
| Production promotion (`feature/render-deploy`) and accounts | Owner said no promotion for now |
| `feature/webui` (49 unique UI commits) and `feature/account-login` | Owner's branches |
| Deleting merged branches | Deletion needs explicit approval; the three merged branches were approved on 2026-10-30 (phase 1.4), and `docs/outstanding-work-plan` after phase 1 the same day |
| Merging, deploying, open-data pushes and Render pins after each phase | Release go-ahead |

## Order and total

1 → 2 → 3 → 4, then 5 and 6 in either order, with 7 last. Phases 1–5 take about 14 days of
agent work; all seven take about 21. With phase 2 deferred, the order is 1 → 3 → 4, then 5 and 6,
then 7; phase 2 can be picked up whenever LangSmith is available or its use is waived.

## Execution notes

### Phase 1 (2026-10-30)

Started on the owner's word ("go ahead and implement phase 1"). Branch `docs/phase-1-cleanup`.

- **1.1 ROADMAP:**
  - Restructured into an at-a-glance table, then one section per line of work: v0.1, the MCP
    stages, chat and agent, the availability catalog, hosted deployment, the backlog and the
    standing constraints. Each section links its plans and records.
  - The long Stage 1–6 paragraphs are condensed into a table. Their detail stays in the linked
    acceptance records and in git.
  - The "Follow-ups after v0.1" list maps onto phases 6 and 7. Two items are not scheduled:
    native OneBuilding indexing (it waits for permissions) and rate-limit scheduling (only if
    evidence shows a need).
- **1.2 Status lines:**
  - The slots spec now records the merge (`0483872`, `3ac7e3d`) and points phases (b)–(d) to
    phases 3 and 4.
  - The evals design records that E1, E2 and E4 are built and that E3, E5 and task 10 are
    phase 2.
  - The NSRDB geospatial design is marked superseded and kept as history. Its map part was done
    on 2026-09-24. Its service rule was replaced by the owner's 2026-10-12 decision (ADR 0003:
    the mask gates NSRDB GOES), the 2026-10-13 per-product masks and the 2026-10-27 Himawari-8
    gate.
  - The plan file of that design was left as written: its own header already marks it
    historical.
- **1.3 Flaky test:**
  - **Runs:** six full runs, two at a time for load, two in default order and four shuffled
    (seeds 11, 22, 33, 44, through a scratch plugin). 1,091 passed in every run, in 5:09–5:28
    under load.
  - **Two false starts (my own setup, not the suite):** a `--basetemp` under the long
    scratchpad path exceeded the Windows path limit (`WinError 206`), and pytest does not
    create a missing parent of `--basetemp`. Short roots under `%TEMP%` fixed both.
  - **Named:** the 2026-10-13 failure is in the session log:
    `tests/agent/test_policy_config.py::test_a_security_file_is_used_by_path`. With
    `OPENAI_API_KEY` unset, it and `test_chat_eval_and_serve_choose_their_profiles` fail every
    time: the hosted profile refuses to start without a moderation key. A worktree has no
    `.env`, so this is an environment dependence, not timing.
  - **Second dependence, found while checking:** run from the main checkout, whose `.env` has
    `LANGSMITH_TRACING` on, 13 API and site-gate tests build the web chat with real LangSmith
    tracing and the real key. Their log shows 18 "tracing: on" events.
  - **The 2026-10-30 run:** it kept only the summary line, so its failing test cannot be named.
    It ran from the main checkout with a dummy key. The tracing dependence above is the likely
    cause, but this is not proven.
  - **Fix**, on its own branch because it is test code and needs the owner's go-ahead:
    `fix/offline-test-isolation`, commit `2247700`.
    - An autouse fixture in `tests/conftest.py` runs every offline test in a temporary working
      directory, with a fake `OPENAI_API_KEY` and the LangSmith variables cleared. Live tests
      keep the real environment. `CONTRIBUTING.md` explains this.
    - Checked: in the worktree with no key, 1,091 passed. From the main checkout, 1,091 passed,
      and the only "tracing: on" left is `test_create_app_reads_tracing_from_its_env_file`,
      which uses its own fake key on purpose.
  - Machine time used: about 40 minutes.
- **1.4 Cleanup:**
  - Each branch was first confirmed to be an ancestor of `origin/main`.
  - `feature/agent-request-lookups` and `feature/availability-followups` were deleted locally
    and on origin; `docs/record-staging-pin` was local only.
  - The follow-ups worktree was removed. Its only untracked content was a 64 KB empty catalog
    under `.local/openepw/`.
  - This session's own worktree (`.claude/worktrees/mcp-agent-request-slots-2459d2`) stays
    while the session uses it; the desktop app manages it.
- **Owner review (2026-10-30):**
  - "You may go ahead merging offline-test-isolation into main; leave deploy/staging unchanged."
    Merged into `main` with a merge commit, because `main` had moved on by the phase 1 docs;
    the published fix branch was not rebased. `deploy/staging` is unchanged.
  - Deleting `docs/outstanding-work-plan` approved ("Ok"); confirmed merged, then deleted
    locally and on origin.
  - Phase 2 deferred, not worked, because LangSmith is not available for now.
