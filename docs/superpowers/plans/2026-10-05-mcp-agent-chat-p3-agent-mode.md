# MCP agent chat — P3 agent mode, model port and evals — Implementation Plan

**Goal:** Agent mode for the P2 core: a tool-calling model loop over the openepw MCP server, with
host ask-tools that open the same forms as guided mode, the same host guard-rails, automatic
fallback to guided mode, mode switching, scripted scenarios in CI and an `openepw eval` command
with opt-in live model runs.

**Spec and decisions:** [design spec](../specs/2026-10-05-mcp-agent-chat-design.md) §2 (modes),
§3 (ask-tools, gates), §4 (agent loop, limits, errors), §6 (scenarios, evals);
[ADR 0005](../../decisions/0005-mcp-agent-chat.md); [P2 plan](2026-10-05-mcp-agent-chat-p2-agent-core.md)
and its execution notes. P2 is merged into `feature/chat-ui` at `63ee921`.

**Approval:** the owner asked to "execute P3" on 2026-10-05 after reviewing P2's status and the
proposed P3 starting point. This plan was written and executed in the same session; routine
choices below are recorded rather than gated (AGENTS.md).

## Global constraints

- Branch `feature/mcp-agent-mode` from `feature/chat-ui`; no push until the owner asks. Do not
  modify `main`, `deploy/staging`, `feature/account-login`, `feature/mcp-agent-chat`.
- `fix(topic): ...` commits, normal human authorship, no agent or model trailers.
- Python 3.11 and 3.13; the scientific and data core imports nothing from `openepw.agent`.
- The model calls only `openepw.mcp.access.MODEL_TOOLS` and the host ask-tools. Submit, cancel,
  retry, export and upload stay host actions. Every plan request a model sends is rewritten by
  `gates.check_plan_request`; "run" submits only plans shown on the open review (P2 guard).
- Model input never contains credentials, local paths or EPW bytes: user text passes through
  `safe_prompt` before it is stored or sent; tool results are framed as data.
- Offline tests never call a model or provider; live runs are opt-in (`live` marker, `openepw
  eval --live`) and budget-capped.

## Decisions this plan makes (owner may override)

1. **Model port.** `ModelPort.respond(system, items, tools) -> ModelReply` over a
   provider-neutral item list (`user`, `note`, `assistant` with tool calls and opaque provider
   items, `tool_result`). Adapters: `ScriptedModel` (tests) and `OpenAIModel` (Responses API with
   function tools over `httpx`, `store=false`, encrypted reasoning items passed back, the same
   model id, price constants, usage ledger and budget stop as the legacy parser). No LangChain
   dependency in the new core.
2. **Default model and budget.** `gpt-6-luna` (the legacy default), ledger at
   `<data root>/agent/model-usage.json`, `--max-cost` default 5 USD per ledger; exceeding it is
   `ModelUnavailable`, which switches the session to guided mode.
3. **One policy object, two modes.** `ModelPolicy` holds a `GuidedPolicy` and delegates to it
   while `state.mode == "guided"`. A form opened by guided rules is answered by guided rules
   even in agent mode; a form opened by an ask-tool carries its pending tool call.
4. **Shared host steps.** Form builders and the plan run move from `guided.py` to
   `agent/host.py` so both policies open identical forms and submit through one guarded path.
5. **Years in agent mode.** `facts.years` is the union of years the person wrote in the current
   request (messages and text-form answers). A model plan may use any subset; `check_plan_request`
   rejects others with `GATE_REQUIRED need=ask_text`.
6. **Suspension.** An ask-tool stores `state.pending_call` and the turn's item list in
   `SessionState`, so a restart resumes the loop. Text typed while an ask-tool form is open
   becomes that tool's result (`person_replied`), so corrections reach the model.
7. **Evals.** Scenario files are JSON inside the package (`openepw/agent/evals/scenarios.json`;
   no YAML dependency). Weather providers and geocoding are stubbed by packaged stubs unless
   `--live-providers`. `openepw eval --mode guided` runs offline; `--mode agent --live` uses the
   OpenAI adapter and reports pass rate, steps, latency and cost per scenario.
8. **CI.** The test matrix sets `fail-fast: false` so the 4 known date-sensitive failures no
   longer cancel the Python 3.11 jobs.

## File structure

| File | Responsibility |
| --- | --- |
| `src/openepw/agent/text.py` (modify) | `safe_prompt` moves here; `harness.agent` re-imports it |
| `src/openepw/agent/host.py` | Shared form builders, `point`, `run_plans` |
| `src/openepw/agent/guided.py` (modify) | Uses `host.py` |
| `src/openepw/agent/state.py` (modify) | `SessionState.turn`, `SessionState.pending_call` |
| `src/openepw/agent/session.py` (modify) | Redacts user text; `on_upload` hook; `tool(..., by=)` |
| `src/openepw/agent/model_port.py` | `ModelPort`, `ModelReply`, `ToolCall`, `ModelUnavailable`, `ScriptedModel`, `OpenAIModel`, `load_openai_key` |
| `src/openepw/agent/tools.py` | Ask-tool schemas, model tool list from MCP `list_tools`, result shaping |
| `src/openepw/agent/policy_model.py` | `ModelPolicy`: loop, gatekeeper, limits, repair, suspension, fallback, summaries |
| `src/openepw/agent/mcp_port.py` (modify) | `InProcessMCP.list_tools()` |
| `src/openepw/agent/cli.py` (modify) | Agent mode by default when a key exists, `/mode`, `--mode`, `--max-cost` |
| `src/openepw/agent/evals/` | Packaged stubs, scenarios, runner, report |
| `src/openepw/cli/main.py` (modify) | `chat --mode/--model/--max-cost`, `eval` subcommand |
| `tests/agent/test_model_port.py`, `test_policy_model.py`, `test_agent_scenarios.py`, `test_evals.py`, `test_eval_live.py` | Tests |

