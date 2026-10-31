# ADR 0005 — One MCP agent core for web and CLI chat

Date: 2026-10-05. Status: design agreed with the owner on 2026-10-04/05; P1
(service moves and MCP contract) implemented on feature/mcp-agent-chat; P2
(agent core, guided mode, CLI) implemented on feature/mcp-agent-core; P3
(agent mode, model port, evals) implemented on feature/mcp-agent-mode; P4–P5
pending. In the openepw host's agent mode, `weather_locations_review` and
`weather_product_offers` are reached only through the `review_location` and
`choose_products` ask-tools, so every review shows the person a form; the MCP
access classes for external clients are unchanged. Full design:
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

## Note (2026-10-09): guardrails

The agent chat's defences against irrelevant and malicious prompts are a run setting, not part
of this decision's gates: a security profile (YAML) chooses moderation, strike limits and what
happens at the limit, the link allowlist and the knowledge-answer length. The gates above are
unchanged and apply under every profile; a profile cannot weaken plan approval or one-shot
submission confirmation. See the
[guardrail plan](../superpowers/plans/2026-10-09-agent-guardrails.md) and the
[agent README](../agent/README.md#security-profiles-and-guards).

## Note (2026-10-27): availability lookups

The agent's model gains one host lookup tool, `look_up_products`, so it can answer availability
questions in words. A lookup is read-only: it opens no form, records nothing in the session facts
and returns no `request` objects, so plans still take their datasets only from offers the person
chose on the product form. Its points must be ones the session has seen and its years ones the
person wrote; a lookup for places that are not approved carries a fixed host label. Reviews and
product choices are still forms, `weather_locations_review` and `weather_product_offers` stay hidden
from the agent's model, and the gates above are unchanged. See the
[request lookups design](../superpowers/specs/2026-10-13-agent-request-lookups-design.md).

## Note (2026-10-31): request parts, summary and Change

A request has four parts (place, product preference, products, years), each with a status derived
from the facts. Plans use confirmed parts only: years written in a question are only proposed, and
`weather_plan` with them is refused with `GATE_REQUIRED`, need `review_request`. A new form,
the request summary (`request_summary`, gate `review_request`), lists the parts; approving it
confirms what is proposed. The model opens it with the new ask-tool `review_request`; the host
opens it when a plan needs a proposed part and on request. The plan review and the summary offer a
Change action per part; Change is a host path in both modes, with no model call: the plan and its
approval reset and only that part's form opens. A change to one part resets only what depends on
it (a new place leaves the chosen products to recheck; new years keep products still offered).
Run still approves exactly the plans shown, and the other gates above are unchanged. See the
[request slots design](../superpowers/specs/2026-10-30-agent-request-slots-design.md).
