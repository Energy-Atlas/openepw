# Stage 6 implementation plan: local pilot and release acceptance

Status: draft for owner review, 2026-09-25. Pilot execution follows Stage 4/5 acceptance. Client/user selection and a scorecard may be prepared earlier.

> **For agentic workers:** Use `superpowers:executing-plans` after approval. Record observed client/user results and reproduce defects with focused tests before fixing them. Checkboxes track work, not extra human approval gates.

**Goal:** Show that real local users and an MCP-connected agent can find suitable weather, retrieve or generate traceable EPWs, and understand uncertainty, QC and partial results on supported workflows.

**Architecture:** Exercise the released Python service through the Stage 4 stdio MCP server and Stage 5 reference harness in at least one target LLM client. Keep deterministic offline suites as the regression base; add small opt-in live provider checks and structured user observations. No team deployment, hosted service or public publication.

**Tech stack:** Existing package extras and test tools, the selected local MCP host, optional model credentials, synthetic fixtures, and a small live provider matrix. The pilot does not add a mandatory runtime dependency.

**Spec:** [Coordinated stages](2026-09-25-mcp-remaining-stages.md), [program allocation](../../plans/2026-09-24-production-mcp-program.md), [Stage 4 contract](2026-09-25-mcp-stage-4-local-mcp.md), [Stage 5 harness](2026-09-25-mcp-stage-5-agent-harness.md).

## Pilot frame and owner inputs

The pilot target is a local building-energy researcher/modeler or EnergyPlus user. Before recruitment or platform-specific acceptance, record the actual host/client version, operating systems, participants/roles and whether the client can read EPW resources or only artifact metadata. If the owner has not named a client or participants, prepare the runnable internal pilot with the reference harness and one available MCP host, then present the remaining external-user acceptance gap explicitly. Do not infer a positive real-user result from scripted tests.

The pilot scorecard measures: task completion; correct geography/product/time/method choices; whether users understand alternatives and unknowns; plan/job/artifact navigation; provenance and QC comprehension; handling of gaps/partial failures; startup/reconnect; and bounded latency/requests. Predefine pass/fail for critical science and safety claims. Record observations separately from automated assertions and distinguish offline synthetic, opt-in live and real-user evidence.

## Acceptance matrix

| Case | User task and evidence expected |
| --- | --- |
| A: actual-year Ithaca point | Resolve place, compare at least two eligible/uncertain alternatives, plan exact year, submit, inspect EPW and QC, explain source/period and readiness limit. |
| B: published OneBuilding batch | Show exact product and shared native URL where verified, separate duplicate requested occurrences, retain unsupported location, inspect per-output results and optional compact export mapping. |
| C1: local baseline future | Register complete local EPW, state unknown provider origin where applicable, choose supported morph SSP/window, inspect baseline and variable lineage. |
| C2: fetched baseline future | Use A's artifact for the second morph baseline path; separately fetch a baseline at a supported PUMA site for hourly profile RCP/window acceptance. Preserve each fetched manifest/QC and explain why the hourly method's baseline is a comparison identity. |
| C3: unsupported future contrast | Reject unsupported scenario/window/site/profile or SSP/RCP cross-method choice without fabricated substitution. |
| G: NOAA hourly gap | `warn`: inspect sentinel-bearing EPW and QC, never call it simulation-ready. `error`: inspect failed row and absence of EPW; other batch outputs remain available. |
| Recovery and negative cases | Ambiguous place, stale/unknown evidence, provider/credential failure, disconnect/reconnect, cancellation, retry of failed output, corrupt artifact and bounded invalid input. |

Use synthetic/redistribution-safe data for the full matrix. A live matrix is limited to one bounded actual-weather request, one named published product and one supported future source only when terms, credentials, budgets and provider access permit. The pilot report names skipped live cells and does not claim acceptance for them. Stage 1 collection is not repeated.

### Task 1: Lock the pilot setup and scorecard

**Files:** Create `docs/pilot/setup.md`, `docs/pilot/scorecard.md`, `tests/pilot/test_install_smoke.py`.

- [ ] Record target client and OS/version, available participant roles and local install command. Run a clean environment install of only documented extras, launch stdio MCP, list tools/resources, and connect the reference harness. Document any host resource-size or path limitations.
- [ ] Fix the scorecard before running pilot tasks. Prepare consent/data handling for any participant notes; do not include credentials, private user prompts or redistributed provider data in Git. Keep an internal-only rehearsal distinct from a real participant result.
- [ ] Commit `fix(docs): prepare local MCP pilot`.

### Task 2: Offline integrated journeys

**Files:** Add `tests/pilot/test_journeys.py` and synthetic fixtures; update setup if a client setting is wrong.

- [ ] Run A, B, C1/C2/C3, G and negative/recovery cases through actual stdio MCP sessions and the harness. Check exact plan/job/output/artifact IDs across surfaces, resource access, batch mapping, climate meanings and QC messages. Use a real client session in addition to direct service calls.
- [ ] Turn any observed material bug into a focused failing regression in the owning layer, fix there, rerun the journey and document the correction. Keep provider science in the service; no pilot-only data fixes or prompt workaround for a core defect.
- [ ] Commit code/test fixes at the relevant boundaries with `fix(topic): ...` messages.

### Task 3: Target-client and user pilot

**Files:** Add results under `docs/pilot/` and `docs/validation/mcp-stage-6-acceptance.md`.

- [ ] Guide the selected users through representative A/B/C tasks in the named target client. Capture whether they can choose and explain source/time/method alternatives, find artifacts/QC and interpret partial or unsupported outcomes. Include G as a user-visible QC case. Record observed prompts/actions, paraphrased or redacted where needed, and note assistance required.
- [ ] Record client/platform version, setup time, successes, misunderstandings, protocol/resource limits and repeated failures. Triage material defects into tests/fixes; rerun affected tasks. Where participants or target client are unavailable, complete the internal rehearsal and mark external-user acceptance open rather than calling the stage complete.
- [ ] Do a small opt-in live matrix within provider terms; record actual calls, dataset/version/date, credential gate and QC outcome. A refused or unavailable provider is classified and documented with a practical fallback.

### Task 4: Release acceptance and handoff

**Files:** Update `README.md`, `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/limitations.md`, client setup and provider notes; complete `docs/validation/mcp-stage-6-acceptance.md`.

- [ ] Run the complete deterministic suite, MCP/harness/pilot tests, Ruff, mypy and build on the target local setup. Check package extras, installation, stdio startup, reconnect, resource bounds, license/attribution in artifacts and no bundled raw inventories/secrets. Run an EnergyPlus consumption smoke only if the selected local pilot scope provides the tool; otherwise state that simulator validation was not performed.
- [ ] Review scorecard and unresolved defects against the agreed local stories. Fix material issues, rerun affected checks and write an honest release report with tested clients/OS/providers, skipped cells, residual science/quality limits and known access barriers. Keep `simulation_ready=false` unless a separately justified certification policy exists.
- [ ] Commit `fix(docs): record local MCP pilot acceptance`. Publication, team hosting and cross-run weather reuse remain separate future decisions.

## Exit condition

Stage 6 is complete only when the selected real client/user stories work end to end, critical science/QC claims pass, material defects are resolved, and actual local results and limits are recorded. An internal-only rehearsal is useful evidence but does not satisfy the real-user part of this exit. The current production MCP program ends here.
