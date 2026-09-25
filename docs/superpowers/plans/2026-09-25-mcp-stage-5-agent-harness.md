# Stage 5 implementation plan: optional agent harness and evaluations

Status: revised draft for final owner approval, 2026-09-25. Implement after the Stage 4 MCP contract is accepted and the coordinated plan receives final approval; draft evaluation cases can be prepared earlier.

> **For agentic workers:** Use `superpowers:executing-plans` after approval. Make the deterministic evaluation fail for each required behavior before implementing it, verify and commit increments. Checkboxes are execution tracking, not additional human gates.

**Goal:** Provide a runnable reference agent that guides a local user through the MCP tools, plus reproducible evidence that it chooses tools and explains uncertainty, provenance and QC appropriately.

**Architecture:** An optional harness is an MCP client with explicit conversation state and a swappable model adapter. It calls only Stage 4 public tools/resources. The Python service remains authoritative for source eligibility, plans, jobs, QC and scientific transformations. No agent-only weather API or new mandatory core dependency.

**Tech stack:** Begin with a small direct Python harness. Compare the same tasks with a minimal LangGraph/LangChain prototype before deciding whether its state/persistence machinery earns an optional dependency. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence) and the [LangChain MCP adapter](https://docs.langchain.com/oss/python/langchain/mcp) are current candidates. Opt-in real-model smoke uses OpenAI [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna), low reasoning effort through the Responses API, with bounded outputs and a configurable model ID. LangSmith is not used or contacted; all evaluation records remain local. Pin any chosen optional stack and document its data behavior.

**Spec:** [Coordinated stages](2026-09-25-mcp-remaining-stages.md), [program allocation](../../plans/2026-09-24-production-mcp-program.md), [Stage 4 contract](2026-09-25-mcp-stage-4-local-mcp.md).

## Agent behavior contract

1. Parse user intent into location, purpose, actual/published/future product, dates or climate windows, required variables, preferred sources and missing-data policy. Ask for a missing choice when it materially changes the result, especially ambiguous place, multiple plausible products, baseline/reference period, unsupported climate method or export destination. Do not fabricate a choice or make an implicit provider switch.
2. Ask MCP for eligibility and alternatives, preserving supported/unknown/unsupported, evidence age, access requirements and source health. Explain why a recommended choice fits the stated purpose; do not state that a catalog match guarantees complete weather or simulation readiness.
3. Create an inspectable plan, show material plan choices and estimated cost/limitations, then submit using its `plan_hash`. The user-facing plan review is part of the harness flow; it is not a new repository implementation approval gate. Respect the host's tool-invocation confirmation behavior.
4. Poll or resume a durable job by ID, including after harness restart. Show per-occurrence failures/unsupported rows and successful artifacts separately. Retry only failed identities on an explicit user request or a documented safe policy; never rerun successful members or silently select another source.
5. Inspect manifest and QC before describing an EPW's use. State NOAA gaps, sentinels and `simulation_ready=false` plainly; under strict policy explain that no EPW was emitted. For future output, describe baseline origin, method, scenario, reference/target windows, model/member or coherent year, source limits and unchanged variables.
6. Keep local paths, secrets, raw hourly tables and full metadata inventories out of prompts and local evaluation records. Artifacts are referenced by IDs and summarized through MCP. Do not invoke LangSmith or send run data to any tracing service during this program, even if a key exists.

## Evaluation rubric and fixtures

Use stories A, B, C and G from the coordinated plan as gold tasks. Add ambiguous place names, stale/unknown availability, provider outage/credential gate, retry after partial success, invalid baseline, unsupported SSP/RCP cross-method choice, cancelled job and corrupted artifact. Synthetic MCP transcripts and a deterministic model stub cover every required branch offline. A small-to-medium opt-in `gpt-6-luna` run checks natural-language quality without making nondeterministic output a required CI gate. Read `.env` only into test-process memory, never change it, and keep model/provider billable usage under the coordinated US$10 cumulative cap.

Score each task on: required tool calls and order; scientific choices and explicit clarification; plan hash submitted unchanged; correct per-occurrence/job/artifact accounting; explicit uncertainty/QC/provenance in the final explanation; recovery without duplicate work; bounded calls/tokens/elapsed time; and redaction. Block acceptance on critical failures: wrong geography without clarification, fabricated availability, silent source switch, unsupported future method, treating a sentinel EPW as simulation-ready, or leaking a credential. Numeric thresholds for the rest are defined in the checked-in rubric before harness tuning, then held fixed for comparison.

| File/area | Planned role |
| --- | --- |
| `src/openepw/harness/` or optional examples package | MCP client, conversation state, model adapter and user-facing entry point; optional dependency boundary |
| `tests/harness/` | Deterministic scripted MCP/model fixtures, rubric and regression cases |
| `docs/harness/` | Flow, stack comparison, prompts/tool-use policy, privacy and local setup |
| `docs/validation/mcp-stage-5-acceptance.md` | Versioned rubric results, local redacted run records and residual agent limitations |

### Task 1: Freeze evaluation tasks before stack selection

- [ ] Create concise task fixtures and expected MCP events for A/B/C/G and the adversarial cases. Write failing rubric tests for the critical failures above, including the sparse-NOAA final explanation. Represent allowed clarification outcomes separately from wrong automatic assumptions.
- [ ] Record what local run records may store: tool names, IDs, statuses, bounded safe summaries, durations and redacted prompt text. Add a test that secrets, file paths and hourly arrays are absent from persisted records. Assert hosted tracing is disabled regardless of an available LangSmith key.
- [ ] Run the rubric tests and commit `fix(tests): define MCP agent evaluation cases`.

### Task 2: Minimal direct MCP harness

- [ ] Write failing tests with a deterministic model stub for clarify → assess/discover → plan → submit → inspect → QC → explain, plus disconnect/restart and partial-job recovery. Drive a real Stage 4 MCP server in at least one test rather than mocking every tool response.
- [ ] Implement minimal state and MCP client calls. Store only conversation/job/plan IDs and safe summaries; inspect canonical MCP facts when resuming. Keep prompts as guidance about the tool contract, not copies of provider/quality algorithms. Make any model API optional through a local configuration interface.
- [ ] Run the offline suite and commit `fix(harness): add local reference MCP agent`.

### Task 3: Framework comparison and stack decision

- [ ] Build a bounded prototype of the same A/G and partial-recovery tasks with LangGraph/LangChain MCP integration, using the same fixed rubric and synthetic service. Compare correctness, restart behavior, complexity, install size, trace control and extra dependencies against the direct harness.
- [ ] Choose the simpler implementation that meets the rubric. If LangGraph materially improves the evaluated state/recovery flow, keep it as an optional `harness` extra; otherwise retain the direct harness and document why. Both alternatives use local evaluation records; neither calls LangSmith.
- [ ] Save the comparison and chosen dependency boundary in `docs/harness/stack-decision.md`; commit `fix(docs): record agent harness stack decision`.

### Task 4: Full evaluation and user-facing explanations

- [ ] Run every offline fixture through the chosen harness, then a bounded `gpt-6-luna`/real-MCP-client smoke with the owner-provided key after final approval. Set per-call output and request limits, estimate cost using current official pricing before the run, add actual token usage to a local cumulative ledger, and stop before the US$10 limit. If the model is unavailable for the account, classify that exact restriction and retain offline acceptance without silently switching to a costlier model. Record local tool events, rubric scores, failures and corrections. Test that an eligible-but-gapped NOAA retrieval yields an explicit QC warning and no readiness claim.
- [ ] Add user-facing examples for actual-year point, published batch and future from both baseline paths. Verify the harness can explain partial output mapping, compact export and method-specific future limits without exposing secrets or bulk weather data.
- [ ] Run full relevant tests, Ruff, mypy and build; update `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/limitations.md`. Review material failures, fix and rerun; create `docs/validation/mcp-stage-5-acceptance.md`; commit `fix(docs): record Stage 5 agent acceptance`.

## Exit and Stage 6 handoff

Stage 5 exits with an optional runnable reference agent, a fixed local evaluation suite and local redacted run records showing the selected anchor and recovery tasks pass the rubric. Any real-model variability or host-specific behavior is recorded, not hidden. Stage 6 uses this harness and the Stage 4 MCP contract through a real local client session; human participant sessions are deferred.
