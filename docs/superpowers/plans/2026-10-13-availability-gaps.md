# Availability gaps: PVGIS coverage first

Status: item 1 approved by the owner on 2026-10-13 (D1–D3 below) and done. Branch
`feature/availability-gaps`, from `main` at `6a9f53d`. The
[record](../../validation/availability-gaps-2026-10-13/README.md) has the requests, results and
limits.

Follows the [2026-10-13 coverage plan](2026-10-13-availability-coverage.md), its section
"Done, and what is left", and the method of its [record](../../validation/availability-coverage-2026-10-13/README.md):
- requests go through the collector into `.local/mcp-availability/`;
- offline analysis and re-import;
- a validation record;
- a new dated open-data version.

Items are taken in the order of that section. This revision covers item 1 (PVGIS) only.

## Item 1. PVGIS 5.3 TMY: what the documentation says

These are documentation pages and one report, read outside the collector as in the
[2026-09-24 map review](../../validation/mcp-stage-2/pvgis-map-evidence.md). No PVGIS API
request was made.

| Source | Read | What it gives |
|---|---|---|
| [PVGIS 5 user manual](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/pvgis-5-user-manual_en) | page | SARAH3 is the 5.3 default for "Europe, Central Asia, Africa and South America (partly)". ERA5 is the default "for rest of the world without coverage from satellite-based DBs". "These are also the databases used in the TMY tool." SARAH3 and ERA5 both run 2005–2023. |
| [API, non-interactive service](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/getting-started-pvgis/api-non-interactive-service_en) | page | `tmy` takes no `raddatabase`. `startyear` and `endyear` default to the database's period, which must be at least 10 years. Nothing on sea points or error bodies, beyond a JSON error for out-of-range inputs. |
| [PVGIS 5.3 release](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/pvgis-releases/pvgis-53_en) | page | 5.3 has been the production API since September 2024. SARAH3, ERA5 and the ERA5-Land/ERA5 meteorology each cover "Sea: 25 km coastal zone". |
| [PVGIS 5.3 Dataset Update](https://joint-research-centre.ec.europa.eu/document/download/aa763480-b092-48af-a7f8-42913b43d305_en?filename=Report_2024_PVGIS_5.3_Datasets_Update.pdf) (JRC139355, 2024) | PDF, 3,141,949 bytes, SHA-256 `29d6607f513dfcf5…`; kept in `.local/mcp-availability/documentation-2026-10-13/` | See below. |

The JRC139355 report (Table 1, §3.1, §3.2.1) is the most specific source:
- **SARAH3:** 2005–2023, about 5 km, spatial extent 65°W–65°E and 65°N–60°S.
- **ERA5 radiation:** 2005–2023, 31 km, spatial extent 180°W–180°E and 75°N–60°S.
- **Other variables:** ERA5-Land, with ERA5 for coastal pixels that ERA5-Land leaves empty
  ("ERA5LandPlus").
- **Sea:** coverage is "extended to cover 25 km of coastal waters". The coastline is a
  vectorisation of SRTM (60°N–60°S) and GTOPO30 elevation data, buffered 25 km towards the sea.
- **Grid:** the PVGIS tiling grid runs from 180°W to 180°E and from 75°N to 60°S.

**What follows from the documentation.**
- PVGIS 5.3 TMY is one service with a per-location radiation source:
  - SARAH3 where it is the default;
  - ERA5 elsewhere, with ERA5-Land meteorology throughout.
- Every point has a 2005–2023 source period.
- A response reports its own `radiation_db` (London: `PVGIS-SARAH3`, `ERA5` meteorology).
- Documented domain: land and a 25 km sea zone, between 60°S and 75°N. Open sea, polar
  land beyond the grid, and Antarctica are outside it.
- The SARAH3 box (65°W–65°E, 65°N–60°S) is not the SARAH3 default area. JRC's
  [coverage figure](https://joint-research-centre.ec.europa.eu/sites/default/files/2024-09/PVGIS_53_DB_Coverage.png)
  shows ERA5 inside it at high latitudes.

**What the documentation leaves open.**
- Nothing documents the error for a point outside the domain.
- Nothing documents whether large lakes count as sea.
- The ERA5 fallback has not been observed through `tmy`.
- The coastline is PVGIS's own, not ECMWF's land–sea mask.
- JRC publishes no raster of the domain or of the SARAH3/ERA5 split. Its Data Catalogue
  record for the PVGIS 5.3 rasters refused an automated read. The record is
  `data.jrc.ec.europa.eu/dataset/eef67979-…`; the request was not retried.

**Current catalog problems this exposes.**
- `products.py` labels the product "PVGIS TMY 5.3 · SARAH3". That is wrong wherever ERA5
  is the source.
- The only entry is London's probe, with London's selected month-years. Those must never
  be applied elsewhere. A documented entry needs the 2005–2023 period without selected
  months.

## Evidence and budget (approved 2026-10-13, D3)

**P1. Bounded TMY probes.**
- Each probe is one `GET https://re.jrc.ec.europa.eu/api/v5_3/tmy?lat=…&lon=…&outputformat=json`,
  the London request's form, through the collector (`kind: probe`, `provider: pvgis`,
  `--manifest`).
- A successful response is about 1.27 MB; an error is expected to be under 10 KB.
- No key or credential is involved.

| ID | Point (lat, lon) | Uncertainty | Expected | Stop |
|---|---|---|---|---|
| `pvgis-ithaca` | 42.44, −76.50 | ERA5 fallback through `tmy`, outside the SARAH3 box | TMY, `radiation_db` `PVGIS-ERA5`, 2005–2023 | after one response |
| `pvgis-atlantic` | 40.0, −40.0 | Open sea, more than 1,000 km from land | small JSON error | after one response |
| `pvgis-northsea` | 52.30, 4.20 | Sea about 15 km off the Dutch coast, inside the 25 km zone | TMY, `PVGIS-SARAH3` | after one response |
| `pvgis-svalbard` | 78.22, 15.65 | Land north of the 75°N grid edge | small JSON error | after one response |
| `pvgis-lake-victoria` | −1.0, 33.0 | Large lake, more than 60 km from any shore | unknown: TMY or error | after one response |

**Caps.**
- 1.5 MB per probe, 7.5 MB in total.
- The PVGIS probe cap rises from 2 to 7, for these five IDs and one justified `-r1` revision.
- The probes count against Stage 1's remaining ceilings: 5–6 of the 6 probes left, and up to
  7.5 MB of the 16.8 MB left. A rate-limit or overload response (429 or 529) stops the
  series; nothing is retried.

**P2. Offline mask, no requests.**
- Build a 0.1° PVGIS domain mask from the ERA5-Land land–sea mask already held
  (`era5land-lsm-r1`), within 60°S–75°N.
- Proposed rule, pending decision D2:
  - inside: a land fraction of at least 0.5;
  - outside: farther than 50 km from any point with a land fraction above 0, or beyond the
    grid's latitudes;
  - between the two: unknown. This band covers PVGIS's own coastline, its 25 km zone and
    small islands.
- P1 checks the rule at its points before the mask is accepted.
- The coverage module needs an explicit edge band for this, because its current edge is one
  cell. The change stays in `coverage.py`; `catalog_index.py`, `store.py` and `deploy.py` are
  not touched.

**Cheaper alternative (not recommended).** The same five points could be probed through
`PVcalc` instead, at a few KB each. That relies on the manual's statement that TMY uses the
same default databases, rather than observing TMY itself.

## Owner decisions (2026-10-13)

- **D1. One product, both sources.**
  - Option (a): PVGIS TMY 5.3 is offered as one product whose radiation is SARAH3 or ERA5 by
    location, recorded per run.
  - Not chosen: two products, or SARAH3 only.
  - The label is written "SARAH3/ERA5", because choice labels never contain " or ".
- **D2. The mask rule in P2, with its unknown band.**
  - P1 showed two gaps, both corrected towards unknown and recorded in the
    [record](../../validation/availability-gaps-2026-10-13/README.md).
  - Lake Victoria was served, so water not connected to the ocean is never outside.
  - Atolls ERA5-Land misses would have been excluded, so published station positions count as
    land.
- **D3. P1 approved as listed.**

## Result (2026-10-13)

- **Requests.** P1 used all six requests.
  - Ithaca: TMY with ERA5 radiation.
  - Lake Victoria: TMY with SARAH3.
  - Atlantic, Svalbard and the North Sea at about 19 km: 400 "Location over the sea". The
    North Sea needed the one revision after a transport error.
  - Stage 1's probe ceiling is now used up: 12 of 12, with 14.3 MB left.
- **Catalog.**
  - The mask gates PVGIS TMY.
  - A documented 2005–2023 entry applies inside the mask, and each probe keeps its own months.
  - The map draws the mask.
- **Matrix.** Supported points went from 1 of 24 to 15; 3 are excluded and 6 unknown (coasts,
  atolls).
- **Package.** 2026.10.13.1 was exported to the local open-data branch
  `data/weather-availability-catalog-2026.10.13.1` (`b606e1e`). The round trip is lossless.
  It is not pushed: the owner confirms the push, then pins staging.

## Items 3 and 4 (approved 2026-10-13: D4, D5, D6)

The owner asked to proceed towards items 3 and 4 on 2026-10-13, after the open-data push.
On the same day the owner approved D4 (documented year lists), D5 (the non-missing ERA5-Land
gate) and D6 (the budget as listed).

### What is already known (offline)

**NLR's dataset pages** give one year list per dataset, the `names` values, with no regional
variation:
- GOES aggregated v4: 1998–2025.
- Himawari-7: 2011–2015.
- Meteosat: 2005–2022, although the same page's prose says "2017–2019".

The five probes list exactly these years.

**The S3 bucket is not the API.** It holds Himawari-7 files for 2011–2020, while the API offers
2011–2015. The years must come from the API and its documentation.

**Mask extents.**
- GOES (`tdy-2023`, which also gates GOES actual years): 21° S to 60° N.
- Himawari-7: 55° S to 60° N.
- Meteosat and IODC: 54.75° S to 60° N.
- Buenos Aires, Santiago, Anchorage and Ushuaia are outside every NSRDB mask. GOES full disc
  (2018 on, not downloaded by the adapter) is documented over all of GOES's view.

### Proposed evidence

**N1. Edge probes.** Ten NSRDB data-query probes through the collector.
- Same form as E2: `GET https://developer.nlr.gov/api/solar/nsrdb_data_query.json` with
  `api_key=DEMO_KEY&wkt=POINT(lon lat)`, 1 MB cap each, about 16 KB expected.
- They test whether the year lists hold at each grid's edges, and the GOES gate's southern
  limit.

| ID | Point | Grids tested |
|---|---|---|
| `nsrdb-honolulu` | 21.307, −157.858 | GOES west edge, Himawari-7 east edge |
| `nsrdb-recife` | −8.05, −34.90 | GOES east edge |
| `nsrdb-juneau` | 58.30, −134.42 | GOES north edge |
| `nsrdb-buenos-aires` | −34.60, −58.38 | just outside the GOES mask: is GOES aggregated listed? |
| `nsrdb-cape-town` | −33.925, 18.424 | Meteosat and IODC south |
| `nsrdb-oslo` | 59.91, 10.75 | Meteosat and IODC north |
| `nsrdb-dakar` | 14.69, −17.44 | Meteosat and IODC west |
| `nsrdb-auckland` | −36.85, 174.76 | Himawari-7 south-east |
| `nsrdb-sapporo` | 43.06, 141.35 | Himawari-7 north |
| `nsrdb-almaty` | 43.24, 76.95 | IODC north-east |

- Caps: plus one justified `-r1` revision. The NSRDB probe cap rises 6 → 17 and the overall
  probe ceiling 12 → 23, for these IDs only.
- Bytes come from the 14.3 MB left.
- Stop after the ten, or on any rate limit.

**N2. Earliest-year downloads.** Four hourly downloads with the configured NLR key, outside
the collector, logged like E5:
- GOES aggregated 1998 at Juneau;
- GOES aggregated 1998 at Honolulu;
- Meteosat 2005 at Oslo;
- Himawari-7 2011 at Auckland.

Each uses the nine EPW attributes, with a 2 MB cap (about 0.6 MB expected) and 8 MB in total.
The check: 8,760 rows, no fill values, and solar values that are not all zero. The key never
enters a log or file.

**N3. Dataset pages.** Through the collector (documentation, 1 MB cap each), keeping each
documented year list as evidence:
- `nsrdb-GOES-aggregated-v4-0-0-download`;
- `nsrdb-GOES-tmy-v4-0-0-download`;
- `himawari7-download`;
- `himawari-tmy-download`;
- `nsrdb-msg-v1-0-0-download`, and its `-tmy`, `-tdy` and `-tgy` pages;
- `meteosat-download` (IODC).

These are nine metadata requests out of the 10 left in Stage 1, all under
`https://developer.nlr.gov/docs/solar/nsrdb/`.

**C1. One ERA5-Land field** from CDS, outside the collector (CDS jobs need the configured key).
- Request: `reanalysis-era5-land`, `2m_temperature`, 2020-01-01 00:00, global, GRIB,
  unarchived.
- Requests: 1 submit, at most 60 status polls 10 s apart, 1 results lookup and 1 download of at
  most 15 MB (about 6 MB expected).
- Stop when saved, or on failure. It is not resubmitted without the owner.
- Each request is logged without the key.
- The GRIB decoder gains bit-map support, so missing points read as missing.

### Decisions (owner, 2026-10-13: all as recommended)

- **D4. NSRDB years.** If every N1 edge point lists the documented years and N2 finds real
  data:
  - each dataset's documented year list becomes an area-wide entry inside its mask, as for
    PVGIS;
  - if any edge differs, stop and report.
- **D5. ERA5-Land gate.** Replace the land-fraction mask with C1's non-missing points:
  - inside: ERA5-Land has a value, including lakes and low-fraction coasts;
  - outside: no value;
  - near the edge: the neighbouring cell.
- **D6. Budget.** N1–N3 and C1 as listed.

### Result (2026-10-13)

- **NSRDB.**
  - All ten edge probes list the same years and files as the earlier five, and the four
    earliest-year downloads hold full data.
  - Nine adapted datasets now have an area-wide documented entry inside their masks.
  - NLR's GOES TMY page lags the data query, so the probes' list is used.
- **ERA5-Land.** One CDS field gives the mask of points with values, which now gates ERA5-Land.
- **Package.** 2026.10.13.2 is committed on the local open-data branch
  `data/weather-availability-catalog-2026.10.13.2` (`958907a`). The push waits for the owner.
- See the [record](../../validation/availability-gaps-2026-10-13/README.md).

## Remaining items: scope and proposals (2026-10-15; decided 2026-10-27)

The owner's answers are in "Owner decisions (2026-10-27)" below. For each item:
- the challenge, and why it was not already included;
- the scope;
- the plan;
- the limits and stopping conditions;
- the owner's open questions (Q1–Q9).

Research ceilings now: metadata 59 of 60, probes 22 of 23 (N1 only), 186.2 MB of 200 MB.

### Item 2. NSRDB Himawari-8 (`himawari`, 2016–2020)

**Challenge.**
- Its hourly values are labelled at :00 and centred on the hour, so they span :30 to :30.
- EPW rows are hour-ending, and ADR 0002 defers fractional-hour interpolation.
- No Himawari-8 grid mask exists. Its 2 km grid table is several times the size of
  Himawari-7's.

**Scope.**
- Asia–Pacific, 2016–2020.
- Every probe inside the Himawari-7 mask lists it: Singapore, Honolulu, Auckland and Sapporo.
- The API offers 10, 30 and 60-minute intervals.

**Plan.**
- **H1.** One 10-minute download at Singapore for 2018, about 3.6 MB with the NLR key. Compare
  it with the 60-minute file already held, to learn whether sub-hour values are instantaneous
  samples or interval means and where they are labelled.
- **H2.** If they are means or regular samples, build hour-ending values by aggregating the
  sub-hour values inside each EPW hour. This is aggregation, not interpolation, and needs an
  ADR 0002 amendment.
- **H3.** Gate Himawari-8 by the Himawari-7 mask, as already done for Himawari TMY, on the
  strength of the four probes.
- **H4.** Live acceptance: the solar-noon offset check near 0 for hour-ending labels, and the
  hourly sums against the 60-minute product.

**Stop** if H1 shows labels or semantics that do not allow an exact hour-ending aggregate.
Himawari-8 then stays catalogued but not downloaded.

**Cost per user request.** A 10-minute year is about 6 times the 60-minute download; a
30-minute year about 2 times.

- **Q1.** Approve the aggregation method in principle (H2), and H1?
- **Q2.** Use 10 or 30-minute data?

### Item 5. OneBuilding national and special typical-year families

**Challenge.** These were out of scope in the earlier plans, and each family needs its own
workbook request, product naming and terms check.
- The OneBuilding request cap is spent: 22 of 22.
- Several families are future-climate files, which need scenario and window semantics, not
  a typical-year reference period.
- Originator terms differ by family.

**Scope.** From the sources page snapshot of 2026-09-23. The page's Last-Modified was
2026-08-24.

| Kind | Families (locations) |
|---|---|
| Existing-weather typical years | NORCERRA Norway (358); CWEC full, Canada (2,265: CWEC, 2016, 2020, 2020v2, TDY 2020v2); CSWD China (270); INMET and TRY Brazil (411 + 17); CTZ California (v2, 2010, 2016, 2022, 2025: about 424); JGMY (157, synthetic); TurTMY (81); RMY2012 Australia (69 × 3 solar weights); ISHRAE 2014 India (62); IMGW Poland (61); PHIKO South Korea (22); NIWA New Zealand (18); ArgTMY (15); TMY (12); ITMY Iran (6); AMTUes Uruguay (5); IMS Israel (4); CityUHK Hong Kong (1) |
| Mixed (current and future) | RMY2024 Australia (83 + RCP futures); NIWA2024 (18 + SSP futures); MetEireann (6 + futures); BBSR Germany (15 + 2035) |
| Future only | Canada NRC Future (18,049 rows, 4 kinds); BrazFuture (28) |

**Plan.**
- **O1.** One conditional re-request of the sources page, with its ETag, to catch changes.
- **O2.** The workbooks for the existing and mixed families: 27 requests.
  - CWEC full, which should cover every CWEC version (the per-version workbooks only as a
    fallback);
  - the six CTZ workbooks;
  - each other family once.
  - About 5 to 10 MB expected, 5 MB cap each.
- **O3.** Offline:
  - a register of each family's originator, method, period and terms link;
  - product names per family, with the same coordinate and NOAA cross-checks and owner review
    of unmatched rows as for TMYx;
  - mixed families import only their historical-period files.
- **O4.** Check that the adapter downloads one file per new family, live and opt-in.

**Limits and stop.**
- About 30 OneBuilding requests and one revision each, at normal host spacing.
- Stop on any rate limit, or on a workbook format the parser rejects.

- **Q3.** Catalog the future-only and future parts of the mixed families as published future
  files (a new product kind), or leave them out?
- **Q4.** Publish metadata for every family, or leave out families whose originators restrict
  their files, such as ISHRAE (sold) and possibly CSWD and RMY?
- **Q5.** Include JGMY, which is synthetic and statistically generated, as a typical year, or
  mark it as synthetic?

### Item 6. Smaller unknowns

**6a. CDS polar footprint.**
- The CDS records give ±89°, so the evaluator leaves |lat| ≥ 89 unknown for ERA5 and
  ERA5-Land.
- ERA5's documented grid is global, and the new ERA5-Land mask already covers Antarctica.
- Plan: one documentation read through the collector (the last metadata request); if the grid
  reaches ±90, drop the polar unknown.

**6b. NOAA years after the inventory.**
- `isd-inventory.csv` was last modified 2025-08-30, so 2025 is partial and 2026 is unknown.
- NOAA has moved ISD to GHCNh, which the adapter does not read.
- Plan: one conditional request (`If-None-Match`). If it is unchanged, record ISD as frozen at
  August 2025. If it has changed, re-download it (about 15 MB, under the 20 MB exception).
- **Q6.** Should a GHCNh adapter for observations from 2025 on be added? It is a new provider
  and a larger project.

**6c. The half-hour time-zone tie rule.**
- With +5:30, the rule (nearest whole hour, a tie towards mean solar time) gives Mumbai +5 and
  Kolkata +6, inside one civil zone.
- There is no data to collect.
- **Q7.** Keep it, use one offset per zone (all of India +5 or +6), or wait for a sub-hour
  shift such as item 2's?

**6d. Found in this round.**
- Coastal points whose 0.1° cell is mostly water are unknown for PVGIS: 17% of stations.
  - A public-domain coastline (Natural Earth 10 m land, about 5 MB) could decide land or sea
    per point.
- The CDS adapter takes the nearest grid cell, which near a coast can be an ERA5-Land cell
  with no value. This still needs verifying.
- Meteosat 2005 wind at Oslo looks implausible: at most 1.3 m/s.
- **Q8.** Take up the coastline refinement?

### Item 7. Budget

Stage 1's ceilings are nearly used. Proposed new ceilings for items 2, 5 and 6, with exact IDs
and URLs fixed at approval as before:
- metadata 60 → 100;
- probes 23 → 25;
- bytes 200 → 240 MB;
- OneBuilding attempts 22 → 55;
- outside the collector: one NSRDB download (H1) and later acceptance downloads.

### Item 8. OneBuilding terms

**Challenge.** The site gives no licence and its footer reads all rights reserved. The
catalog's OneBuilding metadata is published by owner override.

**Options.**
- (a) The owner asks OneBuilding (Lawrie and Crawley) for permission to republish the
  metadata. A draft can be prepared; sending it is the owner's.
- (b) Keep the override and document it, which is the current state.
- (c) Keep OneBuilding out of the public package, and supply it to the hosted service
  separately.

This is not a legal opinion.
- **Q9.** Which option? Shall I draft the message for (a)?

### Release steps (owner go-ahead 2026-10-26)

- **Done:** `feature/availability-gaps` merged into `main` (`2047ec9`) and `main` into
  `deploy/staging` (`ac9856f`), after ruff, mypy, the full test suite and the offline evals on each
  merged tree. Masks without `edge_runs` keep the earlier edge rule, so staging stays correct on the
  2026.10.13 package until the pin changes.
- **Done:** open-data 2026.10.13.2 pushed (branch `data/weather-availability-catalog-2026.10.13.2`,
  commit `958907a5cdf3353853de45395b43229e8524ab41`). The raw `datapackage.json` URL serves
  SHA-256 `e46dace1892aacce26c7d3173ad0514dcc7618e22ecc9b92f4f6e8103cf3fcd5`.
- **Waiting for the owner:** pin staging in the Render dashboard (the code is already deployed):

  ```text
  OPENEPW_CATALOG_URL=https://raw.githubusercontent.com/Energy-Atlas/open-data/958907a5cdf3353853de45395b43229e8524ab41/datasets/weather-availability-catalog/datapackage.json
  OPENEPW_CATALOG_SHA256=e46dace1892aacce26c7d3173ad0514dcc7618e22ecc9b92f4f6e8103cf3fcd5
  ```

- Items 2 and 5–8: the owner answered Q1–Q9 on 2026-10-27; see "Owner decisions (2026-10-27)".

## Owner decisions (2026-10-27)

All answers were given in conversation on 2026-10-27. Work runs on `feature/availability-followups`
(from `main` at `f0d11e0`). Nothing is merged into `main` or `deploy/staging`, and no open-data
release is pushed, without the owner's go-ahead.

| # | Decision |
| --- | --- |
| Q1 | **H1 approved:** one 10-minute download at Singapore for 2018, for research only (to learn how sub-hour values are labelled and how large the re-binning error is). |
| Q2 | **Hourly only.** Users get 60-minute Himawari-8 data; 10 and 30-minute data are not offered. |
| Q1/Q2 method | **Re-bin, checked.** Instantaneous variables (temperature, humidity, wind, pressure) keep their :00 values (if H1 confirms they are instantaneous), which match EPW's hour-ending timestamps. Each irradiance hour ending at *h* is the mean of the two centred values labelled *h − 1* and *h*, which keeps totals. H1 measures the error against the sub-hour data; ADR 0002 gets an amendment. **Stop** if the error is large or the labels do not fit; Himawari-8 then stays catalogued but not downloaded. |
| Q3 | Future-only families and the future parts of mixed families are **left out**; mixed families import only their historical files. |
| Q4 | Families whose originators restrict their files are **left out**: ISHRAE (sold). CSWD and RMY only if a terms check clears them. |
| Q5 | **JGMY included**, marked synthetic (statistically generated). |
| Q6 | **No GHCNh adapter now.** ISD is recorded as frozen at August 2025 if the inventory is unchanged; GHCNh goes on the roadmap. |
| Q7 | **Keep the tie rule** (nearest whole hour, a tie towards mean solar time), documented. |
| Q8 | **Coastline refinement approved:** Natural Earth 10 m land (public domain) decides land or sea for coastal PVGIS points. |
| Q9 | **Option (b):** keep the owner override for OneBuilding metadata and document it. No message is sent. |
| Item 7 | **Budget as proposed:** metadata 60 → 100, probes 23 → 25, bytes 200 → 240 MB, OneBuilding attempts 22 → 55, plus the H1 download and small live acceptance downloads (one file per new OneBuilding family, one Himawari-8 year). |
| Release | Stop before merging: feature branches are pushed as a backup only. |

Unmatched OneBuilding rows (no coordinate or NOAA match) are left out of the catalog and listed for
the owner's later review; they do not stop the work.
