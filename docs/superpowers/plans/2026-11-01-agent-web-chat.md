# Web chat on the agent core (P4) — Plan

**Status:** P4 of [ADR 0005](../../decisions/0005-mcp-agent-chat.md) and the
[agent chat design](../specs/2026-10-05-mcp-agent-chat-design.md) (§1, §4 "Web turns", §6 parity,
§7 P4 row). Made a phase by the owner on 2026-11-01, who also answered the open points:

| Point | Owner answer (2026-11-01) |
| --- | --- |
| P4 as a phase | "p4 can become the phase and you may proceed." |
| Chats saved through `/v1/chat` | "left as they are, no need for backward compatibility": `/v2` starts new sessions only; nothing migrates. |
| Deploy | "deploy after this fix": merge into `main` and `deploy/staging` once P4 passes its checks. |

**Branch:** `feature/agent-web-chat` from `main` (`87edbdd`). Production (`feature/render-deploy`),
`feature/webui` and `feature/account-login` are not touched.

## 1. Problem

The browser chat (`web/chat-ui`) calls `/v1/chat`, which `chat/coordinator.py` serves by calling
`WeatherService` directly. The agent core (`openepw.agent`: agent and guided modes, guardrails,
lookups, request parts) runs only in the CLI and the evals. People on staging get none of it, the
two conversation implementations drift, the evals do not test what people use, and a session the
guardrails end is bypassed by opening another (no per-person limits).

## 2. Design

### 2.1 Agent host (`openepw.agent.web`, no FastAPI import)

- One `AgentHost` per server process, built by `create_app` from the same service, `JobRunner`
  and MCP server.
- **Turns run in worker threads**, each with its own event loop, MCP client (in-memory transport,
  one per turn) and policy. MCP tools that block (geocoding, planning) block only their turn, not
  the web server's loop or other sessions. One input at a time per session (`SESSION_BUSY`).
- Sessions live in `<data root>/agent/sessions.sqlite`, the same store as `openepw chat`, so a web
  session can be resumed in the CLI on the same data root. Ownership, usage, limits and job
  ownership live in `<data root>/agent/web.sqlite`.
- **Model per turn:** an `OpenAIModel` without its own ledger, wrapped by a spend guard that
  checks the profile's caps before each call and records each call's cost in `web.sqlite`
  (atomic, so concurrent turns do not lose spend). A stopped cap raises `ModelUnavailable`
  (`budget`); the policy then switches the session to guided mode as it already does.
- **Jobs:** after Run the host follows jobs in short passes (`AgentSession.check_jobs`, one
  `job_inspect` round per pass) while no form is open, so a long Copernicus job never holds the
  session. When every job finishes, the policy's results step runs as in the CLI.

### 2.2 Routes (`/v2/agent`, `openepw.api.agent_routes`)

| Route | Purpose |
| --- | --- |
| `POST /v2/agent/sessions` | New session (agent mode when a model is configured), checked against the person's session rate |
| `GET /v2/agent/sessions/{id}` | Snapshot: mode, open form, recent events, request parts, places, jobs, busy, ended |
| `POST /v2/agent/sessions/{id}/inputs` | One input: `text`, `answer`, `back`, `new`, `mode`, `request`; 202, the turn runs in the background |
| `POST /v2/agent/sessions/{id}/upload` | EPW for an open upload form (5 MB) |
| `GET /v2/agent/sessions/{id}/events` | Server-sent events after `Last-Event-ID` (or `?after=`), with `state` frames when a turn ends; `?poll=1` returns JSON for clients without SSE |

A session belongs to the person who created it (account id on deployments with accounts, else the
client address); other people get 404. `/v1/chat` stays until P5 and is unchanged.

### 2.3 Limits (security profile `limits`)

Typed settings replace the `limits: {}` placeholder; `hosted.yaml` sets them, `local.yaml` turns
them off. Per person (account, else client address): new sessions per hour, inputs per minute,
weather jobs running at once (checked at Run). Spend caps: per session, per person per day, all
web sessions per day. `weakened()` reports any limit looser than `hosted`.

Deferred from the guardrails list (recorded, not built): a lower place cap per approval, CDS
products for admins only (needs account roles, staging-only today), alerts on guard-code spikes.

### 2.4 Web renderer (`web/chat-ui`)

- `ChatApi` speaks `/v2/agent` (same constructor, so a wrapper fetcher still works); REST for
  catalog, jobs, artifacts and views is unchanged.
- `App` renders the open form by kind: `text`, `map_input` (typed; the map pick stays hidden by
  the 2026-09-27 decision), `choice` (place candidates also on the map), `location_review`
  (Approve or a typed correction), `product_choice` (the product dialog, preselection, map tags),
  `plan_review` (Run and Change), `request_summary` (OK and Change), `upload`.
- Header: agent/guided toggle, "Your request" (the summary), Back, Start over. Job card, downloads
  and charts as before; view events open chart panels.
