# Outstanding work after the 2026-10-30 release — phase plan

**Status:** phases and their contents agreed with the owner on 2026-10-30 ("Valid findings … group
them by phases"; "Ensure these plans are written down"). No phase is started. Each phase starts only
on the owner's word, with the prerequisites listed for it.

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

| # | Item | Source | Done when |
|---|---|---|---|
| 1.1 | Bring the ROADMAP up to date with the agent chat, availability and staging work since Stage 6, and link this plan | [ROADMAP](../../../ROADMAP.md) | ROADMAP lists these phases and their status |
| 1.2 | Fix stale status lines: the [slots spec](../specs/2026-10-12-agent-request-slots-design.md) ("not merged"), the [evals design](../specs/2026-10-10-agent-evals-design.md) ("Not built yet") and the [NSRDB geospatial design](../specs/2026-09-24-nsrdb-geospatial-availability-design.md) ("owner review is required"; check whether the 2026-10-13 coverage masks superseded it) | the documents | Each status matches what is in `main` |
| 1.3 | Find the flaky test: one failure in a slow 8-minute run on 2026-10-30, none on rerun. Rerun the suite under load and record any failure | 2026-10-30 release | The test is named and fixed, or documented as timing-sensitive |

## Phase 2 — Finish the agent evals (about 3 days)

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

This phase comes before phase 4, so the slots work is measured with the judges.

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
| 4.2 | Eval tasks for the slots, with phase 2 judge checks | Agent and guided suites pass offline |
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
| Deleting merged branches (`feature/agent-request-lookups`, `feature/availability-followups`, `docs/record-staging-pin`) and their worktrees | Deletion needs explicit approval |
| Merging, deploying, open-data pushes and Render pins after each phase | Release go-ahead |

## Order and total

1 → 2 → 3 → 4, then 5 and 6 in either order, with 7 last. Phases 1–5 take about 14 days of
agent work; all seven take about 21.

## Execution notes

None yet.
