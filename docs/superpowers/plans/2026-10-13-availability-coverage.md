# Availability coverage: OneBuilding regions, NSRDB beyond GOES, ERA5 and rollout

Status: approved by the owner 2026-10-13 (the answers below). Branch `feature/availability-coverage`.
Follows the Stage 1 method ([plan](2026-09-23-mcp-stage-1.md), ADR 0003), the NSRDB coverage method
([source review](../../validation/mcp-stage-2/nsrdb-footprint-source-review.md)) and the
[2026-10-12 findings](../specs/2026-10-12-availability-and-time-zones-design.md) (A4, A5, F5).

## Owner decisions (2026-10-13)

1. **OneBuilding: all TMYx regions.**
   - Import every row of the Europe and Southwest Pacific workbooks already held. Until now,
     only the UK and Australian files were imported.
   - Add the seven other TMYx regional workbooks linked from the saved sources page.
   - The 2026-09-28 publication override for OneBuilding extends to them.
   - Rows that cannot be matched go to owner review, as the 61 before did.
2. **NSRDB beyond GOES: catalog, masks and adapter.**
   - Point probes, a coverage mask per satellite product from its published file's grid
     table, one test download per dataset, and adapter support.
   - Each product is gated by its own mask.
3. **ERA5 and ERA5-Land.**
   - Copernicus's catalogue period counts as documented global coverage for ERA5; only the
     newest months become unknown when old.
   - ERA5-Land, from both CDS and Open-Meteo, is gated by ECMWF's published ERA5-Land
     land–sea mask, which is published in the package as a 0.1° mask.
4. **Rollout: auto-upgrade on start.**
   - When the pinned package SHA-256 differs from the installed one, install the package as a
     new catalog generation and replace the footprints.
   - On failure, keep serving the previous catalog and log why.

## Request budget (owner-approved exceptions)

Collection continues in the existing ignored snapshot `.local/mcp-availability/`, through the
collector, which records everything in the ledger. Stage 1's ceilings stay in force, and each
exception below names its exact requests. Remaining before this plan: 19 metadata requests,
9 probes (1 for NSRDB), 59.9 MB. No credentials ever enter a manifest or ledger.

| ID | Requests | Cap | Purpose and stopping condition |
|---|---|---|---|
| E1 OneBuilding regional workbooks | 7 (OneBuilding attempts 16–22), exact URLs below | 5 MB each, 35 MB total | Product URLs and coordinates for the TMYx files in regions 1, 2, 2/6 Russia, 3, 4 Canada, 4 Central America/Caribbean, 7. Stop when the seven are saved, or a URL fails once (one justified revision allowed). |
| E2 NSRDB point probes | 3 data-query requests with `DEMO_KEY` (NSRDB probe cap 3 → 6) | 1 MB each | Which NSRDB datasets cover Singapore (1.2897, 103.8501), Nairobi (−1.286, 36.817) and London (51.507, −0.128). Stop after the three. |
| E3 NSRDB bucket listing and grid tables | ≤ 6 anonymous S3 listing requests, plus per selected product ≤ 12 range requests and ≤ 300 MB | 300 MB per product | Choose one published file per new product, then read only its HDF5 `meta` table, as for GOES `tdy-2023`. Cross-check each grid against the E2 points (≤ 8 km). Stop when each product's mask is accepted or rejected. |
| E4 ERA5-Land land–sea mask | 1 documentation read + 1 download | 50 MB | ECMWF's published ERA5-Land land–sea mask file. Stop when saved. |
| E5 NSRDB adapter acceptance | 1 small download per new dataset, configured key | live, opt-in | Live acceptance of the adapter, tagged `live`; never in ordinary tests. |

E1 URLs (all under `https://climate.onebuilding.org/sources/`):
- `Region1_Africa_TMYx_EPW_Processing_locations.xlsx`
- `Region2_Asia_TMYx_EPW_Processing_locations.xlsx`
- `Region2_Region6_Russia_TMYx_EPW_Processing_locations.xlsx`
- `Region3_South_America_TMYx_EPW_Processing_locations.xlsx`
- `Region4_Canada_TMYx_EPW_Processing_locations.xlsx`
- `Region4_NA_CA_Caribbean_TMYx_EPW_Processing_locations.xlsx`
- `Region7_Antarctica_TMYx_EPW_Processing_locations.xlsx`

## Steps

1. **Rollout.** `openepw.deploy` installs a package whose descriptor SHA-256 differs from the
   one recorded at the last install:
   - it stages a new generation, activates it, and replaces `footprints/` atomically;
   - a failure keeps the active catalog and the old footprints, and the server still starts;
   - offline tests cover this.
2. **Per-product masks.**
   - Footprint manifests name the catalog product they gate.
   - `coverage.py` loads one mask per product, so GOES, Himawari, MSG and ERA5-Land are each
     gated by their own mask.
   - A product without a mask keeps today's behaviour.
3. **ERA5.** CDS catalogue periods count as documented coverage. Aged CDS evidence makes only
   years at or after the catalogue's end unknown. This replaces the 2026-10-12 rule that CDS
   is always time-sensitive.
4. **ERA5-Land.** E4, then a 0.1° mask (land where the published mask says land) in the
   footprint format. The coast stays unknown through the edge rule.
5. **OneBuilding.**
   - E1, then `analyze` offline.
   - Products come from every row of the TMYx regional workbooks, not only from country
     index pages. Coordinates come from those rows, with the same NOAA cross-check.
   - Unmatched or conflicting rows go to a review list for the owner. They are imported
     without coordinates until reviewed.
6. **NSRDB.** E2, E3, the adapter (download endpoints, variables, interval and years per
   dataset, from NLR's documentation), then E5.
7. **Publish.**
   - Re-import the catalog and export package version `2026.10.x` into
     `open-data/datasets/weather-availability-catalog`.
   - Update its data card: sources and terms checked, method, counts, known limits, version
     row.
   - Verify a lossless round trip.
   - The owner confirms before the push to the public repository.
   - Then pin `OPENEPW_CATALOG_URL` and `OPENEPW_CATALOG_SHA256` for staging.
8. **Records.**
   - ADR 0003 amendment, limitations, the validation record with a probe log in the Stage 1
     format, `requests.json`, and the research README's exception note.

## Out of scope

- National typical-year families (CWEC, ISHRAE, IMGW and others).
- NSRDB products other than those the E2 probes list.
- Polar CDS footprint conflicts.
- Production deployment.
