# Agent evals framework — Plan

**Status:** **approved by the owner on 2026-10-10** ("plan approved"). The owner asked for E1, E2
and E4 (tasks 1–7 and their docs) first, built autonomously without supervision, with findings,
issues and assumptions logged in the execution notes and presented for review on completion.
E3 (task 8), E5 (task 9, which waits for human calibration labels) and task 10 wait. Design and
owner answers: [spec](../specs/2026-10-10-agent-evals-design.md) (§8).

**Branch:** `feature/agent-evals`, created from
`feature/agent-guardrails` at the commit that adds this plan. `feature/agent-guardrails` was
fast-forwarded into `feature/mcp-agent-mode` and `feature/chat-ui` on 2026-10-10 (all three at
`b8bf980`; not pushed).

**Scope:** the eval framework for the agent chat (`openepw.agent.evals`) and its docs. The agent's
behaviour does not change, except that guards gain off switches usable only by the mutation
command (Task 6).

## 1. Decisions this plan builds on

- **Tasks:** YAML, one file per task, validated by pydantic; an unknown key is an error. No
  backward compatibility: S1–S44 move to YAML and `scenarios.json` is deleted.
- **Trial record:** one object per trial. The trace ends with the outcome; graders read only the
  record.
- **Graders:** a registry. Rule graders are hard (any failure fails the trial) or soft. Model
  judges are soft until calibrated (Task 9).
- **Results:** an ignored local folder, `<data root>/evals/<run id>/` (by default
  `.local/openepw/evals/`), and LangSmith experiments for live runs only.
- **Gates:** advisory. Offline runs only in automated checks (pytest); no GitHub CI. Live runs are
  manual.
- **Trials:** offline 1; live regression 3; live tasks tagged `safety` 5, judged by pass^k (every
  trial passes).
