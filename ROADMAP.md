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

## Production MCP — Stage 1 accepted; Stages 2–3a implemented; Stages 3b–6 approved

The current goal is a validated local MCP experience with an agent harnessing
layer. The staged roadmap ends at the local pilot; team deployment is outside
the current plan.
[The production MCP program plan](docs/plans/2026-09-24-production-mcp-program.md)
allocates features, work areas and deliverables across all six stages. Stage 2
implementation was explicitly approved by the owner on 2026-09-24.
[ADR 0003](docs/decisions/0003-mcp-availability-and-batches.md) records the accepted
availability-investigation scope and batch behavior. The
[staged design](docs/superpowers/specs/2026-09-23-mcp-stages.md) proposes subsequent
shared-service, local MCP, agent-harnessing and pilot stages; it is not an approved
implementation plan. Its stage numbers are separate from v0.1 above.

MCP Stage 1 uses authoritative footprints, station/site inventories, temporal ranges
and future scenario/windows, with strategic bounded probes instead of exhaustive
API queries. Previous successful runs and QC summaries are excluded from this stage.

The 2026-09-24 MCP Stage 1 research baseline was explicitly accepted by the
owner. The [handoff](docs/handoffs/2026-09-24-mcp-stage-2.md) and
[findings](docs/validation/mcp-stage-1/README.md) record 41 metadata requests,
three targeted probes, reproducible tooling and precise limitations.
The shared Stage 2 catalog, eligibility and recommendation services are implemented
with offline validation; see [acceptance](docs/validation/mcp-stage-2-acceptance.md).
The [Stage 2 design](docs/superpowers/specs/2026-09-24-mcp-stage-2-availability-design.md)
and [implementation plan](docs/superpowers/plans/2026-09-24-mcp-stage-2-availability.md)
record the approved work. The [coordinated remaining-stage plan](docs/superpowers/plans/2026-09-25-mcp-remaining-stages.md)
links detailed plans for Stages 3a, 3b, 4, 5 and 6. They incorporate the owner's
2026-09-25 clarification answers. The owner approved autonomous implementation
on 2026-09-25. Stage 3a weather planning, durable batch jobs, QC mapping and
compact export have [offline acceptance](docs/validation/mcp-stage-3a-acceptance.md).
An owner-authorized NOAA follow-up retrieved the larger station/month inventory
in one additional call; its normalized local index was imported for Stage 2.
The approved follow-up also resolved both OEDI scenario directories and matched
selected OneBuilding products through published coordinate spreadsheets or
corroborated NOAA station IDs. The additional coordinate follow-up reduced unknown
products from 1,799 to 61 (all U.S.), preserving station/elevation ambiguity.
Unmatched coordinates and index reuse terms remain
explicit; no production integration or weather-quality acceptance is implied.

The merged Stage 1 follow-up adds a local NSRDB map for the published
`tdy-2023` grid, an approximate PVGIS SARAH3 source-region layer, and pinned
CMIP6 model-license counts. The [NSRDB evidence](docs/validation/mcp-stage-2/nsrdb-footprint-acceptance.md)
generalizes occupied grid sites into 0.25° display cells; it does not establish
arbitrary-point API eligibility. Other NSRDB selectors retain unknown regional
extent outside exact probes. [PVGIS map evidence](docs/validation/mcp-stage-2/pvgis-map-evidence.md)
and the [CMIP6 license-scope addendum](docs/validation/mcp-stage-1/cmip6-license-scope.md)
have their own limits. The accepted Stage 1 snapshot remains the service baseline;
the new research artifacts have not been imported into its active catalog. Any
applicable follow-up enters as a reviewed new generation without recollection or
overwriting accepted annotations.

Current sequence after Stage 1: Stage 2 shared availability and recommendations;
Stage 3a weather-fetch planning, batches and artifacts; Stage 3b future weather
from uploaded or fetched-artifact-ID EPWs; Stage 4 local MCP contract with geography
interpretation; Stage 5 agent harness and evaluations; Stage 6 agent-and-real-client
local pilot and release acceptance. Human participant sessions are deferred. The
harness compares direct Python with LangChain/LangGraph; opt-in live model checks
use `gpt-6-luna`, with only local run records and no LangSmith calls. The existing
`.env` is read-only, and billable API smoke tests share a cumulative cap below US$10.

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
- More detailed job retention/cleanup policy and provider rate-limit scheduling
  if local pilot evidence shows a need.
- Sampled future generators only with defensible temporal/covariance validation.

Publication, ownership changes and paid services remain separate owner actions.
The current feature branch is preserved; no force push or history rewrite.

The subsequent accepted individual review is applied as research annotations:
56 Hawaiian metadata correspondences, three approximate mainland localities and
two unresolved name/code conflicts. Source-checksum changes invalidate acceptance;
accepted review annotations remain metadata-only; weather equivalence is unverified.
