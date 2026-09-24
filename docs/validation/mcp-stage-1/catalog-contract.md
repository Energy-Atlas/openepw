# Stage 2 handoff — proposed availability catalog contract

Status: research recommendation, not an implemented or approved public API.
Evidence: [Stage 1 findings](README.md), [sanitized ledger](evidence.json).

## Records and decision boundaries

Keep catalog logic in the canonical Python service, independent of MCP/FastAPI.
Use these related records, rather than a provider-level available/unavailable flag:

- **Dataset/product:** provider and underlying dataset identity, version/access
  route, spatial kind, documented footprint or unknown, variables and derivations,
  native/delivery resolution, temporal meaning, access requirements and citations.
- **Site:** stable source ID, native coordinates, optional elevation and station
  operating intervals. Unknown coordinates/elevation remain unknown.
- **Availability entry:** product/site or model/member/grid/scenario, applicable
  interval/reference period/window, variable set, documented exclusions and
  uncertainty. Preserve actual-year, TMY-reference and future-window semantics.
- **Evidence:** source record ID/URL, retrieval time, Last-Modified/ETag if supplied,
  checksum, evidence basis, provenance/terms and conflicts. Retrieval time is not
  the publication date and cannot make an old inventory current.

Return eligibility (`supported`, `excluded`, `unknown`) for an explicit requested
location/period/product/variable combination, separately from evidence basis
(`documentation`, `inventory`, `targeted probe`). Include reasons and unknowns.
"Supported" at this stage means an eligible candidate, not complete weather.
Missing credentials and provider outages are separate access/health observations.

Use SQLite plus local metadata files within the project's existing lightweight
architecture. Version importers and snapshot schemas; atomically publish a new
validated snapshot only after successful parsing. Retain the last usable snapshot
on refresh failure and label it stale. No mandatory external database or GIS server.

## What can be decided without a weather call

| Local decision | Evidence needed | What remains a retrieval-time question |
| --- | --- | --- |
| Product/variable compatibility and obvious date exclusions | Dataset contract plus adapter capability intersection | Actual values, missing fields and complete intervals |
| Candidate station/site mapping | Coordinates, stable IDs, operating periods and listed station/year/month counts | Actual observations, distinct valid hours, variable availability and source-specific adjustments |
| Published TMY choices | Explicit catalog product links and reference-period labels | Native EPW coordinates, fields and quality |
| Future scenario/window compatibility | Method/source documentation plus model/site catalog | Complete model time coverage, valid signals or full trajectory content |
| Shared source request grouping | Verified native identity and identical scientific options | Unknown cells/elevation-adjusted responses must not be collapsed prematurely |

Do not silently rewrite the CDS bbox to match its global description. Normalize
longitude representation explicitly while retaining the original. Treat disputed
polar boundaries and missing land masks as uncertainty until evidence resolves
them. Likewise, two NSRDB point catalogs do not define a coverage polygon.

## Proposed refresh policy

These are implementation defaults to evaluate in Stage 2, not upstream service
guarantees. Use conditional requests where supported and refresh a shared source
once per batch, never once per requested point.

| Metadata | Suggested policy | Basis / limitation |
| --- | --- | --- |
| Open-Meteo/CDS documented start dates and capabilities | Review on adapter release; monthly metadata check | Mostly stable contracts; new versions can change variable behavior |
| CDS moving end timestamp | Daily, or on-demand for a newer requested date | Catalog reports a dated moving endpoint; request-year enums alone are insufficient |
| NOAA ISD history and station/month counts | Weekly conditional check; no repeated refresh per point | Both files are dated 2025. Join stable alphanumeric IDs, retain unmatched identities and sparse years. Refreshing cannot manufacture a GHCNh connection or newer ISD coverage |
| OneBuilding selected country catalogs | Weekly conditional check; retain source periods verbatim | Published products are replaced/added independently; old products remain meaningful |
| NSRDB product/year metadata | Seven-day snapshot for resolved requests; on-demand for unknown locations/new years | Annual additions and product-specific coverage. Never extrapolate point results into an unverified spatial cache key |
| Pangeo catalog/WCRP license registry | Weekly conditional check and version pin | Current catalog response carries a 2022 Last-Modified date; polling it cannot guarantee comprehensive newer holdings |
| OEDI site tables and archive indexes | Pin by checksum/ETag; weekly conditional version check | Fixed published windows; a changed archive invalidates member offsets |

Expired or incomplete metadata yields uncertainty, not a definitive exclusion.
Use bounded on-demand refresh only when it can affect the requested decision.
Stage 1's existing ledger budgets are not reusable runtime quotas for production.

## Prioritized gaps for the next stage

1. Introduce shared metadata snapshots and typed evidence/eligibility records; stop
   per-point NOAA inventory retrieval. Keep complete requested-location mappings.
2. Separate source-wide capabilities, current adapter support and location-specific
   availability. Preserve unknowns and temporal meaning in ranking/explanations.
3. Establish a licensed, authoritative OneBuilding coordinate index before offering
   global nearest-site recommendations. Product-name matching alone is insufficient.
4. Resolve version-specific PVGIS footprint/source-period metadata and NSRDB product
   footprints without mass queries. Keep individual probes narrowly scoped meanwhile.
5. Validate CMIP6 windows across all required stores with bounded coordinate metadata
   access. Do not infer full intervals from array length/calendar units or four samples.
6. Complete OEDI archive-member indexing in a separately budgeted pass using the
   corrected 10 MB-per-archive reader. Preserve the 2,368 delivered-site inventory and
   distinguish membership from usable hourly data.
7. Import the now-acquired NOAA station/year/month index alongside history. A
   specifically owner-authorized 20 MB allowance retrieved its 14.97 MB snapshot
   in one revised call, within the unchanged overall budget. Preserve 1,034 IDs
   without history coordinates as unresolved and treat counts as period evidence,
   never hourly/variable completeness. No further bulk queries are needed to build
   this local index from the captured metadata.

## Batch and future-feature boundary

Keep input occurrences, equivalent source requests and output artifacts distinct.
Proceed with supported locations and report the rest with reasons. Preserve native
source coordinates; no synthetic increase in resolution. Existing per-location
output identities remain the default; compact export is an explicit later option.

**Deferred:** using previous successful weather runs or QC summaries to accelerate
matching requests. That feature needs scientific identity, checksum, freshness,
invalidation and user-visible reuse evidence. It is not part of this metadata
catalog investigation or a prerequisite for the initial local MCP release.
