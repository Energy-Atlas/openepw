# Availability round 3 (phase 6), 2026-11-01: record

The budget, the fixed request lists and the step-by-step notes are in the
[phase 6 plan](../../superpowers/plans/2026-11-01-availability-round-3.md). This record
summarises the evidence, the catalog it produced and its limits.

## Requests

All collector requests used `--manifest` and the plan's exact-ID allowlist; the ledger was never
edited.

| Ceiling | Phase 6 allowed | Phase 6 used | Ledger after |
| --- | --- | --- | --- |
| Metadata requests | 40 | 13 | 106 of 133 |
| Probes | 10 | 9 | 33 of 34 |
| Bytes | 150 MB | 11.7 MB | 205.5 of 344 MB |
| OneBuilding file downloads (service) | 10 | 9 | — |
| NSRDB 10-minute years (configured key) | 3 | 5 (2 repeated, see below) | — |

- **Conditional requests (304, unchanged since 2026-10-27):** OneBuilding's sources page and the
  CTZ2016, CTZ2022, CTZ2025, LuxTMY and ITMY workbooks.
- **Pages:** OneBuilding's home page, the North and Central America, Europe and Asia region pages,
  and the California climate zones, Luxembourg and Iran file lists, each recorded in the plan
  before its request.
- **Probes:** nine PVGIS TMY requests at sea, `pvgis-shore-1` to `-9`.
- **Outside the collector:** nine OneBuilding files through the service
  (`onebuilding-acceptance-2026-11-01.json` and `-b.json`); three Himawari-8 10-minute years
  (`nsrdb-acceptance/h6-*`). A shell quoting mistake wrote the first three downloads to one file,
  so Sapporo and Auckland were downloaded once more (`-r1` logs).

## Results

- **6.1 Unparsed workbook rows.** The seven rows have four file-name shapes. Read only when the
  usual pattern fails, and kept only when the station number equals the workbook's WMO column and
  the country matches the URL's folder. One file per shape was downloaded:
  - a country but no state (`MHL_Kwajalein-Bucholz.AAF.913660_TMY.zip`): passes. The 3 TMY rows
    and, with the same shape, the 5 Guantanamo Bay TMYx rows of the Caribbean workbook join (one
    Guantanamo file also downloaded and read);
  - no prefix (2 CWEC rows) and no separator before the station (1 IMGW row): the files return 404
    and stay out;
  - a dot after the state (1 ITMY row): the family stays out (below).
- **6.2 Left-out families.** The workbooks are unchanged, but the current file-list pages link
  the CTZ files under `California_Climate_Zones/` (without the workbooks'
  `USA_United_States_of_America/` folder) and the LuxTMY files under `LUX_Luxembourg/`. Every
  workbook row matched a page link by its exact file name; 11 CTZ page links without a workbook row
  stay out (no published coordinates). One file per family downloaded and read: 8,760 rows, header
  at the workbook point. **362 files join:** CTZ2016 102, CTZ2022 97, CTZ2025 134, LuxTMY 29.
  ITMY's Bandar Abbas file is still not a valid EPW, so ITMY stays out.
- **6.3 PVGIS near-shore sea.** Every probe returned a SARAH3 (or, at Honolulu, ERA5) TMY: 3.6,
  6.2, 9.9 and 12.8 km off the Dutch coast, 6.4 and 9.9 km off Cape Town, 4.0 and 7.8 km off
  Honolulu, 6.5 km off Marseille (distances to the nearest Natural Earth 1:10m edge; by the same
  measure Table Bay, served, is 1.4 km out and the refused North Sea point 16.4 km). **Rule
  adopted:** inside the mask's unknown band, a fine cell counts as inside when its centre is within
  6 km of a Natural Earth land cell's centre, on land or at sea. Every probed coast was served at
  6.2 km or more. Unknown published station positions inside 60° S–75° N: **13.7% → 3.5%** (5,319
  → 1,347 of 38,742).
