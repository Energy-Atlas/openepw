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

## Production MCP — design in progress

Local use will roll out and be tested before self-hosted team deployment.
[ADR 0003](docs/decisions/0003-mcp-availability-and-batches.md) records the accepted
availability-investigation scope and batch behavior. The
[staged design](docs/superpowers/specs/2026-09-23-mcp-stages.md) proposes subsequent
shared-service, local MCP, pilot and team-deployment stages; it is not an approved
implementation plan. Its stage numbers are separate from v0.1 above.

MCP Stage 1 uses authoritative footprints, station/site inventories, temporal ranges
and future scenario/windows, with strategic bounded probes instead of exhaustive
API queries. Previous successful runs and QC summaries are excluded from this stage.

MCP Stage 1 research completed on 2026-09-23. The
[findings and evidence](docs/validation/mcp-stage-1/README.md) record 31 metadata
requests and three targeted probes, reproducible tooling, and precise limitations.
Stage 2 production catalog integration remains proposed, not implemented.
An owner-authorized NOAA follow-up retrieved the larger station/month inventory
in one additional call; its normalized local index is ready for Stage 2 integration.

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
