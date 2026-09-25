# Stage 6 implementation plan: local pilot and release acceptance

Status: revised draft for final owner approval, 2026-09-25. Pilot execution follows Stage 4/5 acceptance and final approval of the coordinated plan. Client setup and a scorecard may be prepared earlier.

> **For agentic workers:** Use `superpowers:executing-plans` after approval. Record observed agent/client results and reproduce defects with focused tests before fixing them. Checkboxes track work, not extra human approval gates.

**Goal:** Show that an MCP-connected reference agent and a real local MCP client can find suitable weather, retrieve or generate traceable EPWs, and explain uncertainty, QC and partial results on supported workflows.

**Architecture:** Exercise the released Python service through the Stage 4 stdio MCP server and Stage 5 reference harness on the current Windows setup, using an actual MCP SDK client session for protocol calls. Keep deterministic offline suites as the regression base; add bounded opt-in provider and OpenAI model checks. No human participant, separate desktop host, team deployment, hosted service or public publication is required for this release.

**Tech stack:** Existing package extras and test tools, the tested local stdio MCP SDK client, optional `gpt-6-luna` access, synthetic fixtures, and a bounded live provider matrix. The pilot does not add a mandatory runtime dependency or hosted tracing.

**Spec:** [Coordinated stages](2026-09-25-mcp-remaining-stages.md), [program allocation](../../plans/2026-09-24-production-mcp-program.md), [Stage 4 contract](2026-09-25-mcp-stage-4-local-mcp.md), [Stage 5 harness](2026-09-25-mcp-stage-5-agent-harness.md).

## Pilot frame and owner decisions

The pilot target is the workflow of a building-energy researcher/modeler or EnergyPlus user, expressed as fixed task prompts. The owner accepted reference-agent plus real-client end-to-end evidence for this stage. Use the current Windows host and the installed MCP SDK stdio client as the default tested client; record exact versions and whether it can read EPW resources or only artifact metadata. A separate desktop LLM host and human participant sessions are deferred. Do not infer actual user comprehension or cross-platform behavior from scripted tests.

The pilot scorecard measures: task completion; correct geography/product/time/method choices; whether the agent explicitly explains alternatives and unknowns; plan/job/artifact navigation; provenance and QC explanation; handling of gaps/partial failures; startup/reconnect; and bounded latency/requests/cost. Predefine pass/fail for critical scientific claims. Record observed model/client output separately from deterministic assertions and distinguish offline synthetic from opt-in live evidence.

## Acceptance matrix

| Case | User task and evidence expected |
| --- | --- |
| A: actual-year Ithaca point | Resolve place, compare at least two eligible/uncertain alternatives, plan exact year, submit, inspect EPW and QC, explain source/period and readiness limit. |
| B: published OneBuilding batch | Show exact product and shared native URL where verified, separate duplicate requested occurrences, retain unsupported location, inspect per-output results and optional compact export mapping. |
| C1: user-uploaded baseline future | Upload a complete user EPW, receive a checksummed artifact ID, state unknown provider origin where applicable, choose supported morph SSP/window, inspect baseline and variable lineage. Test allowlisted local-path registration separately. |
| C2: fetched-artifact-ID baseline future | Use A's already produced artifact ID for the second morph baseline path; separately fetch a baseline at a supported PUMA site for hourly profile RCP/window acceptance. Preserve each fetched manifest/QC and explain why the hourly method's baseline is a comparison identity. |
| C3: unsupported future contrast | Reject unsupported scenario/window/site/profile or SSP/RCP cross-method choice without fabricated substitution. |
| G: NOAA hourly gap | `warn`: inspect sentinel-bearing EPW and QC, never call it simulation-ready. `error`: inspect failed row and absence of EPW; other batch outputs remain available. |
| Recovery and negative cases | Ambiguous place, stale/unknown evidence, provider/credential failure, disconnect/reconnect, cancellation, retry of failed output, corrupt artifact and bounded invalid input. |

