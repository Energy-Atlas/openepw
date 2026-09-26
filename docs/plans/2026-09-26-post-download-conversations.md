# Post-download conversations — proposed plan

**Status:** Draft for owner review; no implementation authorized by this document.

**Goal:** After retrieval or future generation, the console should answer ordinary
follow-up questions about the job, each output, QC, saving, retrying and reusing
an EPW. It should retain the correct referent across turns and restarts without
starting another retrieval unless the user asks for one.

## Current behavior and gap

The console already supports `/status`, `/inspect`, `/save`, `/baseline`, `/retry`
and future follow-ups. LangGraph checkpoints the draft, one last job ID and a
tuple of artifact IDs. A few regular expressions recognize phrases such as
“my downloaded file”; the model extractor is told to return no weather request
for status/file questions. Other follow-ups can fall through as an unknown
weather request. A multi-output job has no durable chat mapping from requested
year/location to artifact ID. A failed new job can leave the prior artifact
tuple as the apparent current result. `/status` currently calls `resume`, which
may poll until a running job finishes.

The service already owns the authoritative evidence: `job_inspect` reports job
state and artifact references, and its verified manifest contains weather
`batch_rows` or `future_rows` with output status and artifact IDs. The console
will read these through MCP. It will not infer output identity from artifact
list order or local filenames.

## Conversation contract

| User request | Expected response or action |
| --- | --- |
| “Where are my files?”, “What did I get?” | Show job state and a numbered output list with requested location/year or future member, status, and artifact ID. Explain that artifacts remain in the data root until explicitly saved; do not invent a prior external save path. |
| “Which file is 2016?” | Resolve the year against manifest rows; if more than one location/product matches, ask the user to choose. |
| “Is this ready for EnergyPlus?” | Inspect the selected artifact and report `simulation_ready` and QC issue codes, including missing sentinels. An emitted EPW is not described as simulation-ready merely because it exists. |
| “Save the 2016 EPW to …” | Resolve one artifact and write only to an explicit local destination using exclusive create. Report the actual path and selected output. |
| “Save all to …” | Require an explicit directory, use safe deterministic names, do not overwrite, and report each saved or failed output. Keep the job manifest mapping available. |
| “Download status?” | Read one job snapshot and report counts and state. `/resume` remains the explicit wait/watch operation. |
| “Why did 2017 fail? Retry it.” | Explain recorded issue codes. The existing MCP retry tool retries all failed outputs: use it directly when 2017 is the sole failed output; otherwise disclose its scope and ask whether to retry all failures. Show the new job ID and updated mapping. |
| “Use that EPW for future morphing …” | Reuse a single unambiguous selected artifact as baseline. Ask for selection when several artifacts match; continue to require real method, scenario and window fields. |
| “Thanks”, “What can I do next?” | Give context-sensitive options without calling the weather planner or asking for a product. |

Pure follow-up turns must make no new `weather_plan`, `future_plan` or submit
calls. A turn that explicitly contains both a follow-up and a new request should
perform both in user order, and should not lose a pending draft or reviewed plan.

## Proposed design

1. **Typed follow-up actions.** Extend the single LangChain turn extraction to
   return ordered actions: new weather/future request, job status, list outputs,
   inspect/QC, select, save one/all, retry, and contextual help. Direct slash
   commands and simple menu choices stay deterministic. The model identifies
   intent and selectors; it does not generate job facts, paths or scientific
   conclusions. Parse any local destination from the original input in the
   console layer, pass only a path placeholder to the model, and never place
   the path in graph state. Use at most one model extraction call per ordinary
   turn. Remove the broad pre-extraction status/file regexes that currently
   swallow compound requests.
2. **Durable result references.** Add a bounded recent-job index to the graph
   checkpoint: job ID, plan hash, kind, last selected output/artifact ID, and
   compact output selectors. Keep the latest completed weather/future results
   distinct from a pending or failed new job. Store no raw utterances, EPW
   bytes, provider payloads, credentials or user save paths. Reinspect canonical
   job and manifest data before answering material status, mapping or QC
   questions; tolerate older checkpoints with only `job_id` and
   `weather_artifacts`.
