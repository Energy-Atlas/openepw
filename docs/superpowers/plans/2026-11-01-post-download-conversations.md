# Conversations after a download (phase 5) — Plan

**Status:** phase 5 of the [outstanding-work plan](2026-10-30-outstanding-work.md). Approved by the
owner on 2026-11-01 with three answers:

| Point | Owner answer (2026-11-01) |
| --- | --- |
| Retry of failed outputs | "add retry": the person retries from the chat, through a form |
| Live model check | "ok": a small live check, as in phase 4 (at most $1) |
| Merge | "ok": merge into `main` and `deploy/staging` when the phase passes its checks |

**Branch:** `feature/post-download-conversations` from `main` (`7581988`). Production
(`feature/render-deploy`), `feature/webui` and `feature/account-login` are not touched.

**Source:** the [post-retrieval conversations plan](../../plans/2026-09-26-post-download-conversations.md)
(2026-09-26). It was written for the LangGraph chat (`harness/`, checkpoints, `/save`). The
agent core (`openepw.agent`) now runs both the CLI and the browser, so this plan updates it
against the later decisions: the agent chat (ADR 0005), the web chat (P4) and staging accounts.

## 1. What the 2026-09-26 plan still asks, and what changes

| 2026-09-26 item | Now |
| --- | --- |
| Future MCP suspension (step 1) | Done (`fa94923`); unchanged. |
| Recent-job index in LangGraph state, checkpoint migration | Replaced: the agent session already keeps `job_ids`, `finished_job_ids` and `artifact_ids`; outputs are read from the jobs' verified manifests, not from session order. No migration (owner, 2026-11-01: no backward compatibility for `/v1` chats). |
| `/save` → `/download` | The CLI gains `/download`; the browser downloads through its own links (the person's browser saves the file). |
| Data views (steps 3–4) | Implemented in 2026-09; this phase adds the month-of-year profile family and lets the agent see a view's values to answer factual questions. |
| Retry "states the scope first" | Kept: the retry form lists every failed output the retry covers. |
| "How is the download going?" (transfer progress) | Not needed: a CLI download is a local file write of at most 10 MB; the browser shows its own progress. Job progress stays as it is. |
| Paths kept out of model input | Kept: the folder is a CLI command argument, written only to the console, never to the event log. |

No conflict with a later decision is material, so nothing is escalated.

## 2. Design

### 2.1 Outputs listing (shared service)

- `openepw.jobs.outputs.job_outputs(runner, job_id)`: one row per batch row of the job's verified
  manifest (or of its plan while it runs): place (name, lat, lon from the plan's locations),
  product kind, provider and dataset, year (or period), status (`succeeded`, `failed`,
  `cancelled`, `unsupported`, `unresolved`, `pending`), artifact id, file name, bytes, sha256 and
  issue codes. A retry job's rows carry `retry_of`.
- REST `GET /v1/jobs/{job_id}/outputs`; MCP model tool `job_outputs` (read-only); the agent host
  merges the rows of a session's jobs by output id, a later success replacing an earlier failure.

### 2.2 Conversation behaviour (both modes)

| Person | Host |
| --- | --- |
| "What did I get?", "list my files" | Numbered outputs (place, year or "typical year", status, file). No plan, no job. |
| "Which one is 2016?", "download the 2016 file" | The matching outputs, offered as downloads; several places ask which one (a choice form in agent mode, the numbered list in guided mode). |
| "Download all" | Every succeeded output offered; the compact ZIP stays a separate next step. |
| "What happened to 2017?" | The output's status and recorded issue codes. |
| "Retry" | A retry form lists every failed output the retry covers; only the person's approval submits `job_retry_failed` (with a one-shot approval of the original plan). Each job chain allows 3 retries. |
| "Annual mean temperature 2016–2018", "average January over those years" | Agent mode: `weather_visualize` on the right files; the host gives the model the view's values with coverage and place/year labels. |

- Follow-ups never call `weather_plan` or `weather_submit`, and never clear a request in progress.
- A **download offer** is a `download` event: files (number, label, artifact id, file name,
  bytes). The browser shows links; the CLI shows `/download <numbers> <folder>`.
- **Guided mode** reads these follow-ups with fixed patterns before reading places or years, and
  the "What next?" form gains "List my files", "Download files" and, when outputs failed, "Retry
  failed outputs".
- **Agent mode** gets two host tools (`list_outputs`, `offer_download`) and one ask-tool
  (`review_retry`). Retry stays a host tool for the model (`job_retry_failed` is refused).

### 2.3 CLI downloads

`/download <numbers|all> [folder]` saves the files of the latest offer (or listing) through the MCP
artifact resource, checks each file's sha256, never overwrites (exclusive create) and removes a
partial file on failure. Without a folder the CLI asks for one. The folder and the written paths
are printed to the console only.

### 2.4 Month-of-year profile

`month_of_year_profile` (planned since 2026-09) becomes implemented: per source, the monthly
aggregate of each year (the same rules as `monthly_series`), then the mean over the years for
each month, grouped by place and source, with contributing years. By default a month with any
incomplete year is null; `allow_partial` averages the available months and marks them partial.
Actual and reference sources never mix.

## 3. Tests and evals

- Offline tests: the outputs listing (manifest and plan rows, retry rows, unknown job), REST and
  MCP, the merge across retries, guided and agent follow-ups, retry gating and its cap, CLI
  download (checksum, no overwrite, partial cleanup), the profile family (coverage rules).
- Evals: a stub provider that fails once near a point; a `tool_counts` grader (follow-ups add no
  `weather_plan`/`weather_submit`); tasks for listing, a year's download, download all, retry,
  a follow-up in the middle of a new request, and (agent) a factual summary.
- A small live agent check on the new tasks within $1.

## 4. Risks

- A retry submits provider work: it needs the person's approval on the retry form, and the cap
  bounds a loop of retries.
- Values given to the model are host-computed; the model may still misquote them. The view event
  (chart, CLI JSON) carries the authoritative numbers.

## 5. Execution notes

(Filled in as the phase runs.)