Use synthetic/redistribution-safe data for the full matrix. A small-to-medium live matrix may include bounded actual weather, one named published product, one supported future source and `gpt-6-luna` agent runs only when terms, credentials, resource estimates and provider access permit. Across Stages 3a–6, cumulative billable API usage stays below US$10, with no new calls once the projected total reaches US$8. Read `.env` only for authorized tests; never modify or stage it. LangSmith is not used. The pilot report names skipped live cells and does not claim acceptance for them. Stage 1 collection is not repeated.

### Task 1: Lock the pilot setup and scorecard

**Files:** Create `docs/pilot/setup.md`, `docs/pilot/scorecard.md`, `tests/pilot/test_install_smoke.py`.

- [ ] Record Windows/client/SDK versions and local install command. Run a clean environment install of only documented extras, launch stdio MCP, list tools/resources, and connect the reference harness. Document any host resource-size or path limitations.
- [ ] Fix the scorecard before running pilot tasks. Keep credentials, private prompts and redistributed provider data out of Git. Record that human usability and any untested desktop host/OS remain outside this acceptance.
- [ ] Commit `fix(docs): prepare local MCP pilot`.

### Task 2: Offline integrated journeys

**Files:** Add `tests/pilot/test_journeys.py` and synthetic fixtures; update setup if a client setting is wrong.

- [ ] Run A, B, C1/C2/C3, G and negative/recovery cases through actual stdio MCP sessions and the harness. Check exact plan/job/output/artifact IDs across surfaces, resource access, batch mapping, climate meanings and QC messages. Use a real client session in addition to direct service calls.
- [ ] Turn any observed material bug into a focused failing regression in the owning layer, fix there, rerun the journey and document the correction. Keep provider science in the service; no pilot-only data fixes or prompt workaround for a core defect.
- [ ] Commit code/test fixes at the relevant boundaries with `fix(topic): ...` messages.

### Task 3: Agent and real-client pilot

**Files:** Add results under `docs/pilot/` and `docs/validation/mcp-stage-6-acceptance.md`.

- [ ] Run fixed A/B/C/G prompts through the reference agent and an actual stdio MCP client session. Capture tool choices, plan hashes, job/artifact navigation and final explanations of alternatives, partial results and QC. Record only redacted local run evidence. The user-provided EPW upload and fetched artifact ID must be separate observed paths.
- [ ] Record client/platform version, setup time, successes, model mistakes, protocol/resource limits and repeated failures. Triage material defects into tests/fixes and rerun affected tasks. A missing desktop host or participant does not block this owner-approved agent/client scope; list each as untested.
- [ ] Run the bounded opt-in live matrix within provider terms and the cumulative budget; record actual calls, dataset/version/date, model/token usage, cost estimate and QC outcome without credentials. A refused or unavailable provider/model is classified and documented with a practical fallback.

### Task 4: Release acceptance and handoff

**Files:** Update `README.md`, `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/limitations.md`, client setup and provider notes; complete `docs/validation/mcp-stage-6-acceptance.md`.

- [ ] Run the complete deterministic suite, MCP/harness/pilot tests, Ruff, mypy and build on the target local setup. Check package extras, installation, stdio startup, reconnect, resource bounds, license/attribution in artifacts and no bundled raw inventories/secrets. Run an EnergyPlus consumption smoke only if the selected local pilot scope provides the tool; otherwise state that simulator validation was not performed.
- [ ] Review scorecard and unresolved defects against the agreed local stories. Fix material issues, rerun affected checks and write an honest release report with tested clients/OS/providers, skipped cells, residual science/quality limits and known access barriers. Keep `simulation_ready=false` unless a separately justified certification policy exists.
- [ ] Commit `fix(docs): record local MCP pilot acceptance`. Publication, team hosting and cross-run weather reuse remain separate future decisions.

## Exit condition

Stage 6 is complete when the reference agent and a real local MCP client complete the selected stories end to end on the tested Windows setup, critical science/QC claims pass, material defects are resolved, and actual local results and limits are recorded. Human participant usability, other clients/OS and simulator certification remain explicitly untested unless separately performed. The current production MCP program ends here.
