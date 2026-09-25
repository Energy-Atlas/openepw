# NSRDB geospatial map acceptance — `tdy-2023`

Date: 2026-09-24. Branch: `feature/data-avail`. Scope: the local [multi-product availability map](../../superpowers/plans/2026-09-24-nsrdb-geospatial-availability.md), not the still-unapproved shared Stage 2 availability service. The map generator and tests are tracked; source-coordinate bytes and generated HTML remain ignored under this worktree's `.local/mcp-availability/`.

## Evidence acquired

The copied Stage 1 ledger still has 44 records and 38 saved raw bodies; all 38 body SHA-256 checks passed and `analysis.json` reports zero parse errors. Ithaca and Phoenix each list `nsrdb-GOES-tmy-v4-0-0` with the native `tdy-2023` name. Those accepted point records remain in the unchanged snapshots for the source cross-check; the map now uses only the published grid evidence. No Stage 1 collector was run.

The [source review](nsrdb-footprint-source-review.md) identified NLR's public `GOES/tmy/v4.0.0/nsrdb_tdy-2023.h5` as the matching bulk domain/name. A bounded anonymous S3 read acquired only its HDF5 `meta` table, not weather arrays. Its metadata contains **2,018,267** grid sites with geographic coordinates, occupying **53,723** distinct **0.25° display cells**. The approximate center-coordinate bounding box is latitude −20.99° to 59.97°, longitude −179.98° to −22.50°. The nearest source-grid centers to the saved probes are 1.112 km from Ithaca and 0.928 km from Phoenix, within the specified 8 km cross-check limit.

| Evidence item | Observed value |
| --- | --- |
| Public object size | 928,896,650,902 bytes; not downloaded whole |
| Object ETag | `"1fdb2bec54c98aa65406e35d53068ccf-6921"` (multipart identity, not SHA-256) |
| Source modified | 2024-09-16 20:14:37 UTC |
| Bulk path version / internal model attribute | `v4.0.0` / `4.0.1`; both are shown in the map evidence |
| `meta` transfer | 4 HTTP requests including HEAD; 264,471,862 bytes (252.22 MiB), below the 12-request/256-MiB cap |
| Local `meta` SHA-256 | `3028ad412525f1008cdd4b8674f73c0f3a4dbba0f46cdd2c4716459007e8c95c` |
| Local display-mask SHA-256 | `0410d124c6c9ea413471b4dad6b93266e216587bf73d0e9f9d34ca018d79c519` |

An immediate repeat used a conditional HEAD and reused the existing local snapshot without transferring `meta` again. Changed object ETags make a previous mask stale before replacement; incomplete, oversized, invalid-coordinate, duplicate-coordinate and mismatched-point inputs fail in offline tests.

## Map artifact and meaning

Run from the `feature/data-avail` worktree, using the owner-copied Stage 1 directory as `--snapshot-root`:

```powershell
python -m scripts.mcp_availability_map.acquire_nsrdb_meta nsrdb-GOES-tmy-v4-0-0 tdy-2023
python -m scripts.mcp_availability_map.build --snapshot-root C:\github\Energy-Atlas\openepw\.local\mcp-availability --topology .local\mcp-availability\world-topology.json
```

The build command writes `.local/mcp-availability/maps/availability-map.html` in this worktree. With the [approximate PVGIS SARAH3 polygon](pvgis-map-evidence.md) and the NSRDB grid-only view, the deterministic file is 723,514 bytes, SHA-256 `fa1c8fcb6db09e5e2ff570cb470dcf28e4c16cba747409735c516c5fef59ed73`. The local base map came from `world-atlas@2/countries-110m.json`, SHA-256 `8479d201eb95559d4c5da965f979b37b541cf402091969e89a12e65913e12098`, stored ignored beside the snapshots. The generated payload retains 15,476 mapped NOAA stations, 21,651 mapped OneBuilding products, 2,368 OEDI sites and the `tdy-2023` grid occupancy layer. It has schema `stage2-map-2` and carries no NSRDB point probes, API key, email, signed URL or source-coordinate inventory. Generation requires the local `meta.bin` and validates its SHA-256 alongside the mask. The acquisition command accepts only the reviewed `tdy-2023` product/object mapping until another selector receives its own source review.

The NSRDB layer means **NLR source grid sites in a generalized 0.25° display cell**. It does not assert every cell is filled, an exact pixel polygon, an API download for an arbitrary point, hourly completeness, variable completeness, or simulation readiness. `tdy-2023` is a named published product, not actual-year 2023 weather. The local map no longer offers the aggregate actual-year NSRDB view or displays the two point probes. Other published names remain selectable but explicitly show unknown extent until matching source-grid metadata is acquired. The documented GOES east/west description is context, not a shaded definitive polygon.

Confirmed cells use opaque blue `#3f6fd9`. The grid is drawn above the land and country-border geometry. The fill exceeds a 3:1 non-text contrast ratio against both black and white backgrounds. The active visualization copy is synchronized with the ignored worktree artifact.

NLR/NSRDB attribution and links to the [NLR product documentation](https://developer.nlr.gov/docs/solar/nsrdb/), [NLR resource-data format and API-domain guide](https://natlabrockies.github.io/rex/misc/examples.nlr_data.html) and [NLR-managed public collection and CC BY 3.0 US listing](https://registry.opendata.aws/nrel-pds-nsrdb/) appear in this record or the map. The source object remains public in place; no original third-party grid coordinates are committed.

## Verification and limits

- `python -m pytest tests/unit/test_nsrdb_coverage_map.py -q`: **18 passed** after the final map edit.
- `python -m pytest tests/unit -q`: **183 passed**, two existing dependency deprecation warnings, after the final map edit.
- `python -m ruff check scripts/mcp_availability_map tests/unit/test_nsrdb_coverage_map.py`: passed; `node --check` on the generated inline script: passed. The generated payload contains only the reviewed published-grid selector.
- Generated payload inspection: schema `stage2-map-2`, one `published:tdy-2023` mask with 53,723 cells and no NSRDB points or actual-year option; no replacement characters or `api_key=` text; HTML is under 1 MiB.
- Browser rendering was not visually verified: the app's browser security policy blocked the earlier local-file preview, and no alternate preview route was used. JavaScript syntax and generated-data checks are the available UI verification.

The internal `4.0.1` model attribute inside NLR's `v4.0.0` domain remains an explicit provenance discrepancy. The grid map is therefore labeled by both values and is not promoted to positive service eligibility. The shared-service Stage 2 plan remains subject to owner approval.
