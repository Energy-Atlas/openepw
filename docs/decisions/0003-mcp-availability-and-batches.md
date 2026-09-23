# ADR 0003 — MCP availability discovery and batch semantics

Date: 2026-09-23. Status: owner-approved direction and MCP Stage 1 scope;
implementation has not started. Later stages remain proposals in the
[MCP staged design](../superpowers/specs/2026-09-23-mcp-stages.md).

These MCP stage numbers are separate from the completed v0.1 Stage 1/Stage 2.

## Product direction

- Develop on `feature/mcp`. Local use is the first rollout and testing prerequisite
  for a later self-hosted team release. Public multi-tenant hosting is not selected.
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

## Architecture boundary

Availability, recommendation evidence and batch resolution belong in the canonical
Python service/domain layer. MCP exposes them through a compact, typed interface;
REST and CLI can consume the same behavior. Server/MCP dependencies remain outside
the scientific core. Research and implementation must record limitations honestly.
