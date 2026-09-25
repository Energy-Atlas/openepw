# NSRDB geospatial availability design

**Local-map display revision, 2026-09-24:** The owner chose a published-grid-only
NSRDB map. The aggregate actual-year option and two point markers are no longer
rendered or embedded in its payload. Their accepted Stage 1 records and the
point-to-grid source cross-check remain intact. The original proposed service
semantics below have not received Stage 2 implementation approval.

Status: proposed amendment to the [MCP Stage 2 availability design](2026-09-24-mcp-stage-2-availability-design.md). Owner review is required before implementation. This work uses the validated, ignored Stage 1 snapshots; it does not restart Stage 1 collection.

## Purpose and present evidence

The local availability map currently shows only the two Stage 1 NSRDB catalog probes, Ithaca and Phoenix. That is accurate for those probes but does not answer the user's geographic question for the selected NSRDB product and time choice. Stage 1's aggregate v4 point responses list actual years 1998–2025; its published v4 responses list TMY/TDY/TGY identifiers and 2022–2025 suffix variants. These are point observations, not a footprint. The saved `ledger.json`/`raw/` and accepted `analysis.json` remain the input of record.

The intended map should show the best *product-specific* spatial evidence for a chosen actual-year interval or a chosen published product identifier. It must distinguish a documented general GOES region, grid-site coverage derived from a version-matched NLR file, and catalog-confirmed points. It must never turn a two-point sample, a satellite field of view, or a release suffix such as `tdy-2023` into a claim of exact year-specific product availability.

## Evidence ladder and acquisition rule

| Level | Permitted map claim | Minimum evidence |
| --- | --- | --- |
| Exact point catalog | The exact product and selected actual year or published identifier was returned for this queried coordinate | Saved NLR `nsrdb_data_query` response with request point, product name, options, retrieval time and checksum |
| Version-matched grid membership | The corresponding NLR published file has a grid site at this location for the selected product and year/version | Provider-controlled file identity and version, `meta` site coordinates, file provenance/checksum or immutable object version, and confirmed relationship to the API product; no weather arrays required |
| Documented broad region | NLR describes a general GOES coverage area for the product family | Cited NLR documentation, displayed as an approximate geographic context only; no definitive inside/outside eligibility |
| Unknown | No matching footprint or point evidence | No shaded coverage; explicit unknown state |

NLR's [download index](https://developer.nlr.gov/docs/solar/nsrdb/) describes aggregate v4 as GOES east/west coverage from 1998 onward and the published v4 TMY family as derived from GOES time series. Its [location query](https://developer.nlr.gov/docs/solar/nsrdb/nsrdb_data_query/) is location specific. The [TMY API](https://developer.nlr.gov/docs/solar/nsrdb/nsrdb-GOES-tmy-v4-0-0-download/) treats `tmy-YYYY`, `tdy-YYYY` and `tgy-YYYY` as `names` options. [OEDI's NSRDB file guide](https://github.com/openEDI/documentation/blob/main/NSRDB.md) documents HDF5 `meta` site coordinates, but its examples describe v3 files; that guide alone does **not** match any v4 API product or published version. The [public NSRDB bucket registry](https://registry.opendata.aws/nrel-pds-nsrdb/) lists distinct CONUS and full-disc collections; their footprints cannot stand in for aggregate or TMY v4.

Stage 2 first inspects provider-controlled catalog/listing metadata for a sidecar extent or coordinate table and an explicit API-product-to-file mapping. If a matching file is available, acquire only bounded spatial metadata, with request count and byte caps recorded in the local evidence ledger. Do not fetch weather arrays or enumerate a dense grid through point API calls. If product/version matching fails, keep the documented context and two point confirmations; report precise region coverage as unresolved. Do not trace an outline from GOES satellite geometry or a convex hull of sampled points.

## Spatial and temporal semantics

- Represent coverage as separate records keyed by API product ID, API/native version, selector kind and selector value. Selectors are `actual_year` (e.g. 2023) or `published_name` (e.g. `tdy-2023`). Keep retrieval date, source modification date, checksum and evidence basis separately.
- For an actual interval spanning years, show **all-years intersection** as the strongest availability view and **some-years union minus intersection** with a distinct pattern. Missing year metadata is `unknown`, not absent. The query retains exact requested start/end dates and the map labels its year-level evidence resolution.
- For `tmy`, `tdy` or `tgy` without a suffix, resolve the concrete current name from a fresh point catalog before mapping; do not pin an alias to the newest Stage 1 suffix forever. `tdy-2023` means the named published product, not actual 2023 weather or a known reference period.
- A grid `meta` table can justify mapped site membership, but it does not prove complete weather, every variable, API download eligibility, or a cell's exact polygon. Render a generalized coverage mask or occupied cells at stated display resolution, preserve holes and disconnected regions, and label it as a spatial summary of source grid sites. Keep the source coordinate reference system and any longitude conversion recorded.
- At a clicked or requested coordinate, the shared service still uses an exact product/location/year catalog check when eligibility depends on it. A generalized mask is not a positive eligibility decision. Outside a *proven exhaustive* grid is excluded only when that grid's exact product/year/version and spatial interpretation are established; otherwise it is unknown.
- Access (key/email), service health/rate limits, weather quality, and display coverage are independent fields. An old or invalidated footprint stays visible only as stale context with an explicit timestamp, not as fresh positive evidence.

## Local artifact and service boundary

The accepted Stage 1 files stay ignored under `.local/mcp-availability/` and retain their checksums. A bounded Stage 2 metadata acquisition, if approved, writes a new local NSRDB footprint manifest and raw source evidence beside them, without altering the accepted ledger or annotations. Only source citations, importer code, small synthetic fixtures and validation summaries enter Git. Generated map data/HTML stay in an ignored local output directory; a reproducible generator lives in the repository. No browser or server/MCP dependency enters the scientific/data core.

The Stage 2 catalog adds a per-product, per-selector spatial evidence record rather than a single provider-wide polygon. The map consumes that record and its evidence basis; Python/REST/MCP availability assessments consume the same semantics. The map may present a broader documented region as context, but the service cannot promote it to `supported` for a selected product and period.

## Acceptance

1. From the copied Stage 1 snapshots, the existing map's Ithaca/Phoenix markers and exact aggregate/published option lists remain unchanged; no selected-year suffix is interpreted as actual-year coverage.
2. A version-matched NLR spatial metadata source, if found within the bounded acquisition, yields a reproducible map layer keyed to exact product/selector. Metadata/file mismatch, missing year, stale file and incomplete transfer downgrade to unknown without retaining a false shaded layer.
3. Synthetic map and service tests cover multi-year intersection/partial union, holes/disconnected regions, dateline/longitude handling, points on display-mask boundaries, alias changes and two probed points outside a mismatched product mask.
4. The local output names every layer's evidence basis, source/date/version and display resolution. It distinguishes `catalog point confirmed`, `source grid site present`, `documented broad region`, and `unknown` in legend, hover and exported summary.
5. No full weather files, source coordinate inventories, credentials or signed URLs are committed or embedded in shared docs. The provider's attribution and applicable reuse terms accompany the local artifact.

## Open scientific/source decision

The precise v4 API-product-to-bulk-file mapping has not yet been verified. Its verification is the first implementation task and a gate for *exact* grid coverage claims. If NLR does not publish or confirm such a mapping, the honest deliverable is an improved map of documented scope plus the two verified points, with an explicit unresolved exact-footprint note. The user's requested exact per-version region would then require provider clarification or another authoritative source.
