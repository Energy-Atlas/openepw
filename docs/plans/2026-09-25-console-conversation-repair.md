# Console Conversation Repair Implementation Plan

> **Approval:** The owner approved implementation in chat on 2026-09-25. Implemented on `feature/mcp` with failing tests first.

**Goal:** Let a user complete a weather request across short clarification turns, inspect real catalog options without starting a job, and select a geocoded place once.

**Architecture:** Keep an in-memory draft of explicit user choices and a pending geocoder choice in the console. Parse each utterance once, merge its explicit fields into the draft, then pass the assembled typed intent to the existing reference agent. The service and MCP tools remain authoritative for availability, plans, jobs, and QC.

**Tech Stack:** Existing Python harness, Pydantic intents, MCP stdio client, pytest, Ruff, mypy.

**Spec:** The Cambridge, MA transcript reported by the owner, plus [harness behavior](../harness/README.md), [MCP contract](../mcp/README.md), and [availability boundaries](../limitations.md).

## Global constraints

- Preserve automatic submission for a complete, executable request; exploration and unanswered clarification never submit.
- Keep `.env` read only, and keep credentials, raw EPW bytes, and provider response bodies out of local records and LangSmith trace payloads.
- Do not guess a geocoding candidate, provider, weather quality, or catalog support. A year-specific weather request may resolve to the existing `historical` product, but that mapping must be stated to the user and be overridable.
- Preserve the single-request `openepw-agent` interface and the existing future baseline workflow.
- The current US$8 per-data-root model budget stop remains in force. The 20-call smoke limit should not govern an ordinary interactive chat.

## Root cause

`ChatSession._remember` retains intent only after `review_required` or job completion. The reference agent returns `needs_clarification` before that, so location, year, and product are discarded. `ReferenceAgent._weather` lists ambiguous geocoder names but neither returns a machine-readable choice nor keeps the candidates. Each reply is parsed as a fresh request; the model prompt even says the current text alone is the task. The model's cumulative 20-call test cap ends the loop. The agent also requires a product before it can call read-only discovery, so “what do you have?” cannot be answered.

## Review focus

1. A short answer such as `2018` fills the pending year without erasing Cambridge or the selected product.
2. A full candidate name or displayed number selects exactly one prior geocoder result without a second geocode call.
3. “What do you have?” consults read-only MCP availability when enough location/period context exists; unknown eligibility is reported as unknown, and no plan or job is created.
4. A new request or correction replaces the relevant draft fields; stale candidates and old weather years do not leak into a later future or weather task.
5. An interactive session can pass 20 model calls while still respecting the cumulative cost budget; trace and credential boundaries remain intact.

## Task 1: Typed draft and single parse per turn

**Files:** `src/openepw/harness/chat.py`, `src/openepw/harness/agent.py`, `src/openepw/harness/model.py`, `tests/harness/test_chat.py`, `tests/harness/test_agent.py`.

- [x] Add a console-owned typed draft for weather/future slots and an explicit pending-question state. Keep only normalized facts, not raw prompt history.
- [x] Parse each new utterance as a delta. Merge explicit nonempty fields into the draft; a correction replaces its field. Do not ask the model to reconstruct the whole request from the last line or reuse guessed values as explicit choices.
- [x] Add a `ReferenceAgent.run_intent(intent, ...)` path that executes an already parsed intent, while retaining `run(prompt, ...)` for the single-request command. The console calls the parser once and then `run_intent`.
- [x] Let a year-specific weather request select `historical` as a disclosed product interpretation, unless the user explicitly chooses a different compatible product. Keep TMY/published requests separate from actual-year requests.
- [x] Test the transcript's first three turns, `2018`-only follow-up, explicit corrections, and a new-task reset. Verify one model call per substantive turn and no plan submission while required fields remain missing.

## Task 2: Geocoder choice handoff

**Files:** `src/openepw/harness/agent.py`, `src/openepw/harness/chat.py`, `tests/harness/test_chat.py`, `tests/harness/test_agent.py`.