## Tasks

### Task 1: Shared host steps and redaction (refactor, no behaviour change except redaction)
- Move `_offset`, `_point`, `_place_set_form`, `_review_form`, `_plan_form`, `_next_steps_form`
  and `_run` from `guided.py` to `host.py` (`offset`, `point`, `place_set_form`, `review_form`,
  `product_form`, `plan_form`, `next_steps_form`, `run_plans(session, advance)`).
- Move `safe_prompt` to `agent/text.py`; `harness/agent.py` imports it.
- `AgentSession.send_text` stores `safe_prompt(text, limit=4000)`; `answer` redacts `answer.text`.
- `AgentSession.tool(name, *, by="host", **arguments)` tags events; `_upload` calls
  `policy.on_upload(session, artifact_id)` when the policy has it, otherwise keeps P2 behaviour.
- Tests: all P2 agent tests unchanged and passing; a redaction test (S20 for guided).

### Task 2: Model port
- `ToolCall(id, name, arguments: str)`, `ModelReply(text, tool_calls, raw, cost_usd)`,
  `ModelUnavailable`. `ScriptedModel(steps)`: each step a `ModelReply`, a callable
  `(system, items, tools) -> ModelReply`, or an exception to raise; records every request.
- `OpenAIModel(api_key, *, model, ledger_path, max_cost_usd, max_calls=None, client=None)`:
  async Responses API call with `tools=[{"type":"function", ...}]`, `store=false`,
  `include=["reasoning.encrypted_content"]`; converts items; projects cost before each call and
  records usage after; maps transport, HTTP, incomplete and malformed responses to
  `ModelUnavailable` without echoing the response body.
- `load_openai_key(env_file=".env")`: environment first, then the ignored dotenv file.
- Tests with `httpx.MockTransport`: request shape (tools, items, no key in body), function-call
  parsing, usage ledger and budget stop, HTTP error mapping, item round-trip.

### Task 3: Tools and the model policy
- `tools.py`: `ASK_TOOLS` schemas (`ask_choice`, `ask_text`, `review_location`,
  `choose_products`, `request_map_input`, `request_upload`, `review_plan`);
  `model_tools(port)` = MCP `list_tools` filtered to `MODEL_TOOLS` plus ask-tools;
  `shape_result(result)` = summary text plus identifiers, capped at 4 KB.
- `ModelPolicy(model, *, max_steps=8, max_retries=2, turn_seconds=60)`:
  - context = system prompt (role, science rules, gates, tool order) + state block from facts +
    history of the last 20 events (tool results labelled as data) + the current turn's items;
  - gatekeeper: unknown names → repair; host tools and legacy tools → `TOOL_NOT_ALLOWED`;
    `weather_plan` → `check_plan_request` (→ `GATE_REQUIRED need=<ask-tool>`), MCP call, plan
    stored (replacing a plan of the same product and datasets); `weather_visualize` → `view`
    event; future-kind requests → `FEATURE_SUSPENDED` from the server as usual;
  - ask-tools open forms (via `host.py`) and suspend; answers become tool results; the
    `review_plan` approval runs `host.run_plans` and ends the turn;
  - limits: 8 tool steps, 2 retries of one failing tool, 60 s wall time per input; exceeding a
    limit ends the turn with a plain message and keeps the form;
  - malformed arguments or unknown tool: one repair attempt, then the guided form for this turn;
  - `ModelUnavailable` at any point: mode becomes guided, a notice is shown, facts are kept and
    the guided form for the current facts opens;
  - after jobs finish, one model turn summarises the host's job message (QC codes,
    `simulation_ready=false`), then the next-steps form opens.
- Tests (ScriptedModel, offline MCP): S1 agent happy path, S6, S7, S8, S13, S14, S16, S18 (agent
  resume), S19, S20, limits, repair, text with an open ask-tool form, stale answers, `/mode`.

### Task 4: CLI agent mode
- `openepw chat [--mode agent|guided] [--model NAME] [--max-cost USD]`: agent mode by default
  when an OpenAI key is available, otherwise guided with a notice; `/mode` toggles (agent only
  when a model is configured); the banner and `/status` show the mode.
- Tests: CLI conversation with a `ScriptedModel`, `/mode` switching, no-key fallback.

### Task 5: Evals
- `evals/stubs.py`: packaged geocoder table and constant ERA5-like provider (the test fakes
  reuse them). `evals/scenarios.json`: S1, S2, S3, S4, S6, S8, S10, S11, S12, S19, S20 as a user
  message plus a form-answer policy and deterministic checks (required forms, forbidden model
  tools, required tools, no submit without approval, grounded years, no simulation-ready claim,
  redaction, step limit). `evals/runner.py`: `run_scenarios(...) -> Report` over a fresh data
  root per run; `openepw eval [--mode guided|agent] [--live] [--repeats N] [--scenario ID]
  [--max-cost USD] [--live-providers] [--output PATH]`.
- Tests: guided eval passes all guided-applicable scenarios offline; a scripted-model eval run;
  report shape; a `live`-marked test (skipped by default).

### Task 6: Docs, CI and verification
- `docs/agent/README.md` (agent mode, keys, budget, evals), ARCHITECTURE, FEATURES, ADR 0005
  status, MCP README note on ask-tools; CI `fail-fast: false`; execution notes here.
- Full suite, ruff, mypy, build; one live CLI run and one small live eval with a budget cap,
  recorded honestly.

## Later phases

P4 builds `/v2/agent` (REST + SSE) and the React renderer on this core; P5 retires the legacy
chat paths (see the P2 plan's table).
