# Handoff: MCP agent chat, phase P2 (agent core, guided mode, CLI)

**Date:** 2026-10-05. **Repository:** `C:\github\Energy-Atlas\openepw` (normal checkout, Windows,
PowerShell or Git Bash). **Start from:** `feature/chat-ui` at `d32a449` or later (P1 merged and
pushed). **Your job:** implement the P2 plan task by task, with reviews, and stop at the end of
P2 for the owner.

You have no access to the conversation that produced this work. Everything you need is in the
repository; this note tells you what to read, what is decided, what is open and how to work.

## Read first, in this order

1. `AGENTS.md`: repository rules. It overrides any tool or harness defaults.
2. [Design spec](../superpowers/specs/2026-10-05-mcp-agent-chat-design.md): the whole
   programme (P1–P5) and why.
3. [ADR 0005](../decisions/0005-mcp-agent-chat.md): the decision record.
4. [P1 plan](../superpowers/plans/2026-10-05-mcp-agent-chat-p1-contract.md), its final
   **Execution notes** section only: owner-approved deviations and items deferred to P2.
5. [P2 plan](../superpowers/plans/2026-10-05-mcp-agent-chat-p2-agent-core.md): **your
   requirements**, with complete code and tests for 9 tasks.
6. [MCP README](../mcp/README.md): the tool contract you call (errors, approval, summaries).

## Where things stand

- The programme makes the web chat and the CLI chat run on **one Python agent core that is a
  real MCP client**, with renderer-neutral forms and host guard-rails. There are two distinct
  modes: **agent mode** (a tool-calling model, from P3) and **guided mode** (rule-based forms,
  P2).
- **P1 is done** and merged into `feature/chat-ui` (`fd8d659..d32a449`). Work previously on
  `feature/mcp-agent-chat` (kept, same commits). P1 delivered:
  - product offers and location offset review in `WeatherService` and as MCP tools
  - typed tool schemas, bare-JSON errors, short model summaries plus `structuredContent`
  - submission, legacy fetch and retry confirmed by the person via MCP elicitation
  - one job runner per data root (cross-process lock), a shared runner for the API's
    in-process MCP server
  - tool access classes (`openepw.mcp.access`)
- **P2 is not started.** The plan was pre-validated: its code ran in a scratch copy at
  `d32a449` (45 agent tests passed, mypy clean on the new package).
- The web UI still uses the old `/v1/chat/*` coordinator. That changes in P4; do not touch the
  web UI in P2.

## Decisions already made (do not reopen)

- **Architecture approach A:** a Python agent core, hosted in-process by the CLI and (P4) by
  FastAPI, connected over the MCP in-memory transport to one MCP server per process.
- **Host-enforced guard-rails in both modes:**
  - location review (including fixed standard-time offsets) before any plan
  - product choice before any plan
  - actual-year years only from the person's text or a form
  - plan review before submit
  - submit, cancel, retry, export and upload are never model tools
- **Forms** come from host ask-tools (agent mode) or the guided rules. They are typed
  Interactions rendered as cards (web) or text (CLI).
- **Server-side approval** is MCP elicitation, not tokens. Retries need confirmation too.
- **Model:** a pluggable `ModelPort` with OpenAI as the default adapter (P3).
- **No-model behaviour:** two distinct modes; guided mode is rule-based forms, like today's
  web cards but not a copy of them.

## Defaults this plan chose that the owner has not explicitly confirmed

These are recorded in the P2 plan under "Decisions this plan makes". Proceed with them. If the
owner objects, the plan's execution notes are where you record the change.

1. **Branch:** `feature/mcp-agent-core`, created from `feature/chat-ui`. The owner was asked
   whether to use a new branch or reuse `feature/mcp-agent-chat` and did not answer before this
   handoff. If the owner names another branch, use it.
2. **Host substitution:** plans are built only from approved facts. This replaces P1's
   deferred "review-key helper".
3. **One-shot approvals:** one plan approval answers exactly one confirmation.
4. **`openepw chat`:** a new subcommand. The legacy `openepw-chat` console stays until P5.
5. **Scenario tests:** P2's guided scenarios are plain pytest. The reusable `openepw eval`
   runner comes in P3.

