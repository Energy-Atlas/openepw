# NSRDB v4 spatial metadata source review

Reviewed 2026-09-24 for the [focused map plan](../../superpowers/plans/2026-09-24-nsrdb-geospatial-availability.md). This is new, bounded Stage 2 metadata investigation. No Stage 1 collection was rerun and no weather array was read.

## Source identity

NLR's [resource-data guide](https://natlabrockies.github.io/rex/misc/examples.nlr_data.html) says each product/domain maps to one download API endpoint, gives the `GOES/conus/v4.0.0` example, and defines HDF5 `meta` as the location axis. NLR's [download index](https://developer.nlr.gov/docs/solar/nsrdb/) identifies separate GOES aggregated v4 and GOES TMY v4 API products. The public NLR-managed `nrel-pds-nsrdb` bucket exposes matching, separate domains:

| API product | Public object family | Selected file | Claim |
| --- | --- | --- | --- |
| `nsrdb-GOES-aggregated-v4-0-0` | `GOES/aggregated/v4.0.0/` | `nsrdb_2023.h5` | Actual 2023 candidate spatial source |
| `nsrdb-GOES-tmy-v4-0-0` | `GOES/tmy/v4.0.0/` | `nsrdb_tdy-2023.h5` | Published `tdy-2023` candidate spatial source |

Bucket listing was read with six anonymous S3 `ListObjectsV2` metadata requests across the root and these prefixes. The selected `tdy-2023` object is 928,896,650,902 bytes, ETag `"1fdb2bec54c98aa65406e35d53068ccf-6921"`, Last-Modified `2024-09-16T20:14:37Z`. The selected aggregate 2023 object is 1,599,024,543,966 bytes, ETag `"5df24a511610c2209dd5daccbbe9f404-5957"`, Last-Modified `2024-09-13T12:41:42Z`. Neither file may be downloaded whole under this plan.

The bulk path says `v4.0.0`, while the `tdy-2023` file's root `version` attribute is `4.0.1`. NLR's guide describes that attribute as the model version and suggests it should match the path. This observed difference is preserved rather than rewritten. The public HSDS endpoint returned HTTP 403 without an API key. Anonymous S3 byte ranges do work. The file's HDF5 `meta` dataset has 2,018,267 rows, 130 bytes per row, and a contiguous 262,374,710-byte storage region beginning at byte 172,584. It contains latitude and longitude fields. That region can be fetched as one bounded range, avoiding all weather arrays and a full 929 GB download.

The provider's [TMY API documentation](https://developer.nlr.gov/docs/solar/nsrdb/nsrdb-GOES-tmy-v4-0-0-download/) lists `tdy-2023` as a `names` choice, not an actual 2023 time interval. Stage 1's Ithaca and Phoenix point responses list both selected API products and `tdy-2023`. The exact bulk-site correspondence of those two points is pending the bounded coordinate-only read; until then, the HDF5 domain is a candidate, not an accepted exact footprint.

## Acquisition choice and guardrails

Use anonymous HTTP Range against the exact S3 object, guarded by a fresh HEAD ETag/size check and `If-Match`; stream only the contiguous `meta` region into ignored local storage. Record object ETag, size, internal model version, coordinate count, native coordinate fields, byte count, request count and SHA-256 of the extracted `meta` bytes. Reject changed identity, incomplete or oversized transfer. The object ETag is multipart and is **not** a SHA-256. Parse the fixed-width compound rows offline; cross-check the nearest published grid coordinates to Ithaca and Phoenix before classifying any region as source-grid evidence.

The reviewed `meta` payload is 250.22 MiB; the 256 MiB cap leaves little room for extra range reads. A 1 MiB root read and a 1 MiB metadata-header read succeeded. Acquisition must keep all transfers for the selected selector within 256 MiB and 12 requests. Source coordinates remain local; a coarsened, explicitly labeled display occupancy mask can be generated afterward. Full cells, hourly variables, download success and exact API eligibility are outside this evidence.

## Stage 1 preservation check

The copied local ledger has 44 records and 38 saved raw bodies; all 38 SHA-256 values match. `analysis.json` uses schema `mcp-research-1` and has zero errors. The local `evidence.json` matches the tracked sanitized evidence byte-for-byte. Snapshot SHA-256 values: `ledger.json` `d13eb5ffa1ba0384ecf53bea95965b31a382cad503ff7ff25880410ee7f3ce90`; `analysis.json` `6db46f795a4404d0e3faaae1e88e82c54ebb222af786e07972a1a3ffeacb2339`. The point bodies are `nsrdb-ithaca` `a1a84846b67c594429561933eeb9125a5b6d10d3cd8e6123e24ce3183f649a39` and `nsrdb-phoenix` `52259cc291690c5789bf5797a32f40d2db8e3a8df57e5551e9bf50793aef89ac`, recorded 2026-09-23. No accepted annotations were modified.

NLR attribution is required. The [public AWS registry](https://registry.opendata.aws/nrel-pds-nsrdb/) lists this NLR-managed collection under CC BY 3.0 US; this work retains only local metadata and commits no coordinate inventory. Exact footprint acceptance remains conditional on the site cross-check and the observed internal-version discrepancy being labeled in the resulting artifact.