- **6.4 Himawari-8 re-binning.** The analysis reproduces the 2026-10-27 Singapore numbers exactly
  (annual +0.096%, hourly RMSE 9.45%). Against the fixed thresholds (annual GHI within 1%, hourly
  RMSE at most 10% of mean daylight GHI):

  | Place and year | Annual GHI | Hourly RMSE | Without re-binning | Result |
  | --- | --- | --- | --- | --- |
  | Sapporo 2019 | −0.03% | 9.86% | 19.9% | pass |
  | Auckland 2017 | −0.42% | **12.64%** | 22.6% | **fail** |
  | Honolulu 2020 | −0.06% | 8.25% | 17.6% | pass |

  Auckland's maritime cloud varies within the hour, so two samples misjudge the hour's mean more
  often. By the owner's 2026-10-27 rule (Q1/Q2: "stays catalogued but not downloaded" when the
  error is large), Himawari-8 is withdrawn from downloads: the catalog lists it as an upstream
  product (`nsrdb:upstream:himawari`) with its probe entries, and the adapter no longer requests it.
  The re-binning code stays for research. This is a decision for the owner to confirm (below).
- **6.5 GHCNh:** not done; the 2026-10-27 deferral stands.

## Catalog and package

- **Generation `029d6de7`** (data root `.local/cat-20261101`): 119 sources, 77,403 products,
  110,989 sites, 103,592 entries, 61 reviews. Before (`2c0b88e7`): 103 / 77,033 / 110,619 /
  103,214 / 61. The 72 stale sources are the same as before.
- **Matrix** (`scripts/availability_matrix.py`, the 22 places of 2026-10-27 plus five, typical and
  2018, both catalogs under the new code; `.local/mcp-availability/matrix-2026-11-01.json`): only
  the expected products change. PVGIS becomes supported at Auckland, Lisbon, Venice and Kwajalein;
  CTZ2016, CTZ2022 and CTZ2025 at Fresno and Alturas; LuxTMY at Luxembourg; TMY at Kwajalein. The
  other 40 queries are unchanged. (The Himawari-8 offer is a code change and is absent under both.)
- **Memory** (`scripts/measure_catalog_runtime.py memory`, Windows working set, two rounds): 561 →
  588 MB after browsing, peak 577 → 605 MB (+5%), mostly from the PVGIS mask (2.5 → 5.2 MB, 1.15
  → 3.72 million fine cells; 1.2 MB gzipped).
- **Package 2026.11.01:** local open-data branch `data/weather-availability-catalog-2026.11.01`,
  commit `55682ee`, **not pushed**. 39 data files, 96.0 MB; `datapackage.json` SHA-256
  `52d57fae4f11276db7b38a47317d97e3195b5a55bfd7820928aeffacb695bd35`. Lossless: re-imported
  records are identical by type and the 12 footprint files are byte-identical; no source URL has a
  query string.

## For the owner

- **Himawari-8:** confirm the withdrawal, or keep it downloadable with a warning, or have the
  adapter build each hour from the 10-minute data (exact hour means; six times the download, a
  method change to ADR 0002). The package matches the withdrawal; keeping Himawari-8 needs a new
  export.
- **Release order:** the package and the code ship together. Code that still offers Himawari-8 with
  this package would offer it without a catalog product, and this code with the 2026.10.27 package
  keeps the old PVGIS coasts.
- **OneBuilding:** the CTZ2016/2022/2025 and LuxTMY workbook URLs return 404 while the pages link
  working paths; CWEC's Fort St John and Quebec-Lesage and IMGW's Katowice files return 404; ITMY's
  files do not parse. OneBuilding could be told (an external message, so not sent).

## What this does not establish

- That every new OneBuilding file downloads: one file per family or shape was read.
- PVGIS's own coastline: the 6 km rule rests on eleven sea points on four coasts.
- Himawari-8 re-binning error elsewhere: four place-years in all.
