# Production MCP: coordinated plan for Stages 3a–6

Status: draft for owner review, 2026-09-25. This coordinates the remaining work; it does not authorize implementation. Stage 1 is accepted and Stage 2 is complete. Work remains on `feature/mcp` in the current checkout; a contributor's separate evidence branch is reviewed independently.

**Goal:** Deliver a validated local MCP weather workflow, including a reference agent, without losing scientific meaning or request-to-artifact traceability between stages.

**Architecture:** The Python service owns evidence, planning, weather operations, QC, jobs and artifacts. REST, CLI and MCP expose the same facts. The optional agent consumes MCP and explains service results. The pilot exercises the integrated system.

**Tech stack:** Existing Python 3.11+, Pydantic, SQLite/filesystem, pytest and the optional MCP SDK. Agent framework choice remains a Stage 5 evidence-based decision. No mandatory distributed service.

**Sources of truth:** [Owner-reviewed program allocation](../../plans/2026-09-24-production-mcp-program.md), [ADR 0003](../../decisions/0003-mcp-availability-and-batches.md), [Stage 2 acceptance](../../validation/mcp-stage-2-acceptance.md) and [future-method contract](../../methods/future-weather.md). The stage-specific plans below control implementation after owner review.

## Sequence and interfaces

| Stage | Main deliverable | Stable handoff required by the next stage |
| --- | --- | --- |
| [3a: weather fetching](2026-09-25-mcp-stage-3a-weather-fetch.md) | Occurrence-aware plans, durable batch jobs, QC and compact export | Plan hash, batch rows, output IDs, job IDs, artifact IDs and manifest/QC references |
| [3b: future weather](2026-09-25-mcp-stage-3b-future-weather.md) | Both baseline paths and both distinct future methods through jobs/artifacts | Typed baseline reference; source lineage and QC; explicit method, scenario and climate windows; future plan/job IDs |
| [4: local MCP](2026-09-25-mcp-stage-4-local-mcp.md) | Stable local stdio tools/resources/errors and real-session tests | Bounded schemas and resource URIs that expose the same service identities |
| [5: harness and evaluation](2026-09-25-mcp-stage-5-agent-harness.md) | Optional runnable reference agent and reproducible evaluations | Tested agent tasks, redacted traces and known failure modes |
| [6: local pilot](2026-09-25-mcp-stage-6-local-pilot.md) | Real client/user acceptance and release evidence | Local release report and explicit residual limits |

Implement in that order. Stage 3b design fixtures, Stage 4 contract examples and Stage 5 evaluation tasks can be prepared while earlier work proceeds; production wiring waits for the preceding interface to pass acceptance. Stage 6 pilot recruitment/client selection and its scorecard can begin early; actual pilot runs wait for Stages 4–5. Cross-stage fixture names and intended assertions are stable, while tests are updated to the implemented wire schema rather than duplicating science in adapters.

## Shared acceptance stories

| Story | 3a | 3b | 4 | 5 | 6 |
| --- | --- | --- | --- | --- | --- |
| A: full actual-year Ithaca point with explicit alternative | plan → EPW/QC | fetched baseline | MCP discovery → job → artifact | agent choice/explanation | target client/user task |
| B: published OneBuilding multi-location TMYx, shared exact URL, duplicate and unsupported occurrence | mapping, partial job, compact export | optional fetched baseline | MCP batch inspection/export | agent handles partial result | target client/user task |
| C: one local and one fetched baseline at the same study location for morphing; a separate supported PUMA case for hourly profiles; unsupported contrasts | fetched inputs | both methods on their own footprints; scenario/window/QC | MCP baseline/future tools | agent clarifies and explains | target client/user task |
| G: NOAA hourly gap, `warn` and `error` policies | sentinel/QC or failed output | reject incomplete baseline for methods that require completeness | resource and error truthfulness | never call sentinel EPW simulation-ready | end-to-end user-visible regression |

Use synthetic or redistribution-safe offline fixtures for deterministic breadth. Live checks are small, opt-in and never replace offline evidence. A supported catalog result means eligible to attempt retrieval, not complete hours or a simulation-ready EPW. Unknown, unsupported, access blocked, retrieval failed and QC limited retain distinct meanings through every surface.

## Contracts that must stay aligned

1. **Identity:** Keep requested occurrence, selected dataset/product, native fetch task, output intent, emitted artifact and job as different IDs. An exact shared native fetch may produce separate per-occurrence EPWs. Persisted plan hashes remain integrity references, not authorization.
2. **Baseline:** Stage 3b resolves a registered local EPW or a Stage 3a weather artifact to an immutable checksummed baseline. The future manifest links the exact baseline artifact and, when present, its source manifest/QC; it never infers provider identity from an EPW header. Stage 4 registers or references baselines under explicit local file-access rules.
3. **Climate meaning:** Actual year, published TMY source years, reference climate period, future climate period, target-year shorthand, SSP/RCP scenario and profile remain separate. Monthly morphing transforms the baseline; hourly climate-profile selection uses coherent trajectories and the input baseline as a comparison identity. Unsupported combinations fail explicitly.
4. **Evidence and quality:** Stage 1 accepted annotations and local snapshots are preserved. Later evidence changes are separately reviewed generations. `analysis.json` remains local and fingerprint-checked if used; absence falls back to bundled contracts with typed unknowns. QC, missing-data policy, per-variable provenance and `simulation_ready=false` remain visible through MCP and the agent.
5. **Artifact access:** Normal tool results contain summaries, IDs and bounded links, not hourly tables or raw inventories. Every referenced artifact is checksum-checked and confined to the configured data root. Explicit compact export does not establish redistribution rights.
6. **Durability:** Long work returns a job ID. Client disconnect does not cancel it; inspect, cancel and explicit retry use canonical job state. Reuse is limited to verified within-job native fetches and existing raw cache; previous-run weather/QC reuse stays outside this program.

## Review and execution checkpoints

- Review these five linked plans together, especially the baseline registration boundary, plan/job wire identities, MCP tool names, harness evaluation rubric and pilot client/users. Record any owner changes in the affected plan before implementation. Planning alone is authorized; no remaining-stage implementation is inferred from this draft.
- At each stage start, compare the preceding stage's actual acceptance record with this plan. If its interface differs, amend downstream plans before writing code. Routine implementation choices after the relevant plan approval remain autonomous under `AGENTS.md`.
- At each stage exit, run focused and regression checks, publish an acceptance record with actual results/limits, update architecture/features/roadmap/provider notes as appropriate, and commit at feature/test/docs boundaries using `fix(topic): concise description`.
- Stop only for the repository's human-intervention boundaries. A blocked provider is reproduced, classified and given a practical fallback; it does not hold the whole program hostage or receive a false live-acceptance claim.

## Deferred work

Team deployment, authentication/isolation for self-hosting, PyPI publication, prior-run weather/QC reuse, a new frontend, sampled future weather and historical TMY/XMY generation are outside this local program. The separate evidence follow-up may join as a new accepted catalog generation; Stage 1 collection does not restart.