## How to work

- **Execution:** use superpowers:subagent-driven-development if available. Dispatch a fresh
  implementer per task with only that task's text, then a spec-and-quality review, then a final
  whole-branch review. Otherwise use superpowers:executing-plans. Keep a progress ledger
  (`.superpowers/` is local scratch; add it to `.git/info/exclude`).
- **Process:** TDD as written in each task: see the test fail, implement, see it pass, lint,
  type-check, commit.
- **Commits:** `fix(topic): concise description`, normal configured authorship. **No
  "Co-Authored-By" or other agent/model trailers**, even if your harness suggests them;
  AGENTS.md wins.
- **Branches and history:** do not push, force-push, rebase published history, or delete
  branches unless the owner asks. Do not touch `main`, `deploy/staging` (Render internal-testing
  deploy; the owner said leave it as is), `feature/account-login` or `feature/mcp-agent-chat`.
- **Files to leave alone:** the ignored root `.env` and `.local/` data.
- **Commands** (repo root):
  - tests: `.venv/Scripts/python.exe -m pytest -q` (about 3.5 minutes; run in the background)
  - `.venv/Scripts/python.exe -m ruff check .`
  - `.venv/Scripts/python.exe -m mypy`
  - `.venv/Scripts/python.exe -m build`
- **Known pre-existing failures:** exactly 4 tests, 2 in `tests/unit/test_availability_adapters.py`
  and 2 in `tests/unit/test_availability_service.py`, failing with "catalog-supported discovery
  called provider HTTP". They fail identically on `main`; they are date-sensitive fixtures,
  tracked separately. There is also one pre-existing starlette/anyio `DeprecationWarning`.
  Anything else failing is yours to explain.
- **If the plan's code fails a test** because an assumption about existing code is wrong (for
  example the fake provider), fix the **test fake** first, never product behaviour, and record
  it in the plan's "Execution notes".
- **Escalate to the owner only for** the items AGENTS.md lists: scope contradictions, unclear
  licences, credentials, irreversible external actions, security incidents, destructive git,
  breaking an approved public API. Otherwise make routine choices, document them and continue.

## Pitfalls already found

- MCP SDK 1.30 enters the FastMCP lifespan once per client session. Always build the server
  with a runner you own (`create_server(service, runner=runner)`), call `runner.recover()`
  once, and `runner.close()` at the end. `InProcessMCP` must be entered and exited in the same
  asyncio task.
- Geocoder candidates arriving through MCP carry `standard_offset_minutes: 0` as a default.
  Strip it (`guided._point`) so the location review estimates the real offset. Otherwise a US
  place silently gets UTC.
- The service's cached-fetch replay reads `http.config`; test HTTP fakes must have it
  (`tests/agent/fakes.py` does).
- `job_inspect` polling is host work and is not logged as tool events; tests should not expect
  it in `tools()`.
- Unknown MCP tool names come back as plain text `Unknown tool: <name>`, not JSON;
  `parse_failure` maps that to `MCP_TOOL_ERROR`.

## Definition of done for P2

- All 9 tasks committed on the P2 branch.
- Each task reviewed (spec and quality) and the final whole-branch review clean or fixed.
- The full suite passes except the 4 known failures; ruff, mypy and build are clean.
- `docs/agent/README.md`, ARCHITECTURE, FEATURES, ADR 0005 and the plan's execution notes are
  updated.
- One manual `openepw chat` run, recorded honestly. Real geocoding and providers need network;
  say so if you could not run it.
- Then stop and report to the owner:
  - commits
  - test results
  - deviations
  - anything deferred, with a proposed P3 starting point (`ModelPort` and the model policy)
  - offer, but do not do, a merge into `feature/chat-ui` and a push

## After P2

P3 adds agent mode: the model loop, ask-tools, mode switching, scripted and live evals.
P4 builds the web on the same core. P5 retires the old chat paths. Each phase gets its own
plan, written after the previous phase lands; see the P2 plan's "Later phases" table.
