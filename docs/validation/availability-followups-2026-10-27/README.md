# Availability follow-ups, 2026-10-27: record

The owner's answers to Q1–Q9 and the item 7 budget are in the
[plan](../../superpowers/plans/2026-10-13-availability-gaps.md), "Owner decisions (2026-10-27)",
with the fixed request list and the step-by-step results. This record summarises the evidence,
the catalog it produced and its limits.

## Requests

All research requests went through the collector with `--manifest` and exact-ID allowlists; the
ledger was never edited.

| Ceiling (these IDs only) | Approved | Used after this round |
| --- | --- | --- |
| Metadata requests | 100 | 93 |
| Probes | 25 | 24 |
| Bytes | 240 MB | 193.8 MB |
| OneBuilding attempts | 55 | 47 |

- **Documentation and conditional requests:** the OneBuilding sources page (changed: LuxTMY
  added), NLR's Himawari-8 page (2016–2020; 10, 30 or 60 minutes), ECMWF's ERA5 and ERA5-Land
  documentation, ISD's inventory (304 Not Modified: frozen at 2025-08-30), two terms pages (CSIRO
  RMY2024, NatHERS RMY 2012).
- **Inventories:** 24 OneBuilding family workbooks (0.9 MB), Natural Earth 1:10m land (3.3 MB).
- **Probes:** PVGIS at Cape Town and in Table Bay (both returned a SARAH3 TMY).
- **Outside the collector** (configured NLR key, never logged): H1, one 10-minute Himawari-8 year
  at Singapore (2.2 MB); H4, Himawari-8 2018 at Sapporo through the service (two UTC files); O4,
  one file per OneBuilding family through the service (22, plus 5 re-runs of failures).

## Results

- **ERA5 poles (6a):** the CDS copy is a regular grid with values at 90° N and 90° S, so
  `POLAR_FOOTPRINT_CONFLICT` is retired; ERA5 at 89.6° N goes from unknown to supported.
- **ISD (6b):** frozen at 2025-08-30; GHCNh is on the roadmap (Q6).
- **PVGIS coasts (6d):** the mask's `refine` layer makes points at least one 0.0125° cell inland
  on Natural Earth land inside. Unknown station positions: 16.6% → 13.7%; Cape Town and Honolulu
  become supported. Sea points stay unknown.
- **Himawari-8 (item 2):** hourly rows are instantaneous :00 samples; irradiance is re-binned
  (annual GHI +0.10%, hourly RMSE 9.45% of mean daylight GHI, both within the fixed thresholds).
  H4: 8,760 rows, no missing GHI, solar-noon offset 0.05 h. Supported for 2016–2020 inside the
  Himawari mask (Singapore, Sapporo, Auckland, Honolulu, Tokyo, Seoul, Wellington, Hong Kong).
- **OneBuilding families (item 5):** 3,628 products in 17 families pass the live check. Left out:
  future files; ISHRAE, CSWD, RMY2012 and RMY2024 (terms); MetEireann (bare `.epw` links); CTZ2016,
  CTZ2022, CTZ2025 and LuxTMY (published paths return 404); ITMY (not a valid EPW).

## Catalog and package

- **Generation `2c0b88e7`** (data root `.local/cat-20261027`): 103 sources, 77,033 products,
  110,619 sites, 103,214 entries, 61 reviews. Before (`b17c5cf4`): 70 / 73,405 / 106,991 / 99,583 /
  61.
- **Matrix:** 22 points, typical and 2018 queries, against the previous catalog under the new code
  (`.local/mcp-availability/matrix-2026-10-27.json`): only the expected products change
  (Himawari-8, PVGIS at Cape Town and Honolulu, the new families at their cities). Ithaca, Lisbon
  and Buenos Aires are unchanged.
- **Memory** (`scripts/measure_catalog_runtime.py memory`, Windows working set, two rounds):
  529 → 562 MB after browsing, peak 545 → 577 MB (+6%), from the PVGIS `refine` layer (97,000
  runs) and the new products.
- **Package 2026.10.27:** local open-data branch `data/weather-availability-catalog-2026.10.27`,
  commit `b3885a8`, **not pushed**. 39 data files, 92.9 MB; `datapackage.json` SHA-256
  `6aab7111fd6c94ae6e3d60c371c31247ed5fee3ea75fe415f6b699233ed847d6`. Lossless: re-imported
  records are identical by type and the 12 footprint files are byte-identical; every committed
  blob matches the export; no source URL has a query string.

## For the owner's review (not stopping the work)

- **Unparsed workbook rows (7):** 2 CWEC, 3 TMY, 1 IMGW (`…Katowice.Intl.AP125600_IMGW.zip`) and
  1 ITMY.
- **Families left out after the live check:** CTZ2016, CTZ2022, CTZ2025 (their workbook URLs
  include `USA_United_States_of_America/`, which CTZ2010's working path lacks), LuxTMY and ITMY.
  File paths are never guessed; OneBuilding could be told.
- **Four owner-reviewed TMY files** (Mount Shasta, Apalachicola, Fort Worth Meacham,
  Sherman-Dennison) now also have coordinates in the TMY spreadsheet; the reviews (approximate
  localities) still apply because their pinned sources did not change.
- **Near-shore sea:** PVGIS served Table Bay 4 km offshore but refused the North Sea at 19 km; a
  sea-distance rule would need more probes.

## What this does not establish

- That every OneBuilding family file downloads: one file per family was checked.
- Himawari-8 re-binning accuracy beyond Singapore 2018 (one 10-minute year) and Sapporo 2018 (one
  hourly year).
- PVGIS's own coastline: the refinement is Natural Earth with a margin, checked at two points.
