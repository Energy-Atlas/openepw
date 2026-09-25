# Local reference agent

## Interactive console chat

From the repository root, install the optional harness and start a local chat:

```powershell
.venv/Scripts/python.exe -m pip install -e ".[harness]"
.venv/Scripts/openepw-chat.exe --data-root .local/openepw --env-file .env
```

The console reads `OPENAI_API_KEY` from the existing, ignored `.env` if it is
not set in the shell. It never writes the file. It opens one local stdio MCP
session and uses `gpt-6-luna` for intent extraction. Each new weather or future
plan executes automatically. Provider requests can fetch live data and model
calls are billable; the harness ledger caps projected model spending at US$8
per data root. The interactive console does not inherit the single-request
20-call smoke cap. Use a distinct `--data-root` to keep a test session separate.
If `LANGSMITH_API_KEY` is present in the shell or existing `.env`, the console
also sends each turn to the `openepw-local-chat` LangSmith project. Model intent
and MCP calls appear as child steps. Traces include sanitized natural-language
requests, compact intent fields, tool names, opaque IDs and statuses; they omit
API keys, EPW bytes, provider request bodies and full MCP results. The console
reads the key without changing `.env`. Set `--trace-project <name>` to group
traces elsewhere, or `--no-trace` to turn tracing off for a session. Tracing
failures are reported in the terminal while weather jobs continue.

For example, ask for an actual year at a location, then ask to morph that EPW
for a named scenario and climate window. A future request also needs a method
and, for morphing, a reference window. The console carries only confirmed
choices, a current request draft and artifact IDs between turns. Short replies
such as `2018` or `historical` fill the current draft. A year-specific weather
request is interpreted as historical unless you choose another compatible
product; the console states that interpretation. Ambiguous geocoding results
are numbered: reply with a number or exact displayed name, or use `/reset` to
start a new request. Ask `what do you have?` to assess read-only catalog
eligibility. Exploration does not submit a plan and cannot prove that an EPW
is complete or simulation-ready. TMY/TMYx/published reference products are
assessed without treating an actual year as their source year.
If a weather request produced several
EPWs, select one with `/baseline <artifact_id>` before referring to “that EPW”.
Use `/upload <path>` to register a user EPW directly through MCP; its bytes and
local path stay outside model prompts. `/inspect last` shows artifact QC, and
`/save last <path>` saves an EPW to a new file without overwriting an existing
one. Type `/help` for all commands. `/status [job_id]` checks a running job,
`/retry` retries failed outputs, and `/quit` ends the console while leaving
jobs and artifacts in the data root. Use `/auto off` to pause subsequent plans
for review and `/submit` to execute a reviewed plan.

Conversation references last only while the terminal stays open. After restart,
use an explicit artifact ID or `/status <job_id>`. The reference parser currently
requests UTC output for weather; use the Python, CLI or MCP interfaces directly
when a particular fixed standard-time offset is required. Inspect QC before
using any EPW for simulation: `simulation_ready=false` remains the contract.

## Single-request reference agent

Install the optional `openepw[harness]` extra, then use
`openepw-agent --data-root <private-data-root> --prompt "<task>"`.
The command launches the Stage 4 stdio MCP server and consumes only its public
tools. It uses `gpt-6-luna` through the Responses API for bounded intent
extraction; the service and MCP tools decide eligibility, plans, jobs and QC.
Set `OPENAI_API_KEY` in the process environment before a model run. The
command does not load, copy or change the repository's `.env`.

By default the agent stops at `review_required`, showing the immutable
plan hash and key choices. Run `openepw-agent --data-root <root>
--submit-kind weather` (or `future`) after reviewing it. For scripted
local evaluation, `--auto-submit` proceeds through job completion. Use
`--resume [JOB_ID]` after disconnect; the agent re-reads canonical MCP job
facts instead of rerunning completed outputs. The reference record lives at
`<data-root>/harness/last-run.json` and contains only opaque IDs and tool
names. The ignored cost ledger lives beside it.

For a user EPW, pass `--baseline-file <path>` with a future prompt. The client
reads and uploads bytes directly, outside model input, and supplies the
returned baseline ID to the agent. A fetched OpenEPW weather artifact ID can
instead appear in the task prompt. A future prompt must name the method,
scenario and climate window; morphing should also specify the reference
window. Unsupported combinations return a typed MCP error and no silent
source switch.

The parser removes credential assignments and absolute local paths before
sending user text to the model. It uses `store=false`, low reasoning effort,
structured intent output, a 1,024-token output cap and an ignored local ledger
that stops new calls at a projected US$8. Stage 5/6 cumulative authorization
is below US$10. The key, raw prompts, EPW bytes, hourly tables and full
catalog inventories are absent from local run records. This single-request
command does not send LangSmith traces. Provider credentials required by a separate live retrieval remain
runtime settings for OpenEPW, outside the model prompt.

The agent does not certify an EPW for simulation. It says that catalog support
only makes retrieval eligible to try, reports unknown alternatives, and
inspects manifest/QC before describing a finished output. A NOAA gap with
`warn` remains sentinel-bearing and `simulation_ready=false`; with `error`
no EPW is emitted for that row. See [the fixed rubric](evaluation.md),
[stack comparison](stack-decision.md) and
[Stage 5 acceptance](../validation/mcp-stage-5-acceptance.md).
