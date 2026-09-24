# Roadmap

## Stage 1 — complete

Provider/API probes, license/reuse review, architecture and the implementation
plan were completed. Owner approved Stage 2 on 2026-09-20.

## Stage 2 — v0.1 implementation

- [x] Typed package contracts, configuration, EPW/QC and packaging.
- [x] Historical and native-product retrieval with manifests and raw checksums.
- [x] Six provider adapters, with source-dependent limits and live evidence.
- [x] Spatial batches, verified-source reuse and explicit hybrids.
- [x] Durable local jobs, cancellation, REST and artifact storage.
- [x] CMIP6 morphing and distinct hourly WRF profiles; typical/extreme/ensemble.
- [x] MCP, CLI and examples over the canonical service.
- [x] Final acceptance record, documentation and regression checks.

## Production MCP — Stage 1 accepted; Stage 2 planning next

Local use will roll out and be tested before self-hosted team deployment.
[ADR 0003](docs/decisions/0003-mcp-availability-and-batches.md) records the accepted
availability-investigation scope and batch behavior. The
[staged design](docs/superpowers/specs/2026-09-23-mcp-stages.md) proposes subsequent
shared-service, local MCP, pilot and team-deployment stages; it is not an approved
implementation plan. Its stage numbers are separate from v0.1 above.

MCP Stage 1 uses authoritative footprints, station/site inventories, temporal ranges
and future scenario/windows, with strategic bounded probes instead of exhaustive
API queries. Previous successful runs and QC summaries are excluded from this stage.

MCP Stage 1 research and follow-ups completed on 2026-09-24 and were explicitly
accepted by the owner. The owner agreed to advance to Stage 2; its next deliverable
is a detailed design and implementation plan. Read the
[agent handoff](docs/handoffs/2026-09-24-mcp-stage-2.md). The
[findings and evidence](docs/validation/mcp-stage-1/README.md) record 41 metadata
requests and three targeted probes, reproducible tooling, and precise limitations.
Stage 2 planning is authorized; production catalog integration is not yet
implemented. The [proposed Stage 2 design](docs/superpowers/specs/2026-09-24-mcp-stage-2-availability-design.md)
and [implementation plan](docs/superpowers/plans/2026-09-24-mcp-stage-2-availability.md)
are ready for owner review; neither is implementation approval.
An owner-authorized NOAA follow-up retrieved the larger station/month inventory
in one additional call; its normalized local index is ready for Stage 2 integration.
The approved follow-up also resolved both OEDI scenario directories and matched
selected OneBuilding products through published coordinate spreadsheets or
corroborated NOAA station IDs. The additional coordinate follow-up reduced unknown
products from 1,799 to 61 (all U.S.), preserving station/elevation ambiguity.
Unmatched coordinates and index reuse terms remain
explicit; no production integration or weather-quality acceptance is implied.

Future advanced feature: index previous verified runs/artifacts and QC summaries
to accelerate subsequent matching requests. Existing raw caching and job recovery
remain supported; this additional feature is deferred beyond initial local delivery.

## Follow-ups after v0.1

- Run configured Linux/macOS CI and an EnergyPlus consumption smoke check.
- GHCNh successor adapter; ISD's current-year service is being retired by NOAA.
- Generalize native OneBuilding geographic indexing, after verifying catalog and
  redistribution permissions. Do not mirror downloaded weather without permission.
- Additional NSRDB products/intervals, CDS DNI/DHI derivation, more climate models
  and datasets with small point-access chunks.
- Authenticated remote Streamable MCP, more detailed job retention/cleanup policy,
  and provider rate-limit scheduling for large deployments.
- Sampled future generators only with defensible temporal/covariance validation.

Publication, ownership changes and paid services remain separate owner actions.
The current feature branch is preserved; no force push or history rewrite.

The subsequent accepted individual review is applied as research annotations:
56 Hawaiian metadata correspondences, three approximate mainland localities and
two unresolved name/code conflicts. Source-checksum changes invalidate acceptance;
production discovery and weather-equivalence behavior remain unchanged.
