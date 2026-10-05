# Agent chat core (agent and guided mode)

`openepw.agent` is one conversation core for the CLI and (from P4) the web chat. It is a real
MCP client of the local openepw server over the SDK's in-memory transport and never calls the
weather service directly. It has two modes with the same forms and host guard-rails:

- **Agent mode** (P3): a tool-calling model reads the conversation, calls the server's model
  tools and the host's ask-tools, and answers in words.
- **Guided mode** (P2): rule-based forms and offline text reading; no model.

## Run it

```powershell
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat --mode guided
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat --session <id>
```

Agent mode is the default when `OPENAI_API_KEY` is set in the environment or in the ignored
root `.env`; otherwise the chat says so and uses guided mode. `--model` picks the OpenAI model
(default `gpt-6-luna`) and `--max-cost` (default 5 USD) is the budget stop for the usage ledger
in `<data root>/agent/model-usage.json`. Costs are estimates from token counts and the price
constants in `openepw.agent.model_port`. The key is read at start-up, sent only to the OpenAI
API, and never written to the session, events, ledger or reports.

One process runs jobs for a data root: stop `openepw serve` or use another data root
(`DATA_ROOT_BUSY` otherwise). Commands: `/back`, `/new`, `/upload <path>`, `/status`,
`/mode [agent|guided]`, `/help`, `/quit`. Sessions are saved in
`<data root>/agent/sessions.sqlite`; an unknown `--session` ID is reported as
`SESSION_NOT_FOUND`, and a saved agent session resumed without a key continues in guided mode.

After a run starts, the chat follows the jobs for up to two minutes at a time, then gives the
prompt back (press Enter to keep following; `/status` lists the jobs). Jobs run in this process:
`/quit` or Ctrl-C waits for a running job to finish, and its outputs stay in the data root.
`/upload` refuses files over 5 MB before reading them.

## Forms and gates

Every step is a typed form (`text`, `choice`, `location_review`, `product_choice`, `map_input`,
`upload`, `plan_review`). Guided mode asks them in the gate order: place → location review
(with fixed standard-time offsets) → products → years (actual-year only) → plan review → run →
job progress → next steps (charts, compact ZIP, new request). Plans are built by the host from
the approved review, chosen offers and the years the person wrote; a model-supplied plan request
is rewritten the same way. "Run" submits only the plans the open review shows: any change
(years, products, place) replans and reopens the review first. Each plan approval answers
exactly one submission confirmation, and an approval is dropped if the submission fails before
the server asks. Future weather stays suspended (scenario names such as SSP5-8.5, RCP 4.5 or
CMIP6 get the suspension message without a model call). Retrieved EPWs are not certified
simulation-ready.

Back restores the facts (and the mode) captured when an earlier form was shown, but never
crosses a started job, and keeps uploaded or retrieved EPW artifacts. An unexpected failure during a turn keeps
the open form and shows `INTERNAL_ERROR` with a correlation id that is logged locally; the
exception text is not shown. Credentials and local paths in what the person types are replaced
(`[redacted]`, `[local path]`) before anything is logged or sent to a model.

## Agent mode

The model sees the server's model tools (`openepw.mcp.access.MODEL_TOOLS`) with their live MCP
schemas, minus the two the host wraps, plus these host ask-tools:

| Ask-tool | Opens | The answer becomes |
| --- | --- | --- |
| `review_location(locations)` | location review (calls `weather_locations_review`) | approval and location key |
| `choose_products(product?, provider?)` | product choice (calls `weather_product_offers`) | chosen offers and their requests |
| `ask_text(prompt, purpose?)` | text question (`purpose: "years"` for years) | the person's words |
| `ask_choice(prompt, options, multi?)` | choice list | chosen option ids |
| `request_map_input(prompt)` | place input | the place or geography |
| `request_upload(prompt)` | EPW upload | the artifact id |
| `review_plan()` | plan review | submitted job ids (the host submits) |

The host gatekeeper applies to every call:

- submit, cancel, retry, export, upload and the legacy tools return `TOOL_NOT_ALLOWED`;
- `weather_locations_review` and `weather_product_offers` return `USE_ASK_TOOL`, so a review
  always shows a form;
- `weather_plan` is rewritten to the approved locations, chosen datasets and years the person
  wrote, or answered `GATE_REQUIRED` with the ask-tool to call (`need`).

Text typed while an ask-tool form is open becomes that tool's answer, so corrections reach the
model. A turn stops after 8 tool steps, 2 retries of one failing tool or 60 seconds; malformed
calls get one repair attempt and then the guided form for that step. If the model is unavailable
(no key, budget stop, network or provider error) the session switches to guided mode and keeps
its facts. After a run finishes, the model summarises the host's job message (QC issue codes,
`simulation_ready=false`) and the next-steps form opens.

## Evals

```powershell
.venv/Scripts/openepw.exe eval                               # guided mode, offline
.venv/Scripts/openepw.exe eval --mode agent --scripted       # agent mode, scripted model, offline
.venv/Scripts/openepw.exe eval --mode agent --live --repeats 3 --max-cost 1 --output report.json
```

Scenarios live in `openepw/agent/evals/scenarios.json` (spec §6: S1–S4, S6, S8, S10–S12, S19,
S20). Each is one message plus how the simulated person answers each form, or a reply they
type (`"say:..."`). Checks:

- form and tool order;
- no host-only tool run for the model;
- every submission right after a plan-review "Run";
- plan years from words the person typed (option labels do not count);
- at most 8 model steps per input, and no guided-mode fallback in an agent run;
- no unnegated simulation-ready claim;
- no key in the log or in what was sent to the model.

Geocoding and weather providers are offline stubs unless `--live-providers` is given; the stub
geocoder matches names like the real search ("Ithaca" or "Ithaca, NY", not "Ithaca NY"). Agent
mode needs either `--scripted` (offline) or `--live` (the OpenAI key, with an in-memory budget
stop `--max-cost`, default 1 USD). The eval stops once that budget is spent. The report gives
pass rate, model steps, time and estimated cost per scenario, with short redacted transcripts of
failed runs, and a run that crashes is reported as `RUN_ERROR` without ending the eval. Live runs
are never part of CI. The pytest test
`tests/agent/test_evals.py::test_live_agent_evals_with_a_budget_cap` runs only with
`OPENEPW_RUN_LIVE=1`.
