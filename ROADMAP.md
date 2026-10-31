# Roadmap

Open work is in the [outstanding work plan](docs/superpowers/plans/2026-10-30-outstanding-work.md):
seven phases, each implemented without supervision and reviewed by the owner when it ends. This page
summarises the work done so far, one section per line of work, and links its plans and records. The
detail lives in those documents and in git history.

## At a glance (2026-10-30)

| Line of work | State | Main records |
| --- | --- | --- |
| v0.1 implementation | Complete, 2026-09-20 | [v0.1 acceptance](docs/validation/v0.1-acceptance.md), [Stage 2 ledger](docs/validation/stage-2-ledger.md) |
| Production MCP, Stages 1–6 | Locally accepted, 2026-09-25 | [program plan](docs/plans/2026-09-24-production-mcp-program.md), [Stage 6 acceptance](docs/validation/mcp-stage-6-acceptance.md) |
| Map-first chat UI and visualization | In `main` | [ADR 0004](docs/decisions/0004-map-first-chat-scene.md), [chat UI validation](docs/validation/2026-09-26-chat-ui.md) |
| Agent chat, guardrails, evals, request lookups | In `main` and on staging | [ADR 0005](docs/decisions/0005-mcp-agent-chat.md), [agent README](docs/agent/README.md) |
| Availability catalog | Open-data 2026.10.27; staging pinned to it on 2026-10-30 | [ADR 0003](docs/decisions/0003-mcp-availability-and-batches.md), the records below |
| Hosted deployment | Render staging from `deploy/staging`; production not promoted | [Render guide](docs/deploy/render.md) |
| Outstanding work | Phase 1 done 2026-10-30; phases 2–7 not started | [outstanding work plan](docs/superpowers/plans/2026-10-30-outstanding-work.md) |

## v0.1 implementation — complete

Stage 1 (provider and API probes, licence review, architecture, plan) was completed. The owner
approved Stage 2 on 2026-09-20.

- [x] Typed package contracts, configuration, EPW/QC and packaging.
- [x] Historical and native-product retrieval with manifests and raw checksums.
- [x] Six provider adapters, with source-dependent limits and live evidence.
- [x] Spatial batches, verified-source reuse and explicit hybrids.
- [x] Durable local jobs, cancellation, REST and artifact storage.
- [x] CMIP6 morphing and distinct hourly WRF profiles; typical/extreme/ensemble.
- [x] MCP, CLI and examples over the canonical service.
- [x] Final acceptance record, documentation and regression checks.

## Production MCP, Stages 1–6 — locally accepted

Stage numbers here are separate from v0.1. The [program plan](docs/plans/2026-09-24-production-mcp-program.md)
allocates the work; the [staged design](docs/superpowers/specs/2026-09-23-mcp-stages.md) and the
[remaining-stage plan](docs/superpowers/plans/2026-09-25-mcp-remaining-stages.md) record it. The owner
approved Stage 2 on 2026-09-24 and autonomous Stages 3a–6 on 2026-09-25.

| Stage | Content | Record |
| --- | --- | --- |
| 1 | Research baseline: footprints, inventories, temporal ranges, future scenarios; 41 metadata requests and three probes | [findings](docs/validation/mcp-stage-1/README.md), [handoff](docs/handoffs/2026-09-24-mcp-stage-2.md) |
| 2 | Shared catalog, eligibility and recommendations | [acceptance](docs/validation/mcp-stage-2-acceptance.md), [ADR 0003](docs/decisions/0003-mcp-availability-and-batches.md) |
| 3a | Weather planning, durable batch jobs, QC mapping, compact export | [acceptance](docs/validation/mcp-stage-3a-acceptance.md) |
| 3b | Registered baselines, two distinct future methods, member-level jobs | [acceptance](docs/validation/mcp-stage-3b-acceptance.md) |
| 4 | Local MCP tools, resource reads, real stdio SDK sessions | [acceptance](docs/validation/mcp-stage-4-acceptance.md) |
| 5 | Optional reference harness, bounded model runs | [acceptance](docs/validation/mcp-stage-5-acceptance.md) |
| 6 | Local pilot: real SDK stdio journeys, provider and model runs, defects fixed | [acceptance](docs/validation/mcp-stage-6-acceptance.md) |

Follow-ups within this line:
- **NOAA and OneBuilding:** an owner-authorized NOAA inventory and OneBuilding coordinate matching
  cut unknown products from 1,799 to 61, all in the U.S.