3. **Output resolution.** Build a small resolver over verified manifest rows.
   Selectors may be artifact ID, numbered output, year/date, location, method,
   scenario or “last/that”. Match all specified fields. A match is accepted
   only when unique; otherwise show numbered candidates, including duplicate
   occurrence labels, with an **Other…** choice in the interactive CLI. A
   failed/cancelled row never resolves to an EPW. Before a terminal manifest
   exists, `plan_inspect` may supply planned labels but never an emitted
   artifact. A new job cannot silently reuse an old artifact as its output.
4. **Fact-based response and file operations.** Centralize bounded result,
   QC and failure wording in the chat layer, using MCP facts. “Where” explains
   the difference between an internal artifact and a saved local file. Save
   operations validate the selected artifact and use exclusive file creation
   with cleanup of incomplete writes; byte transfer and paths remain outside
   model input, checkpoints and LangSmith traces. Report a save destination
   in the immediate response, but do not claim to remember it after restart.
   For batch export, expose the existing `weather_export_compact` tool as an
   explicit option alongside individual saves; do not create an export merely
   because the user asks where files are.
5. **State transitions and recovery.** `/status` performs one `job_inspect`;
   `/resume` waits to terminal state and updates the result index. New retrieval
   completion, partial completion, failure, cancellation and retry each update
   their own job entry. A follow-up while a separate request is awaiting
   clarification or `/submit` must leave that draft and plan intact. On
   restart, reconcile saved references with MCP state; missing/corrupt
   artifacts produce an explicit error and recovery direction.

## Implementation map

- `src/openepw/harness/result_context.py` (new): bounded recent-job facts,
  verified manifest decoding, output selector resolution and checkpoint
  migration. No model, CLI or filesystem-save code.
- `src/openepw/harness/graph_model.py` and `graph_chat.py`: ordered action
  extraction and dispatch while keeping raw text and local paths out of
  checkpoints and traces.
- `src/openepw/harness/chat.py` and `chat_cli.py`: deterministic follow-up
  execution, contextual responses, output menu and explicit local saves.
- `src/openepw/harness/agent.py`: a one-snapshot job inspection path for
  `/status`; retain `resume` for waiting and existing progress callbacks.
- `tests/harness/`: resolver, graph routing, command, checkpoint/restart and
  real-stdio journey tests. Update `docs/harness/README.md`, `FEATURES.md` and
  `docs/limitations.md` for shipped behavior.

## Delivery sequence

1. **Result index and resolver:** define compact state, manifest reader,
   migration from current checkpoints, and deterministic row selection.
   Test one/many/duplicate outputs, future members, partial jobs, retries and
   stale references. Commit at this boundary.
2. **Follow-up routing:** add ordered typed actions and graph dispatch;
   preserve direct commands and pending drafts. Test paraphrases and mixed
   turns, including “show my 2016 file and get 2020 for the same location”.
   Commit at this boundary.
3. **Responses and saves:** implement output listing, QC explanations,
   numbered selection, single/all saves and optional compact export. Test
   no overwrite, invalid paths, missing artifacts, simulation-readiness
   wording and no planner call for pure follow-ups. Commit at this boundary.
4. **End-to-end acceptance:** run an offline real-stdio conversation through
   download → multi-output question → selection → QC → save → future baseline,
   restart and retry. Run focused harness tests, Ruff, mypy and the existing
   offline pilot. If an opt-in live model smoke is useful, keep it small and
   within the established local budget; do not change `.env`. Update harness
   docs, features and limitations, then commit.

## Acceptance examples

- After a seven-year request, “where is my 2016 file?” identifies the 2016
  output from the manifest, not the sixth artifact in a list, and offers an
  explicit save command or destination prompt.
- “Are any of these simulation-ready?” reports each inspected result's QC
  status without claiming readiness from catalog eligibility or EPW syntax.
- “My download status and get TMYx for the same place” reports the old job
  and starts exactly one new TMYx plan; the status action does not overwrite
  the new plan hash.
- “Save it” with several matching outputs asks which one; no file is written.
- After restart, “what did I download?” rehydrates the last result from MCP
  facts. A failed latest job does not surface an older EPW as its artifact.
- Tool messages remain structured and redacted; trace/checkpoint inspection
  shows no local save path, raw EPW data, key or raw provider response.

**Boundary:** This work improves the local console harness. It does not add
scientific repair, simulation certification, a web UI or distributed memory.