- [x] Return the bounded geocoder candidates as structured clarification data alongside a numbered human-readable list. Preserve each candidate's ID, name, coordinates, and elevation from the MCP response in the console's pending choice.
- [x] Accept a unique displayed number or exact normalized name. Reject ambiguous or unrecognized answers and repeat the choices without rerunning geocoding or silently selecting the first result.
- [x] Pass the selected location through the agent's typed location override and resume the assembled draft. Clear the pending choice after selection, correction, or task reset.
- [x] Test the Cambridge choice shown in the transcript, including the full candidate name, number, invalid selection, and a selection followed by `2018`.

## Task 3: Read-only exploration before execution

**Files:** `src/openepw/harness/model.py`, `src/openepw/harness/chat.py`, `tests/harness/test_chat.py`, `tests/harness/test_chat_stdio.py`.

- [x] Distinguish an exploratory request such as “what do you have?” from a retrieval request. Exploration must not turn on automatic submission.
- [x] With a resolved location and year, call the public `weather_assess`/`weather_discover` tools for valid product-specific requests and summarize ranked eligibility, access, evidence age, and explicit unknowns. Published/TMY products cannot be queried using an actual year; assess them under their own reference-period semantics.
- [x] If location or year is still unresolved, explain the product choices that can be discussed and ask for only the missing detail. Do not fabricate a source list or present catalog support as complete, simulation-ready weather.
- [x] Test that exploration makes no `weather_plan` or `weather_submit` call, then that an explicit retrieval choice uses the retained draft and proceeds automatically.

## Task 4: Interactive budget and end-to-end acceptance

**Files:** `src/openepw/harness/model.py`, `src/openepw/harness/chat_cli.py`, `tests/harness/test_model.py`, `tests/harness/test_chat_stdio.py`, `docs/harness/README.md`, `docs/limitations.md`.

- [x] Keep the 20-call cap for bounded automated/single-request smoke runs; use a separate interactive call policy so it cannot terminate a normal conversation at 20 cumulative calls. Retain the US$8 per-data-root projected cost stop and usage ledger.
- [x] Replay the owner's Cambridge transcript against a deterministic model and geocoder fixture. Acceptance: a product/year/location draft survives clarifications, the Cambridge candidate is selected once, “what do you have?” reports read-only eligibility, and a complete request produces one stored plan and at most one submission.
- [x] Run harness unit tests, real stdio synthetic tests, Ruff, mypy, and the full offline suite. A bounded live model check may verify phrasing and traces, but must not fetch weather or claim availability without catalog evidence.
- [x] Document the revised clarification, exploration, and call-limit behavior; commit at the conversation-state and acceptance boundaries.

## Implementation record

- The console holds a typed in-memory draft and passes it to `ReferenceAgent.run_intent`; the single-request agent path remains available. Geocoding choices are numbered, retained, and selected without repeating geocoding.
- Exploratory prompts use read-only `weather_assess` for the five weather product families. Reported catalog support is retrieval eligibility, with access and unknowns preserved; EPW quality remains subject to QC.
- The interactive console uses the US$8 ledger stop without the 20-call smoke cap. The standalone parser retains its 20-call default.
- Deterministic transcript and real stdio fixture tests cover the Cambridge clarification path, one plan and submission, future-task separation, and no planning during exploration. A bounded four-call live model-only check covered the owner's opening phrasing; no live weather retrieval was performed.
- Verification: full offline suite 350 passed, 15 skipped before two final location-choice edge tests; focused conversation tests 11 passed after them. Ruff, mypy, and the installed console help command passed. The existing Starlette/AnyIO deprecation warning is unrelated.

## Interactive follow-up — 2026-09-25

- The owner's next Cambridge session exposed a compound reply that the console did not recognize: `location 1, AMY data` left the numbered candidate unresolved. The console now selects the displayed location before parsing the remaining product text, so a later `2018` uses the selected coordinates.
- The active local catalog produced roughly 91 KB assessments and a 123 KB AMY discovery with normal providers, above the former 80 KB MCP result cap. The cap is now 160 KB; the same discovery and its 1.5 KB plan summary fit. This does not change eligibility or QC semantics, and larger results remain bounded.
- Regression tests for both failures passed before full-suite verification: 356 passed, 15 opt-in tests skipped, and the existing Starlette/AnyIO deprecation warning. The live model parsed `AMY data` as AMY with no place; no weather job was submitted during this check.
