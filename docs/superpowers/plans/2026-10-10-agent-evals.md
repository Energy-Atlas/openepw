# Agent evals framework — Plan

**Status:** proposed 2026-10-10; **not approved**. Build only after the owner records approval
here. Design and owner answers: [spec](../specs/2026-10-10-agent-evals-design.md) (§8).

**Branch:** `feature/agent-evals` (name awaiting the owner's approval), created from
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
- **Judge model:** a setting. The owner named `gpt-6-terra`, which the project key cannot use
  (`model_not_found`). The default (for example `gpt-5.6-terra` or a `gpt-6` model) awaits the
  owner (Q1).

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

## 4. Open questions for the owner

1. **Judge model default:** `gpt-6-terra` is not available to the project key. Use
   `gpt-5.6-terra`, one of `gpt-6-sol`, `gpt-6-astra` or `gpt-6.1-sol`, or another model?
2. **Branch name:** `feature/agent-evals` (purpose prefix as AGENTS.md requires; it adds a
   capability, not a fix), created from `feature/agent-guardrails` after this plan's commit.
3. **Labelling:** is 24 labels per judged dimension acceptable for a first calibration, with the
   set growing from labels added while inspecting traces?
