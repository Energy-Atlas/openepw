# ADR 0003 — MCP availability discovery and batch semantics

Date: 2026-09-23. Status: owner-approved direction and MCP Stage 1 scope;
On 2026-09-24 the owner explicitly accepted Stage 1 completion and agreed to
advance to Stage 2 design/planning. The owner subsequently approved autonomous
Stage 2 implementation on 2026-09-24; its catalog and recommendation service are
implemented with [acceptance evidence](../validation/mcp-stage-2-acceptance.md).
Stage 1 research is complete with explicit limitations in the
[findings](../validation/mcp-stage-1/README.md). The transition is documented in the [agent handoff](../handoffs/2026-09-24-mcp-stage-2.md).
The owner approved autonomous Stages 3a–6 implementation on 2026-09-25 after
reviewing the [coordinated plan](../superpowers/plans/2026-09-25-mcp-remaining-stages.md).
Stage 3a has [offline acceptance](../validation/mcp-stage-3a-acceptance.md). The
Stage 1 follow-up branch was reviewed and merged without importing its research
maps into the active service catalog. The current roadmap adds agent harnessing
before the local pilot and omits team deployment.

These MCP stage numbers are separate from the completed v0.1 Stage 1/Stage 2.

## Product direction

- Develop on `feature/mcp` in the repository checkout. Local MCP, an agent
  harness, and a local pilot are the current rollout path. No team-deployment stage
  is selected now; public multi-tenant hosting is also outside this roadmap.
- First-class workflows: dataset guidance/discovery, EPW retrieval, future-weather
  generation, and reliable batches. Standalone EPW inspection is not a priority
  user story, but workflow QC/provenance remains required.
- Future generation supports both a user-supplied local EPW and discovery/retrieval
  of a suitable baseline through OpenEPW.
- Recommendations account for study purpose, geographical and temporal availability,
  required variables, scientific meaning and access requirements. Recommend and
  proceed when intent is clear; clarify consequential ambiguities. Retain alternatives
  and do not silently switch sources after failure.
- Default to proceeding with supported locations and explicitly report unsupported
  locations. This does not authorize silently shortening requested periods or
  producing incomplete annual weather as complete.

## MCP Stage 1 — availability evidence and catalog design

Map availability from authoritative documentation and inventories before relying
on per-location weather API requests. Include:

1. Dataset footprints, geographical restrictions, native resolution, supported
   products and variables.
2. Station/site coordinates and stable source identifiers.
3. Station operating periods, available years and published-product reference periods.
4. Future scenarios, models/members and supported climate windows.

Use strategic locations and years to resolve specific uncertainties. API calls
must not be exhaustive: no grid sweeps, all-station queries, year-by-year enumeration
of downloads, or large batch probes. Prefer a published inventory downloaded once
and examined locally. Before a probe, state the uncertainty, representative input,
request/response-size limits and stopping condition. Reuse an answer across the
investigation; stop when the uncertainty is resolved. Respect rate limits and avoid
repeated attempts during provider backoff. Full-year downloads are not the default
for catalog investigation; use them only if essential to the precise question.

The evidence record distinguishes documented coverage, catalog-listed availability,
unknown availability and exclusions. Preserve provenance, checked dates and catalog
versions/checksums. A station operating range does not prove hourly completeness.
No fabricated footprint, year range, station identity or scenario equivalence.

Deliver a provider/product availability matrix, inventory-source register, bounded
probe log, unresolved limitations and proposed local catalog/refresh contract.
Metadata caching is in scope; advanced reuse of previous weather runs is not.

On 2026-09-23 the owner authorized further investigation of the larger NOAA
station/year inventory. The follow-up permits a 20 MB response only for the exact
published ISD inventory endpoint, retaining the 200 MB investigation ceiling and
all previous charges. One revised download resolved this inventory; monthly
report counts remain distinct from hourly or variable completeness. See the
[execution record](../superpowers/plans/2026-09-23-mcp-stage-1.md).

## Explicitly deferred — previous-run reuse

Previous successful retrievals and QC summaries are NOT inputs to Stage 1's
availability mapping. An advanced future feature may index prior runs and verified
artifacts to accelerate matching requests, with scientific identity, checksums and
freshness checks. Do not claim this feature exists or incorporate it into Stage 1.
Preserve the existing raw-response cache and job recovery/retry behavior; this
deferral does not remove existing caching or within-batch retrieval deduplication.

## Accepted batch behavior

- Keep requested-location identities, unique source requests and output artifacts
  separate. Report all three counts; multiple datasets/years/members can increase
  outputs beyond the number of input locations.
