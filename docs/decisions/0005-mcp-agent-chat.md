# ADR 0005 — One MCP agent core for web and CLI chat

Date: 2026-10-05. Status: design agreed with the owner on 2026-10-04/05; P1
(service moves and MCP contract) implemented on feature/mcp-agent-chat; P2
(agent core, guided mode, CLI) implemented on feature/mcp-agent-core; P3–P5
pending. Full design:
[unified MCP agent chat](../superpowers/specs/2026-10-05-mcp-agent-chat-design.md).
REST and web-chat retries keep the original job's `approved_via` and need no new
confirmation.

## Context

The web chat (`chat/coordinator.py`) calls `WeatherService` directly while the
console chat is the only MCP client. Both use the model for one structured
extraction per message and hand-written control flow. Behaviour tested in the
CLI is not exercised by the web, and web forms have no CLI counterpart.

## Decision

- One Python agent core (`AgentSession`) is a genuine MCP client with a
  tool-calling loop. The CLI runs it in-process; FastAPI hosts it for the
  browser. Both connect over the in-memory transport to one MCP server and one
  `JobRunner` per data root.
- Two distinct modes: agent mode (pluggable `ModelPort`, OpenAI default) and
  guided mode (rule-based forms), used automatically when the model is
  unavailable and selectable by the user.
- Forms are typed Interactions produced by host ask-tools and rendered by both
  the web (cards) and the CLI (text forms).
- The host enforces location review (including standard-time offsets), product
  choice and grounded years before planning, and plan approval before submit.
  Submit, cancel, retry, export and upload are not model tools.
- `weather_submit`, the legacy `weather_fetch` alias and `job_retry_failed`
  each require an MCP elicitation confirmation (for a retry, the confirmation
  names the failed job and its original plan hash). The openepw host answers it
  only for a recorded user approval; other clients show their own confirmation;
  clients without elicitation receive `APPROVAL_REQUIRED`. No model-callable
  approval token exists.

## Consequences

- Product offers and location offset review move from the chat layer into
  `WeatherService` and gain MCP tools.
- Several MCP tools gain typed schemas, field-level errors and a split between a
  model summary and structured data.
- `ChatCoordinator`, `ReferenceAgent`, `ChatSession`, `GraphChatSession` and
  `/v1/chat/*` are retired after both renderers pass the shared scenario evals.
- External MCP clients see these behaviour changes:
  - Submission (`weather_submit` and the `weather_fetch` alias) and retrying
    failed work (`job_retry_failed`, confirmed against the original job and
    plan hash) need a confirmation.
  - Text content is now a short summary; the full data is in
    `structuredContent`. v0.1 clients that parsed JSON from the text must read
    `structuredContent` instead.
  - Tools no longer publish an `outputSchema`.
  - Error text is a bare JSON object `{code, message, retryable}` (plus
    `details` or `correlation_id`), including for invalid arguments, with no
    "Error executing tool" prefix.