- **Budget** (owner left it to the plan):
  - agent model: `--max-cost` default $1 per live run (unchanged);
  - judges: a separate `--judge-max-cost`, default $1 per run.

  A full live run (33 tasks; 3 trials for regression, 5 for safety) is about $0.20 for the agent
  model at today's rate. Judges run only on tasks that declare them; at about $2 in and $12 out
  per million tokens (a Terra-class rate, to be checked against OpenAI's pricing page), one
  judged trial costs about 1–2 cents.
- **Judge model:** a setting, default `gpt-5.6-terra` (the owner first named `gpt-6-terra`, which
  the project key cannot use).

## 2. Tasks

| # | Task | Main files | Tests |
| --- | --- | --- | --- |
| 1 | **Task schema and YAML suite.** Pydantic models for a task (id, title, purpose, covers, suite, tags, modes, profiles, setup, user, graders, trials, reference, script). One YAML file per task under `openepw/agent/evals/tasks/`, migrated from S1–S44 with the same checks. Delete `scenarios.json`; `--scenarios-file` becomes `--tasks` (a folder or file) | `evals/schema.py` (new), `evals/tasks/*.yaml`, `evals/runner.py`, `evals/command.py` | Every packaged task validates; an unknown key, an unknown grader or bad parameters fail with the file and line; migrated tasks give the same verdicts as before (offline, both profiles) |
| 2 | **Grader registry.** Each check in `_check` becomes a registered grader: name, one-line description, why it matters, severity, parameter schema, and the evidence it returns (trace entry numbers). Always-on graders are listed once. Failure codes come from the registry; `assistant_excludes` gets its own code instead of `OFF_TOPIC_ANSWER` | `evals/graders.py` (new), `evals/runner.py` | Each grader's description and severity exist; verdicts carry evidence; the report shows hard and soft separately |
| 3 | **Trial records with pins.** One JSON-lines file per run in `<data root>/evals/<run id>/trials.jsonl`. Each record holds:<br>• **pins:** run id, task id and hash, trial number, git commit and whether the tree had uncommitted changes (plus a hash of the diff), package version, model id, system-prompt and tool-list hash, profile and digest, providers, moderation mode, start time;<br>• the redacted trace ending in the `outcome` entry;<br>• grades.<br>Passing trials are kept too. Keys and local paths are redacted again on the way out | `evals/records.py` (new), `evals/runner.py`, `agent/tracing.py` (prompt hash helper) | The record round-trips; pins present; a planted key never appears in the file; works outside a git checkout (commit recorded as unknown) |
| 4 | **Metrics and comparison.**<br>• per task: pass rate, pass@k, pass^k, per-grader pass rates, p50/p95 steps, tool calls, tokens, cost and latency, guard codes, strikes, fallbacks;<br>• per suite and tag: pass rate with a Wilson 95% interval;<br>• `summary.json` beside the trials;<br>• `openepw eval compare A B` lists newly failing, flaky and newly passing tasks, and grader changes | `evals/metrics.py` (new), `evals/command.py` | Metric formulas on synthetic records; comparison of two fixed runs |
| 5 | **HTML report.** One self-contained `report.html` per run:<br>• header with the pins;<br>• suite and tag table with intervals;<br>• the baseline comparison first;<br>• failures grouped by grader;<br>• cost, latency and step summaries;<br>• a page per task with each trial's verdicts and the deciding trace entries highlighted;<br>• a LangSmith link when the trial was traced.<br>No external scripts; it works offline | `evals/report.py` (new), template | Report renders from a fixed run; links and anchors resolve; no secrets |
| 6 | **Grader checks (meta-eval).**<br>• one failing and one passing trace fixture per rule grader;<br>• `openepw eval mutate` switches off one guard at a time and confirms the tasks that cover it fail. The guards are link filtering, moderation, the strike limit, the years gate, the approval gate, readiness correction, input normalisation and outside-text cleaning. A guard whose tasks still pass is reported as uncovered;<br>• a solvability check (every task's script passes offline) | `tests/agent/graders/` fixtures, `evals/mutate.py` (new), small off switches in `guard.py`, `session.py` and `gates.py` (test-only, not settings) | Every registered rule grader has both fixtures; the mutation run reports no uncovered guard; switches cannot be turned on from YAML profiles or the CLI chat |
| 7 | **Lint and catalogue.**<br>• `openepw eval --lint`: tasks without purpose or coverage, graders without fixtures, tasks without a script, checks that can never trigger under a profile (for example a code the profile cannot emit);<br>• `openepw eval --catalog`: a Markdown and HTML catalogue of the tasks (purpose, setup, conversation, graders in plain words, last pass rates), a grader glossary and a coverage matrix from `covers` | `evals/catalog.py` (new), `evals/command.py` | Lint finds planted problems; the catalogue lists every task and grader |
| 8 | **LangSmith for live runs (E3).** When tracing is configured, a live run creates or updates a dataset (`openepw-agent-evals`: one example per task) and an experiment per run. Each trial is a trace with metadata (`task_id`, `trial`, `suite`, `tags`, pins), and grader verdicts are attached as feedback. Offline and scripted runs are never sent. The trace inspection guide (spec §6.3) goes into the agent README | `evals/langsmith.py` (new), `agent/tracing.py`, docs | With a fake client: datasets, runs and feedback are created with redacted data; nothing is sent offline; a tracing failure never fails the eval |
| 9 | **Model judges (E5), soft.** Judge graders for:<br>• whether a decline was right;<br>• whether a reply is grounded in tool results (no availability claim without one);<br>• knowledge-answer correctness against the task's `reference`;<br>• helpfulness and clarity.<br>Each has one narrow question, a rubric, a "can't tell" option and a short reason. The judge model is a setting, with the `--judge-max-cost` cap. Calibration:<br>• a LangSmith annotation queue with the same rubric;<br>• 24 human labels per dimension to start (8 pass, 8 fail, 8 borderline);<br>• `openepw eval calibrate` reports agreement, Cohen's kappa and disagreements.<br>Judges stay soft; the owner decides any promotion | `evals/judges.py` (new), `evals/calibrate.py` (new), docs | With a scripted judge: rubric prompts, parsing, budget stop, "can't tell", soft severity; calibration maths on fixed labels; one live judge pass recorded |
| 10 | **Grading real sessions.** `openepw eval grade-sessions --data-root ...` runs the always-on rule graders over saved chat sessions (the local session store) and writes the same record and report format, without replaying them. No model and no LangSmith needed | `evals/sessions.py` (new) | Grades a fixture session store; a planted invariant break is found |
| 11 | **Docs.** Agent README (evals, testing guide, trace guide), ARCHITECTURE, FEATURES, limitations, and this plan's execution notes | docs | — |

**Order:** 1, 2, 3, 4, 6, 7, 5 (E1, E2, E4), then 8 (E3), then 9 (E5), then 10 and 11. Tasks 1–7 and
10 need no key. Commit at each task boundary.

**Estimate:** about three days for tasks 1–8 and 10–11; task 9 is about a day of building plus the
owner's labelling time.

## 3. Not in this plan

- A model-played person and the capability suite (E6), apart from the `suite` field and tag
  support.
- LangSmith online evaluators on production traces (reconsidered with P4 hosting).
- Running evals in GitHub CI.

## 4. Owner answers (2026-10-10)

1. **Judge model default:** `gpt-5.6-terra`.
2. **Branch name:** `feature/agent-evals`, from `feature/agent-guardrails` after this plan's commit.
3. **Labelling:** 24 labels per judged dimension to start.
4. **Push:** push `feature/agent-guardrails`, `feature/mcp-agent-mode` and `feature/chat-ui`.

## 5. Execution notes (2026-10-10 to 2026-10-11): E1, E2 and E4

Built autonomously on `feature/agent-evals` as the owner asked: tasks 1–7 and their docs. E3
(task 8), E5 (task 9) and task 10 are not started. Sections 1–3 are left as approved and are
superseded where they differ.

### Deviations and assumptions

- **CLI shape:** `openepw eval` has subcommands (`run`, the default, plus `compare`, `lint`, `catalog`
  and `mutate`) instead of `--lint` and `--catalog` flags. Run options changed with the format
  (no backward compatibility): `--scenario` → `--task`, `--repeats` → `--trials`,
  `--scenarios-file` → `--tasks`, and `--output` → a results folder (`--output-dir`, default
  `<data root>/evals/<run id>/`).
- **Per-profile checks:** a grader entry may carry `profile:`; this replaces `checks_by_profile`.
- **Grader codes:** each grader has one code. New or renamed codes are `SUBMISSION_MISMATCH` (was
  `SUBMITTED`/`NOT_SUBMITTED`), `SESSION_END_MISMATCH` (was `SESSION_NOT_ENDED`/`…_UNEXPECTEDLY`),
  `TOO_FEW_STRIKES` (was the second meaning of `STRIKES`) and `FORBIDDEN_REPLY_TEXT` (was
  `OFF_TOPIC_ANSWER`, which every `assistant_excludes` hit raised); the others are unchanged.
- **Readiness grader:** `FALSE_READINESS` now fails only a claim shown without the host
  correction. The old check failed corrected claims too; the invariant is what the person sees.
- **Model-input graders** read only what a model call was sent, not its reply (a fixture pins this).
- **Grader fixtures** live in the package (`openepw/agent/evals/grader_fixtures.yaml`), not in
  `tests/`, so `eval lint` can check them in an installed copy.
- **Mutations** patch functions in the running process (`unittest.mock`) instead of adding off
  switches to `guard.py`, `session.py` and `gates.py`; the agent code gains no test-only paths.
- **Approval-gate mutation:** "text typed at the plan review counts as Run". Removing the MCP
  elicitation check alone cannot be seen by an eval (the host never submits without Run); that
  layer stays covered by `tests/unit/test_mcp_approval.py` and `tests/agent/test_mcp_port.py`.
- **Trace size:** each model entry keeps everything the model was sent (state block, history,
  turn items), so traces can be inspected in full; the HTML report shows the first 4,000
  characters per call. Tool-list hashes in the summary leave out calls offered no tools (the
  summary after a run).
- **Coverage ids** are a packaged vocabulary (`coverage.yaml`); unknown ids are load errors.
- **Migration** of S1–S44 used a one-off script (not committed). Each task got a purpose, coverage
  ids and tags; checks moved one to one.
- **Git pins** ignore untracked files; outside a git checkout the commit is "unknown".

### Findings while building (and what was done)

1. **Agent tasks without an offline solution:** S2, S3, S4 and S10 had no script, so their
   agent-mode solvability was never proven offline. Scripts added; lint now treats this as an error.
2. **Exclusion without proof:** S30 checked that hidden characters never reached the model but
   nothing showed its text reached the model at all. Lint found it; `model_input_contains` added.
3. **Uncovered guards (mutation runs):** no task covered the readiness correction or the
   off-topic clamp, and S6 could not catch a removed years gate (the person later gives 2018
   and the replanned 2018 plan overwrites the invented one). Added S45, S46 and S47; all 14
   mutations are now caught.
4. **Declines not counted in S23/S31:** these check the decline wording but not the strike,
   because guided mode never counts declines and a grader cannot yet be limited to one mode.
   S42–S44 cover counting. Possible follow-up: a `mode` filter on grader entries.
5. **Trivial offline pass in S10:** its scripted run stops at the product form, so "no
   actual-year plan" holds trivially offline; the check is meaningful in guided and live runs.
6. **Grader bug caught by the framework:** the first model-input grader also read the model's
   own reply, failing S29 falsely. Fixed, with a fixture.
7. **Windows decoding:** `git diff` output was decoded as cp1252 and crashed on UTF-8; fixed.
8. **Lint scan:** reading emitted codes from source missed codes passed positionally; lint
   also uses the session's guard-code list.
9. **Defence in depth confirmed:** with the host-tool gate patched off, the model's submit still
   failed at the MCP approval check; the eval caught the attempt (`MODEL_HOST_TOOL`).
10. **Report visual check:** rendered in the browser pane; pins show uncommitted changes and the
    diff hash.

### Results

- `openepw eval lint`: 36 tasks, no errors or warnings. All 63 grader fixtures hold.
- Offline, both profiles: guided 23/23, agent scripted 36/36.
- `openepw eval mutate`: 14 of 14 mutations caught.
- Agent tests 314 passed, 2 skipped (live, opt-in); full suite 971 passed with only the four
  known availability-test failures; ruff and mypy clean; the wheel ships the task files,
  fixtures and coverage list.
