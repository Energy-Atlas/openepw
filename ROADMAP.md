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

## Web UI — planning only

A same-repository frontend under `ui/` is the accepted direction. The
[draft design](docs/superpowers/specs/2026-09-20-webui-design.md) and
[implementation plan](docs/superpowers/plans/2026-09-20-webui.md) cover a compact
dockable UI, MapLibre/3D, real scripted workflows and API documentation.
Implementation is not yet approved. Local-first deployment is a proposed default.
No repository extraction or PyPI publication is part of this milestone.

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