- Resolve each location against geographical and temporal eligibility. Use source
  distance and relevant elevation differences where known; do not choose an
  unsuitable station merely because it is nearest.
- Retrieve equivalent source requests once. Equivalence includes verified source
  identity, dataset/product, period, variables and applicable adjustments/options.
  Nominal grid spacing or rounded coordinates alone does not prove equivalence.
- Preserve every input occurrence and its source/output mapping, including
  unsupported and failed entries. Distinguish shared weather from missing results.
- Preserve station/source coordinates in weather artifacts. Do not imply that
  assigning a station file to a building relocates or downscales its weather.
- Keep the existing default of distinct per-location output identities/files.
  Add an explicit compact export option with unique equivalent weather files and
  a complete mapping table. Different transforms or output semantics must not be
  collapsed simply because they share a retrieval.

This extends the approved
[output identity design](../superpowers/specs/2026-09-23-core-integration-design.md)
without silently changing its default or invalidating existing plans/artifacts.

## Owner decisions 2026-10-12 (availability in the product choice)

Recorded after a staging failure where NSRDB GOES was offered at Singapore. See the
[findings and proposal](../superpowers/specs/2026-10-12-availability-and-time-zones-design.md).

- **Aged evidence keeps durable facts.** Past its check cadence, evidence still supports
  site positions, published-file lists and closed dated years (reason `SOURCE_CHECK_DUE`);
  it does not support the newest listed year, an open-ended period's last two years, CDS
  or future windows (`STALE_SOURCE_EVIDENCE`, unknown). Aged evidence still cannot exclude.
- **The NSRDB coverage map gates NSRDB GOES products.** This replaces, for eligibility,
  the rule of the [NSRDB geospatial design](../superpowers/specs/2026-09-24-nsrdb-geospatial-availability-design.md)
  that a generalized mask is never a positive decision: outside the reviewed mask
  (`OUTSIDE_SOURCE_COVERAGE`) is excluded, inside it (`INSIDE_SOURCE_COVERAGE`) the
  probed year and file lists apply, and next to it stays unknown. The `tdy-2023` mask is
  used for the GOES aggregated and TMY products alike.
- **Published station files reach 100 km**, as NOAA ISD does.
- **No live point checks while building the product list**; planning still checks.

## Owner decisions 2026-10-13 (coverage of the catalog)

See the [plan](../superpowers/plans/2026-10-13-availability-coverage.md) and its
[validation record](../validation/availability-coverage-2026-10-13/README.md).

- **OneBuilding:** every TMYx file the regional workbooks list is a product, with the workbook
  row as its published evidence. The 2026-09-28 publication override extends to all regions.
- **NSRDB beyond GOES:** the catalog, a coverage mask per satellite family, and adapter support.
  - Himawari-7, Meteosat and Meteosat IODC, and their typical years, are downloaded.
  - Himawari-8 is not, because its hourly labels at :00 do not form hour-ending intervals.
  - The masks come from each family's published grid table, under owner-raised caps after an
    overrun on the Himawari table. Himawari TMY shares the Himawari-7 grid.
- **ERA5:** Copernicus's catalogue period is documented coverage.
- **ERA5-Land:** gated by ECMWF's land–sea mask (land fraction ≥ 0.5).
- **Masks:** each mask gates only the products its manifest names (`gates`).
- **Rollout:** a hosted instance upgrades its catalog when the pinned package changes, and keeps
  the previous one if the upgrade fails.

## Owner decisions 2026-10-13 (PVGIS coverage, availability-gaps plan)

See the [plan](../superpowers/plans/2026-10-13-availability-gaps.md) and its
[validation record](../validation/availability-gaps-2026-10-13/README.md).

- **PVGIS TMY 5.3 is one product with a per-location radiation source:**
  - SARAH3 where it is JRC's default, ERA5 elsewhere;
  - the run records PVGIS's reported `radiation_db`.
- **A domain mask gates it.** It is built from the ERA5-Land land–sea mask, with an explicit
  unknown band (`edge_runs`):
  - inside: land between 60° S and 75° N;
  - outside: ocean-connected water more than 50 km from any land or published station, and
    beyond those latitudes;
  - unknown: coasts, lakes and small islands.
- **Inside the mask, a documented 2005–2023 entry applies.** A probe's selected month-years
  stay at its own point.
- **Six PVGIS TMY requests under an owner-approved exception** used Stage 1's last probes.

## Architecture boundary

Availability, recommendation evidence and batch resolution belong in the canonical
Python service/domain layer. MCP exposes them through a compact, typed interface;
REST and CLI can consume the same behavior. Server/MCP dependencies remain outside
the scientific core. Research and implementation must record limitations honestly.
