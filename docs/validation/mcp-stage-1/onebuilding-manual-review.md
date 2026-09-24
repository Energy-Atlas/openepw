# OneBuilding individual case review — 2026-09-24

This is a reasoned review of the 61 products left unresolved by the automatic
matcher, using already captured source indexes and NOAA history. No new requests,
weather downloads, parser changes or production overrides were made.

## Principal correction

The earlier explanation described fallback NOAA failures, but missed direct
OneBuilding evidence: **all 56 Hawaiian products have the same complete filenames
in the published coordinate indexes**. Their catalog URLs use
`WMO_Region_4_North_and_Central_America`; the spreadsheet URLs use
`WMO_Region_5_Southwest_Pacific`. Everything after that region directory is identical,
including country/state directories, station identifiers, product families and
reference periods. Each filename has a unique published latitude/longitude/elevation
tuple in the downloaded index rows.

My judgment: this is strong metadata correspondence for the intended products,
not 56 genuinely unidentified places. Retain both URLs and the manually reviewed
relationship. Do not claim an HTTP redirect, identical archive bytes or verified
EPW-header coordinates: none was tested. Use each product's own indexed coordinates,
not one modern station coordinate for every historical period.

The automatic count remains 61 until a separate implementation applies reviewed
relationships. This review identifies 56 at the product-metadata level and gives
qualified judgments for the remaining five mainland products.

## Individual judgments

| Catalog identifier / location | Products | Evidence and judgment |
| --- | ---: | --- |
| 911977 — Bradshaw Army Airfield | 5 | Exact product filenames in Southwest Pacific index, differing only in region directory. Accept product-specific published metadata. NOAA's different position and roughly 89 m elevation discrepancy should not replace it. |
| 912960 — Hilo | 5 | Four TMYx products plus a Normals product have corresponding indexed filenames. Missing NOAA identifier is irrelevant to this direct evidence. Published locations are around 19.645, -155.083; do not substitute another Hilo station or assume the airport. |
| 911780 — Kalaeloa / NAS Barbers Point | 7 | All seven filenames correspond across region paths, including the TMY3 filename explicitly containing both names. This supports the naming association independently of guessing from NOAA aliases. Preserve per-product elevations and dates. |
| 911975 — Kona / Keahole | 7 | Indexed filenames identify each of the seven products. Source names themselves link Keahole and Kona. Coordinates vary by product/period; no single NOAA point should overwrite all seven. |
| 911905 — Lanai Airport | 7 | Seven complete filenames correspond, including TMY3 and TMYx/Normals naming variants. Use their individual coordinates/elevations, not a guessed common point. |
| 912950 — Mauna Loa Observatory | 6 | Five TMYx products and one Normals product have direct index counterparts. The source provides positions around 19.535, -155.576 and elevation 3407.4 m. No NOAA match is needed to identify this metadata. |
| 998193 — Moku-o-loe Marine Lab | 5 | Five exact filename counterparts establish the product metadata. The MOKUOLOE spelling difference is a secondary name issue, not a reason to ignore the direct index evidence. |
| 911860 — Molokai Airport | 8 | Eight exact filename counterparts, including two Normals periods. Preserve each period's source coordinates and elevation. NOAA record differences do not block this identification. |
| 911700 — Wheeler Army Airfield | 6 | Six corresponding index filenames. The indexed Wheeler name and site are more direct evidence than selecting between NOAA Wheeler/Wahiawa records. |
| 722200 — Apalachicola, older TMY | 1 | Same identifier and airport name in newer products, plus two nearby NOAA points. Confident intended airport identification; source-index point around 29.7333, -85.0333 is suitable as explicitly approximate discovery evidence. Exact older-TMY coordinates/elevation remain unverified. |
| 725957 — Mount Shasta, older TMY | 1 | Same identifier and place name occur in NOAA and newer products, with differing positions around 41.315–41.333, -122.317–-122.333. Identify the Mount Shasta station/locality provisionally; the filename's “Rep.AP” is insufficient to prove a particular airport or precise older-TMY site. |
| 723654 — Los Alamos, TMY2 | 1 | Same identifier/place in NOAA and newer source indexes. The historical NOAA record (1980–1997) at 35.879, -106.269 is a plausible candidate for an older product; another point is 35.883, -106.283. Product age is supporting context, not proof of which record supplied this TMY2. Identify locality, leave precise position unresolved. |
| 722600 — Fort Worth Meacham, older TMY | 1 | The saved OneBuilding indexes locate the exact airport name under 747390 around 32.819, -97.361. Identifier 722600 instead points to Stephenville/Clark Field around 32.216, -98.18. I would identify the intended named facility as Meacham, but retain a material name/code conflict. Do not silently change the product identifier or assign Stephenville weather. The old file's header is needed to adjudicate its actual station. |
| 722541 — Sherman–Dennison/Perrin Field, older TMY | 1 | Source indexes have Denison/North Texas Regional/Perrin Field under 720287 at 33.714, -96.674. Identifier 722541 instead identifies McKinney around 33.18, -96.59. Intended named facility is likely Perrin Field; file identity remains conflicted. Do not silently substitute McKinney or relabel this old TMY as 720287. |

Total: 56 Hawaiian product-metadata correspondences, three mainland products with
credible locality identification but uncertain exact historical coordinates, and
two mainland products with material name/code conflicts. These are review judgments,
not weather-content acceptance or claims that old identifiers were necessarily wrong;
historical identifier reuse or catalog errors remain possible explanations.

## Evidence and reproducibility

Evidence IDs: `onebuilding-us-xlsx`, `onebuilding-au-coordinate-xlsx`,
`onebuilding-normals-coordinate-xlsx`, `onebuilding-tmy3-coordinate-xlsx`,
`noaa-history`; checksums and source URLs are in [the evidence ledger](evidence.json).
Full indexed rows remain local. The 56 checked correspondences were saved locally
as `.local/mcp-availability/onebuilding-manual-hawaii-correspondence.json`, retaining
both paths, source evidence IDs and per-product coordinates. Their inspection
confirmed only the region-directory difference, without broad URL normalization.

Recommended next step is to encode these reviewed relationships as explicit,
provenance-bearing research annotations, keeping exact-index, reviewed-metadata,
approximate-locality and conflicted-file states separate. This review does not
introduce that mechanism or authorize more network calls.