- Model text is rendered as Markdown without raw HTML; links open in a new tab with
  `rel="noopener noreferrer"` after the host's link policy.

### 2.5 Tests

- Host and routes: ownership, busy, limits, spend caps, job following, SSE framing (TestClient).
- **Parity:** guided and scripted-agent scenarios run through the CLI loop and through `/v2`; both
  give the same sequence of form kinds and tool calls.
- **Form fixtures:** Python writes one form of every kind to
  `web/chat-ui/tests/fixtures/agent-forms.json` (a test fails when it is stale); vitest renders
  each.
- CI gains a `web` job (`npm ci`, `npm test`, `npm run build`).
- Browser check against a local server with the eval stub providers, recorded in §4.

## 3. Risks

- **Rollback:** sessions saved by this code cannot be read by older code (as for phase 4).
- **Address limits** use the first `X-Forwarded-For` entry like the account gate; without accounts
  a person can evade them by spoofing it. The daily caps on all web spend still bound the cost.
- **Live behaviour** of agent mode in the browser follows the CLI's (phase 4 live check); no new
  live eval is run without the owner's word.

## 4. Execution notes

### P4 (2026-11-01)

Started on the owner's word above; branch `feature/agent-web-chat` from `main` (`87edbdd`).

**Built.**
- `agent/web.py`: `AgentHost` (worker-thread turns, one input per session, ownership, job
  following), `WebStore` (`web.sqlite`: owners, inputs, spend, jobs), `SpendGuard` (caps before
  each call, atomic cost records), `WebInput`.
- `agent/session.py`: `check_jobs` (one `job_inspect` pass); `follow_jobs` uses the same steps.
- `agent/policy_config.py` and the profiles: typed `limits` (`hosted` sets six, `local` none);
  `weakened` names looser limits.
- `api/agent_routes.py` and `create_app(agent_model=...)`: the `/v2/agent` routes, SSE with
  `Last-Event-ID`, `?poll=1`, refusals as `{code, message}` (409, 413, 429).
- `web/chat-ui`: `ChatApi` on `/v2` (same constructor), `App` and `FormDock` render every form
  kind, `ModelText` (Markdown without raw HTML or images, safe links), header with mode switch,
  "Your request" and Back; job card, downloads and charts kept on REST.
- Tests: host (10), routes and parity (9: S1, S2, S57 guided; S1, S57 scripted agent), the form
  fixture (one real snapshot per kind), vitest (104) on that fixture; CI `web` job.
- Docker image names the `mcp` extra; the server logs a warning when it is missing.

**Routine choices and deviations.**
- Worker threads instead of the design's "existing background queue": the legacy queue belongs
  to `ChatCoordinator`, and MCP tools that block would otherwise stall the server's event loop.
- One MCP client per turn (in-memory, cheap) instead of one per session: an event loop ends with
  each turn, and the SDK's client must stay in the loop that opened it. The model and moderation
  HTTP clients are made and closed per turn for the same reason.
- Free text at any form is sent as a message (`send_text`), as the CLI does; buttons send answers.
- A second input while one runs is refused (`SESSION_BUSY`) rather than queued; the browser
  disables the reply area while a turn runs.
- The browser keeps a new session key (`openepw-agent-session`), so old `/v1` sessions are never
  resumed (owner: no backward compatibility).
- The job card keeps polling `/v1/jobs` for progress and manifests; "Download all" makes one ZIP
  per job (the agent's session ZIP is the "Compact ZIP" next step).
- Dropped from the old web chat: retry of failed outputs (no agent path yet), the Copernicus queue
  note (agent job events do not say a job is queued), rollback to any earlier message (Back is one
  step), the client-side chart guess from typed text (the agent answers chart requests itself).
- The web chat records no LangSmith traces (phase 2 deferred; the tracer is per-turn state).
- `openepw serve` on a non-local host now needs `OPENAI_API_KEY` at start-up (owner decision Q4
  of 2026-10-09 for profiles that block without moderation), as `openepw chat` already did.

**Browser check (2026-11-01).** Local server on the eval stub providers, guided mode, built app:
"AMY 2018 for Ithaca NY" → location review (map zoomed to Ithaca, time offset shown) → product
dialog with map tags (selecting by tag ticks the box) → plan review with the parts table → Change
years → years form "(now 2018)" → "2019" → plan review → Run → job followed by the host → result
message and "What next?" → the monthly chart opened from the view event. A second request
(Boston, 2020) and "Your request" showed the summary with statuses. One SSE connection stayed
open for the session; the only console error was the expected 404 of `/v1/diagnostics` (debug log
off). Fixed on the way: the plan review showed the request twice; the phone layout left no room
for the transcript (taller rail, compact header, map overlays above it). Agent mode was not tried
in the browser (no live model run without the owner's word; agent sessions are covered by the
scripted parity tests).

**Checks.** (Filled in below when the final run completes.)
