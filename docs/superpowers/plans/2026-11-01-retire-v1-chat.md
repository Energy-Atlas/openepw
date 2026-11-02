# Retire the legacy chat (P5) — Plan

**Status:** added as a phase by the owner on 2026-11-01, after phase 5:

| Point | Owner answer (2026-11-01) |
| --- | --- |
| Next phase | "Let's do phase 5 first", read as P5: it was the recommended next step and phase 5 itself was finished the same day |
| Merge | "ok to merge to both main and staging" |
| Branches | "may delete": `feature/post-download-conversations`, `feature/agent-web-chat` and `docs/defer-staging-check`, each confirmed merged first |
| Staging check | The signed-in check of P4 and phase 5 was deferred until the next phase ships; it now covers P5 too |

**Branch:** `feature/retire-v1-chat` from `main` (`4d79309`). Production (`feature/render-deploy`),
`feature/webui` and `feature/account-login` are not touched.

**Source:** ADR 0005's P5: retire `ChatCoordinator`, `ReferenceAgent`, `ChatSession`,
`GraphChatSession` and `/v1/chat/*`. Since P4 the browser renders agent sessions through
`/v2/agent`, so nothing in the product calls the legacy chat any more. Old `/v1` chats need no
backward compatibility (owner, 2026-11-01).

## 1. What goes and what stays

| Code | Decision |
| --- | --- |
| `/v1/chat/*` routes and their request models in `api/app.py`; `create_app(chat_parser=...)` | Removed. The `KeyError` → 404 and `ValidationError` → 422 handlers stay for the other routes ("Not found" instead of "Session not found") |
| `openepw.chat` (`coordinator.py`, the `products.py` re-export) | Removed |
| `openepw.harness`: the LangGraph console (`chat`, `chat_cli`, `graph_chat`, `graph_model`, `console_port`, `session_lock`, `trace`, `model`, `rubric`, `cli`) | Removed with the `openepw-chat` and `openepw-agent` commands |
| `harness/mcp_client.py` (`StdioMCPPort`) | Kept as `openepw.mcp.client`: a real stdio MCP client for the pilot and stdio tests |
| `harness/agent.py` (`ReferenceAgent`) | Moved to `tests/pilot/reference_client.py`: the pilot journeys still drive `openepw mcp` from outside through the public contract, but it is no longer installed or a command |
| `agent/tracing.langchain_tracing` | Removed (only the LangGraph console used it) |
| The `harness` extra | Renamed `agent` (`mcp`, `pyyaml`, `langsmith`); LangGraph, LangChain and questionary dropped. `harness` stays as an alias so old install commands work. The Docker image no longer installs it (the web chat does not trace) |
| `tests/harness/`, `tests/unit/test_chat_*.py`, the `/v1/chat` API tests | Removed. Tests that used a chat route only as a probe now use `/v2/agent/sessions`; the local-standard-time test builds its request directly |

## 2. Also fixed

The pilot journey `test_b_published_batch_exact_product_occurrences_and_export` counted every
`job_inspect`, so a slow machine exceeded its budget of 30 calls (32–45 on a loaded machine, 37 on
`main` before phase 5). A `job_inspect` that finds the job still queued or running is now a wait,
not a step, so the budgets count work, not machine speed.

## 3. Checks

ruff, mypy, full pytest; offline evals (lint; guided and scripted agent under `local` and
`hosted`; mutations); no live model run (the agent's behaviour does not change). The web client
is unchanged.

## 4. Execution notes

### P5 (2026-11-01)

Started on the owner's word above; branch `feature/retire-v1-chat` from `main` (`4d79309`). The
merged branches were confirmed ancestors of `origin/main`, then deleted locally and on `origin`.

**Done.** Section 1 as written: about 3,800 lines of legacy chat and console code and 14 legacy
test files removed; `StdioMCPPort` moved to `openepw.mcp.client`; the reference agent moved into
`tests/pilot/`; the pilot call budget fixed (section 2).

**Finding.** The web agent chat (`/v2/agent`) has no LangSmith tracing; only `openepw chat` is
traced. The "web chat" tracing project belonged to the legacy `/v1` parser. Recorded in the agent
README and the limitations; not changed here.

**Checks.** ruff and mypy clean (119 source files). pytest (repository `.venv`): 1048 passed, 20
skipped, 0 failed in 15 minutes, run alongside the evals; the pilot journey that used to exceed
its budget under load passed. Offline evals: lint 55 tasks, 0 errors; guided 34/34 and scripted
agent 55/55 under `local` and `hosted`; mutations 20 of 20 caught. No live model run. The web
client is unchanged, so vitest and the build were not rerun on this branch.
