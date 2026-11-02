# Availability data, round 3 (phase 6) — Plan

**Status:** started on the owner's word on 2026-11-01 ("Do phase 6 now"). The answer named neither
prerequisite of the [outstanding-work plan](2026-10-30-outstanding-work.md), so the phase takes
its defaults, recorded here:

| Prerequisite | Default taken (2026-11-01) |
| --- | --- |
| Research budget | The plan's suggestion: 40 metadata requests, 10 probes, 150 MB and 10 OneBuilding file downloads on top of what earlier rounds used |
| 6.5 GHCNh | Out: the owner's 2026-10-27 deferral (Q6) stands, since it was not lifted |

**Owner review (2026-11-02):** "A; ok; ok; skip": Himawari-8 stays withdrawn; merge into `main`
and `deploy/staging`, push the open-data package and give the staging pin; delete the three merged
P5 branches; no message to OneBuilding.

**Branch:** `feature/availability-round-3` from `main` (`5d59a9f`). Merging, the open-data push
and the Render pin stay with the owner. Production (`feature/render-deploy`) is not touched.

**Sources:** the [2026-10-27 record](../../validation/availability-followups-2026-10-27/README.md)
("For the owner's review", "What this does not establish") and the
[availability gaps plan](2026-10-13-availability-gaps.md).

## 1. Budget

The research root stays `.local/mcp-availability/` (the ledger is never edited). After the
2026-10-27 round it had used metadata 93, probes 24, 193.75 MB and 47 OneBuilding attempts.

| Ceiling (phase 6 IDs only) | Before | Phase 6 | New ceiling |
| --- | --- | --- | --- |
| Metadata requests | 93 | +40 | 133 |
| Probes | 24 | +10 | 34 |
| Bytes | 193.75 MB | +150 MB | 344 MB |
| OneBuilding collector attempts | 47 | within the metadata above | 70 |
| PVGIS probes (provider cap) | 9 | within the probes above | 19 |
| OneBuilding file downloads (through the service, outside the collector) | — | 10 | 10 |
| NSRDB Himawari-8 10-minute years (configured key, outside the collector) | — | 3 | 3, 10 MB each |

Every collector request uses `--manifest`, the IDs below and one justified `-r1` revision at most;
a rate limit stops that provider's series.

## 2. Items and fixed requests

### 6.1 Unparsed workbook rows (offline)

The seven rows have four file-name shapes the parser did not accept:

| Rows | Shape | Example |
| --- | --- | --- |
| 2 CWEC | no country and state prefix | `CAN_Canada/BC_British_Columbia/Fort.St.John-North.Peace.Rgnl.AP.719430_CWEC.zip` |
| 3 TMY | a country but no state | `MHL_Marshall_Islands/MHL_Kwajalein-Bucholz.AAF.913660_TMY.zip` |
| 1 IMGW | no separator before the station | `POL_SL_Katowice.Intl.AP125600_IMGW.zip` |
| 1 ITMY | a dot after the state | `IRN_YA.Shahid.Sadooghi.AP.408210_ITMY.zip` |

Rule: names that parse today parse exactly as before. Only when they do not, the four shapes are
read, and a row is kept only if its country code matches the URL's country folder and its station
number equals the workbook's WMO column. One file of each new shape is downloaded through the
service (6.2 live checks).

### 6.2 Left-out families (CTZ2016, CTZ2022, CTZ2025, LuxTMY, ITMY)

Fixed before any request (all `https://climate.onebuilding.org/`, documentation or inventory):

| ID | URL | Header |
| --- | --- | --- |
| `onebuilding-sources-r20261101` | `sources/default.html` | `If-None-Match: "9474-65e5fce4a0013"` (2026-10-27) |
| `onebuilding-ctz2016-xlsx-r20261101` | `sources/CTZ2016_EPW_Processing_locations.xlsx` | `If-None-Match` its 2026-10-27 ETag |
| `onebuilding-ctz2022-xlsx-r20261101`, `-ctz2025-`, `-luxtmy-`, `-itmy-` | the same for each family | the same |
| `onebuilding-home` | `default.html` | — |

A changed workbook is re-read; an unchanged one (304) keeps the saved copy. The home page and at
most seven further pages it links, on the way to the CTZ, Luxembourg and Iran file lists, are
recorded here, with their IDs, before each is requested. A family is added only if a file link
published on a current workbook or page downloads through the service as a valid EPW (one file
per family). Paths are never guessed.

Pages recorded before their request (all linked from the previous page):

| ID | URL (`https://climate.onebuilding.org/`) | Linked from |
| --- | --- | --- |
| `onebuilding-region4-page` | `WMO_Region_4_North_and_Central_America/default.html` | home |
| `onebuilding-region6-page` | `WMO_Region_6_Europe/default.html` | home |
| `onebuilding-region2-page` | `WMO_Region_2_Asia/default.html` | home |
| `onebuilding-ctz-page` | `WMO_Region_4_North_and_Central_America/California_Climate_Zones/index.html` | region 4 page |
| `onebuilding-lux-page` | `WMO_Region_6_Europe/LUX_Luxembourg/index.html` | region 6 page |
| `onebuilding-irn-page` | `WMO_Region_2_Asia/IRN_Iran/index.html` | region 2 page |

### 6.3 PVGIS near-shore sea

