# Production MCP: coordinated plan for Stages 3a–6

Status: owner approved autonomous Stages 3a–6 implementation on 2026-09-25 by instructing "start now" after plan review. Stage 1 is accepted and Stage 2 is complete. Work remains on `feature/mcp` in the current checkout. The `feature/data-avail` Stage 1 follow-up was reviewed and merged at `0f79ab3`; its ignored local source files were not moved into this checkout.

**Goal:** Deliver a validated local MCP weather workflow, including a reference agent, without losing scientific meaning or request-to-artifact traceability between stages.

**Architecture:** The Python service owns evidence, planning, weather operations, QC, jobs and artifacts. REST, CLI and MCP expose the same facts. The optional agent consumes MCP and explains service results. The pilot exercises the integrated system.

**Tech stack:** Existing Python 3.11+, Pydantic, SQLite/filesystem, pytest and the optional MCP SDK. Agent framework choice remains a Stage 5 evidence-based decision. No mandatory distributed service.

**Sources of truth:** [Owner-reviewed program allocation](../../plans/2026-09-24-production-mcp-program.md), [ADR 0003](../../decisions/0003-mcp-availability-and-batches.md), [Stage 2 acceptance](../../validation/mcp-stage-2-acceptance.md) and [future-method contract](../../methods/future-weather.md). The stage-specific plans below control implementation after owner review.

## Merged availability evidence and work allocation

The accepted Stage 1 snapshot and 61 reviewed OneBuilding annotations remain
the service baseline. The merged branch adds a local research map and an offline
CMIP6 license-scope derivation. Neither was imported into the active Stage 2
catalog. The map's NSRDB layer represents 2,018,267 grid sites for the exact
GOES TMY v4 `published_name:tdy-2023` selector, generalized to 53,723 display
cells. Its `v4.0.0` object path and internal `4.0.1` model attribute both remain
in provenance. It cannot establish eligibility at an unprobed point, actual-year
2023 availability, complete hourly data or simulation readiness. PVGIS SARAH3
is an approximate source-region drawing, and the CMIP6 map has no geographic
footprint. See the [NSRDB source review](../../validation/mcp-stage-2/nsrdb-footprint-source-review.md),
[map acceptance record](../../validation/mcp-stage-2/nsrdb-footprint-acceptance.md),
[PVGIS evidence](../../validation/mcp-stage-2/pvgis-map-evidence.md) and
[CMIP6 license-scope addendum](../../validation/mcp-stage-1/cmip6-license-scope.md).

| Stage | Allocated follow-up |
| --- | --- |
| 3a | Preserve selector, evidence generation and `unknown` distinctions while planning/fetching. Keep the map separate from retrieval eligibility; no NSRDB footprint import is required for batch acceptance. |
| 3b | Review the pinned CMIP6 catalog/WCRP model-license join at future preflight. Use available local `analysis.json` only if its accepted inputs are valid; otherwise use independently available accepted registry evidence or return a typed unknown. Keep original store terms, window coverage and geographic coverage separate. |
| 4 | Expose service evidence and QC through MCP without promoting map display cells or license counts into a positive availability claim. |
| 5 | Evaluate the agent on the published-name versus actual-year distinction, uncertain geography and model-license versus climate-window distinction. |
| 6 | Include a real-client negative case for an unprobed NSRDB selector/location and a CMIP6 model with allowed license but unverified window; record the resulting explanation. |

The source-coordinate `meta.bin`, map output and derived `analysis.json` remain
ignored local artifacts. An optional later NSRDB service import needs a separate
selector-bound contract, validated local source identity and a new catalog
generation; it does not restart Stage 1 collection. No generated manifest is
tracked in Git or assumed present in this checkout.

## Sequence and interfaces

| Stage | Main deliverable | Stable handoff required by the next stage |
| --- | --- | --- |
| [3a: weather fetching](2026-09-25-mcp-stage-3a-weather-fetch.md) | Occurrence-aware plans, durable batch jobs, QC and compact export | Plan hash, batch rows, output IDs, job IDs, artifact IDs and manifest/QC references |
| [3b: future weather](2026-09-25-mcp-stage-3b-future-weather.md) | Both baseline paths and both distinct future methods through jobs/artifacts | Typed baseline reference; source lineage and QC; explicit method, scenario and climate windows; future plan/job IDs |
| [4: local MCP](2026-09-25-mcp-stage-4-local-mcp.md) | Stable local stdio tools/resources/errors and real-session tests | Bounded schemas and resource URIs that expose the same service identities |
| [5: harness and evaluation](2026-09-25-mcp-stage-5-agent-harness.md) | Optional runnable reference agent and reproducible evaluations | Tested agent tasks, redacted traces and known failure modes |
| [6: local pilot](2026-09-25-mcp-stage-6-local-pilot.md) | Reference agent and real MCP client acceptance, with a limited live matrix | Local release report and explicit residual limits |

After final owner approval, implement in that order without routine stage-by-stage approval gates. Stage 3b design fixtures, Stage 4 contract examples and Stage 5 evaluation tasks can be prepared while earlier work proceeds; production wiring waits for the preceding interface to pass acceptance. Stage 6 client setup and its scorecard can begin early; integrated pilot runs wait for Stages 4–5. Cross-stage fixture names and intended assertions are stable, while tests are updated to the implemented wire schema rather than duplicating science in adapters.

## Owner clarifications for final review

The owner answered the cross-stage questions on 2026-09-25:

1. Return the revised plans for **final approval** before starting Stage 3a. Once approved, execute Stages 3a–6 autonomously on this branch, with the repository's exceptional escalation boundaries and no routine intermediate approval gate.
2. `.env` is immutable unless the owner later instructs otherwise. Approved live tests may read it; never edit, overwrite, move, copy into artifacts, display values or stage it. Offline tests remain credential-free. Stage-specific test runners explicitly load only the needed values into process memory.
3. Future baseline workflows must cover a recently fetched OpenEPW artifact **by ID** and a **user-provided EPW upload**. Stage 4 also offers bounded local file registration under configured allowed roots; upload and ID reuse are the required end-to-end stories.
4. Opt-in agent tests use OpenAI `gpt-6-luna` as the lower-cost primary model, subject to account availability and current API terms. The [official model page](https://developers.openai.com/api/docs/models/gpt-6-luna) lists the API ID and pricing. The deterministic harness stays model-free; LangSmith is not called and no traces leave the machine in this program.
5. Stage 6 acceptance requires reference-agent **and real MCP client** end-to-end runs on the current Windows setup. Human participant sessions and a separate desktop host are useful later evidence, but are not required for this local release. The report must not claim real-user usability was tested.
6. Small-to-medium, bounded live smoke tests are authorized after final plan approval. Keep cumulative billable API usage for Stages 3a–6 **below US$10**. Estimate before calls, track observed usage/cost locally without keys, and stop new billable calls at an US$8 projected total to leave margin. Unknown-price or new paid terms/accounts are outside this authorization. Record skipped cases instead of exceeding the cap.

## Shared acceptance stories

| Story | 3a | 3b | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- |
| A: full actual-year Ithaca point with explicit alternative | plan → EPW/QC | fetched baseline | MCP discovery → job → artifact | agent choice/explanation | agent/client task |
| B: published OneBuilding multi-location TMYx, shared exact URL, duplicate and unsupported occurrence | mapping, partial job, compact export | optional fetched baseline | MCP batch inspection/export | agent handles partial result | agent/client task |
| C: user-uploaded and fetched-artifact-ID baselines at the same study location for morphing; a separate supported PUMA case for hourly profiles; unsupported contrasts | fetched inputs | both methods on their own footprints; scenario/window/QC | MCP upload/ID/future tools | agent clarifies and explains | agent/client task |
| G: NOAA hourly gap, `warn` and `error` policies | sentinel/QC or failed output | reject incomplete baseline for methods that require completeness | resource and error truthfulness | never call sentinel EPW simulation-ready | end-to-end user-visible regression |

Use synthetic or redistribution-safe offline fixtures for deterministic breadth. Live checks are small, opt-in and never replace offline evidence. A supported catalog result means eligible to attempt retrieval, not complete hours or a simulation-ready EPW. Unknown, unsupported, access blocked, retrieval failed and QC limited retain distinct meanings through every surface.

## Contracts that must stay aligned

1. **Identity:** Keep requested occurrence, selected dataset/product, native fetch task, output intent, emitted artifact and job as different IDs. An exact shared native fetch may produce separate per-occurrence EPWs. Persisted plan hashes remain integrity references, not authorization.
2. **Baseline:** Stage 3b resolves a user-uploaded EPW or a Stage 3a weather artifact ID to an immutable checksummed baseline. The future manifest links the exact baseline artifact and, when present, its source manifest/QC; it never infers provider identity from an EPW header. Stage 4 accepts a bounded local upload and artifact-ID reuse, with an allowlisted-path convenience route under explicit local file-access rules.
3. **Climate meaning:** Actual year, published TMY source years, reference climate period, future climate period, target-year shorthand, SSP/RCP scenario and profile remain separate. Monthly morphing transforms the baseline; hourly climate-profile selection uses coherent trajectories and the input baseline as a comparison identity. Unsupported combinations fail explicitly.
4. **Evidence and quality:** Stage 1 accepted annotations and local snapshots are preserved. Later evidence changes are separately reviewed generations. `analysis.json` remains local and fingerprint-checked if used; absence falls back to bundled contracts with typed unknowns. The merged map and derived license counts are not active service evidence by themselves. QC, missing-data policy, per-variable provenance and `simulation_ready=false` remain visible through MCP and the agent.
5. **Artifact access:** Normal tool results contain summaries, IDs and bounded links, not hourly tables or raw inventories. Every referenced artifact is checksum-checked and confined to the configured data root. Explicit compact export does not establish redistribution rights.
6. **Durability:** Long work returns a job ID. Client disconnect does not cancel it; inspect, cancel and explicit retry use canonical job state. Reuse is limited to verified within-job native fetches and existing raw cache; previous-run weather/QC reuse stays outside this program.

## Review and execution checkpoints

- The owner reviewed these five linked plans and explicitly authorized implementation on 2026-09-25. Preserve the upload/ID baseline boundary, plan/job wire identities, MCP tool names, harness evaluation rubric, US$10 cumulative cap and agent/client pilot during execution.
- At each stage start, compare the preceding stage's actual acceptance record with this plan. If its interface differs, amend downstream plans before writing code. Routine implementation choices after the relevant plan approval remain autonomous under `AGENTS.md`.
- At each stage exit, run focused and regression checks, publish an acceptance record with actual results/limits, update architecture/features/roadmap/provider notes as appropriate, and commit at feature/test/docs boundaries using `fix(topic): concise description`.
- Stop only for the repository's human-intervention boundaries. A blocked provider is reproduced, classified and given a practical fallback; it does not hold the whole program hostage or receive a false live-acceptance claim.

## Deferred work

Team deployment, authentication/isolation for self-hosting, PyPI publication, prior-run weather/QC reuse, a new frontend, sampled future weather and historical TMY/XMY generation are outside this local program. The merged research evidence may enter a future catalog generation only after source-specific review; Stage 1 collection does not restart.