- **Owner review:** 56 Hawaiian correspondences, three approximate localities and two unresolved
  conflicts, kept as metadata-only annotations.
- **NSRDB, PVGIS and CMIP6 map evidence:**
  [NSRDB](docs/validation/mcp-stage-2/nsrdb-footprint-acceptance.md),
  [PVGIS](docs/validation/mcp-stage-2/pvgis-map-evidence.md),
  [CMIP6 licences](docs/validation/mcp-stage-1/cmip6-license-scope.md).

Weather equivalence between sources is not verified.

## Chat and agent

- **Map-first chat UI** (2026-09-26): guided chat over the shared service, map scene and
  visualization views. See the [plan](docs/plans/2026-09-26-guided-weather-chat-ui.md),
  [ADR 0004](docs/decisions/0004-map-first-chat-scene.md),
  [visualization plan](docs/plans/2026-09-26-visualization-initial.md) and
  [place lists](docs/plans/2026-09-27-place-list-inputs.md).
- **One MCP agent core for web and CLI chat** (merged 2026-10-12): guided and agent modes, model
  port and guardrails. See [ADR 0005](docs/decisions/0005-mcp-agent-chat.md) and the
  [guardrails plan](docs/superpowers/plans/2026-10-09-agent-guardrails.md).
- **Agent evals E1, E2 and E4** (merged 2026-10-12). See the
  [evals plan](docs/superpowers/plans/2026-10-10-agent-evals.md). E3, E5 and grading real sessions
  are phase 2.
- **Request lookups, slots phase (a)** (merged 2026-10-30): the agent answers availability
  questions with a host lookup. See the [lookups plan](docs/superpowers/plans/2026-10-13-agent-request-lookups.md).
  Slots phases (b)–(d) are phases 3 and 4.
- **Still planned:** downloading artifacts to the person's disk and richer analytical follow-ups
  ([post-retrieval plan](docs/plans/2026-09-26-post-download-conversations.md)). These are phase 5.

## Availability catalog

The catalog is published as a data package in
[Energy-Atlas/open-data](https://github.com/Energy-Atlas/open-data); deployments pin a commit and
SHA-256 ([Render guide](docs/deploy/render.md), section 1).

| Version | Content | Record |
| --- | --- | --- |
| 2026.10.13 | All OneBuilding TMYx regions; NSRDB satellite masks; ERA5 masks; catalog auto-upgrade | [coverage plan](docs/superpowers/plans/2026-10-13-availability-coverage.md), [record](docs/validation/availability-coverage-2026-10-13/README.md) |
| 2026.10.13.2 | PVGIS 5.3 domain mask; NSRDB years per mask; ERA5-Land points with values. Pushed, never pinned | [gaps plan](docs/superpowers/plans/2026-10-13-availability-gaps.md), [record](docs/validation/availability-gaps-2026-10-13/README.md) |
| 2026.10.27 | 17 OneBuilding national and special families; NSRDB Himawari-8 (re-binned); PVGIS coastal refinement; ERA5 poles. Pinned on staging 2026-10-30 | [record](docs/validation/availability-followups-2026-10-27/README.md) |

Serving memory work: [catalog memory record](docs/validation/2026-10-13-catalog-memory.md).
Remaining gaps are phase 6.

## Hosted deployment

- **Staging:** Render staging deploys every push to `deploy/staging` and runs `main` plus
  staging-only accounts (`feature/account-login`). Catalog pins are set by the owner in the Render
  dashboard.
- **Production** (`feature/render-deploy`): not promoted. The owner decides any promotion.

## Backlog beyond the phases

The v0.1 follow-ups are now phases 6 and 7:
- GHCNh, the successor to the frozen ISD inventory (6.5);
- Linux/macOS CI and an EnergyPlus smoke check (7.1);
- a job retention policy (7.2);
- more NSRDB products and CDS DNI/DHI derivation (7.3);
- reuse of previous verified runs (7.4);
- sampled future generators (7.5).

Not scheduled:
- **Generalized native OneBuilding geographic indexing:** only after its catalog and
  redistribution permissions are verified. Downloaded weather is never mirrored without
  permission.
- **Provider rate-limit scheduling:** only if pilot evidence shows a need.

## Standing constraints

- Publication, ownership changes and paid services are owner actions.
- Merging into `main` or `deploy/staging` and open-data pushes need the owner's go-ahead. Docs-only
  phase results may merge into `main` (owner, 2026-10-30).
- No force push or history rewrite.
- Live model and eval runs are opt-in, each within a cost cap the owner sets.