At most nine probes (`pvgis-shore-<n>`, `re.jrc.ec.europa.eu/api/v5_3/tmy`, 1.5 MB each, a small
4xx body kept as before). Points are chosen offline by their distance from Natural Earth 1:10m land
and recorded here before sending. A rule is adopted only if every probe agrees with it; otherwise
sea points stay unknown and the evidence is recorded.

Measured the same way, the earlier probes were: Table Bay (served) 1.4 km and the North Sea
(refused) 16.4 km from land. Fixed points (distance to the nearest Natural Earth edge):

| ID | Point | Sea | Distance |
| --- | --- | --- | --- |
| `pvgis-shore-1` | 52.10, 4.20 | off the Dutch coast | 3.6 km |
| `pvgis-shore-2` | 52.10, 4.15 | off the Dutch coast | 6.2 km |
| `pvgis-shore-3` | 52.10, 4.08 | off the Dutch coast | 9.9 km |
| `pvgis-shore-4` | 52.10, 3.95 | off the Dutch coast | 12.8 km |
| `pvgis-shore-5` | −33.92, 18.30 | off Cape Town's Atlantic coast | 6.4 km |
| `pvgis-shore-6` | −33.92, 18.26 | off Cape Town's Atlantic coast | 9.9 km |
| `pvgis-shore-7` | 21.25, −157.86 | off Honolulu (outside SARAH3: ERA5 radiation) | 4.0 km |
| `pvgis-shore-8` | 21.20, −157.86 | off Honolulu | 7.8 km |
| `pvgis-shore-9` | 43.15, 5.36 | off Marseille | 6.5 km |

### 6.4 Himawari-8 re-binning at more places

Three 10-minute years through the configured NLR key (never logged), each analysed against the
fixed thresholds of 2026-10-27: annual GHI within 1% of the reference, and hourly RMSE at most 10%
of mean daylight GHI. Points and years are recorded here before downloading. The analysis is
first rerun on the 2026-10-27 Singapore file to reproduce its numbers.

Fixed before downloading (attributes GHI, DNI, DHI, air temperature and solar zenith angle; UTC;
leap day kept), chosen for latitude, hemisphere and viewing angle, all inside the Himawari mask:

| ID | Point | Year | Why |
| --- | --- | --- | --- |
| `h6-sapporo-2019` | 43.06, 141.35 | 2019 | mid-latitude, snow and low winter sun |
| `h6-auckland-2017` | −36.85, 174.76 | 2017 | southern hemisphere, maritime cloud |
| `h6-honolulu-2020` | 21.31, −157.86 | 2020 | far east of the satellite (about 62° of longitude): oblique view |

### 6.6 Catalog and package

New catalog generation, the 22-point matrix against the 2026.10.27 catalog, the memory check, the
lossless round trip, and the open-data package on a local branch, ready for the owner to push and
pin.

## 3. Execution notes

### Phase 6 (2026-11-01)

Results, the catalog and the package are in the
[record](../../validation/availability-round-3-2026-11-01/README.md). In short:

- **6.1:** the four file-name shapes are read only when the usual one fails, and a row is kept
  only when its WMO column confirms the station (`coordinates.irregular_identity`). Only shapes
  whose downloaded file passed reach the catalog (`analysis.VERIFIED_SHAPES`): the country-without-
  state shape (3 TMY rows, and 5 Guantanamo Bay TMYx rows of the Caribbean workbook). The CWEC and
  IMGW files of the other shapes return 404; no earlier URL parses differently (checked over all
  76,958 OneBuilding URLs of the analysis).
- **6.2:** all five workbooks and the sources page are unchanged (304). The file-list pages link
  CTZ2016, CTZ2022, CTZ2025 and LuxTMY at other published paths, which download and read
  (`analysis.PAGE_PATHS`); 362 files join. ITMY still fails.
- **6.3:** all nine probes were served; the 6 km near-shore rule replaces the inland margin in the
  mask's `refine` layer (`pvgis_mask.SHORE_KM`).
- **6.4:** Auckland 2017 fails the hourly threshold; Himawari-8 withdrawn from downloads by the
  owner's 2026-10-27 rule, for the owner to confirm.
- **6.5:** not done (deferred).
- **6.6:** generation `029d6de7`, matrix, memory (+5%), lossless round trip, package 2026.11.01 on
  the local open-data branch `data/weather-availability-catalog-2026.11.01` (`55682ee`), not
  pushed.

**Deviations.** A shell quoting mistake wrote the first three Himawari-8 downloads to one file;
Sapporo 2019 and Auckland 2017 were downloaded again (two requests beyond the three planned; logs
`h6-*-r1.json`). The first OneBuilding live-check run stopped on a script error after one
download; the rerun used the service's raw cache, so no file was fetched twice. One more file
than the eight planned was downloaded (a Guantanamo Bay TMYx file), within the ten allowed.

**New research scripts:** `scripts/onebuilding_live_check.py`, `scripts/himawari_rebin_check.py`
(reproduces the 2026-10-27 Singapore numbers exactly) and `scripts/availability_matrix.py`.

**Checks.** ruff (whole repository) and mypy clean. pytest (repository `.venv`): 1051 passed, 20
skipped, 0 failed. Offline evals: guided 34/34 and scripted agent 55/55 under `local` and `hosted`;
mutations 20 of 20 caught. No live model run.
