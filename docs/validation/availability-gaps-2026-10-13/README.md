# Availability gaps, 2026-10-13: PVGIS 5.3 TMY coverage

The record of item 1 of the [availability-gaps plan](../../superpowers/plans/2026-10-13-availability-gaps.md),
in the format of the [2026-10-13 coverage record](../availability-coverage-2026-10-13/README.md).
- Raw responses, the ledger and the analysis stay local, under `.local/mcp-availability/`.
- This page and [requests.json](requests.json), the sanitised manifest, are the tracked record.

## Documentation read

Read outside the collector, as in the [2026-09-24 map review](../mcp-stage-2/pvgis-map-evidence.md).
None of it is a PVGIS API request.
- The PVGIS 5 user manual.
- The API page.
- The PVGIS 5.3 release page.
- The data-download page, for the terms.
- The PVGIS 5.3 Dataset Update report: JRC139355, 3,141,949 bytes, SHA-256
  `29d6607f513dfcf5687d53496da8b01b9b47a0b6f6d09974e4351eec2d9200a0`, kept in
  `.local/mcp-availability/documentation-2026-10-13/`.

JRC's Data Catalogue record for the 5.3 rasters refused an automated read, and the browser
pane blocks that site. Neither was retried. The plan quotes the statements used.

## Requests

All six went through the collector (`collect --manifest`, one ID per run), under the owner's
2026-10-13 approval of P1 (decision D3).

| ID | Point | Outcome | Bytes | Result |
|---|---|---|---:|---|
| `pvgis-ithaca` | 42.44, −76.50 | saved, 200 | 1,269,086 | TMY; `radiation_db` `PVGIS-ERA5`, `meteo_db` `ERA5`, 2005–2023, irradiance time offset 0.5 h |
| `pvgis-atlantic` | 40.0, −40.0 | 400 | 82 | "Location over the sea. Please, select another location" |
| `pvgis-northsea` | 52.30, 4.20 | transport error after 0.37 s, no HTTP status | 0 | none; the exception is not persisted |
| `pvgis-svalbard` | 78.22, 15.65 | 400 | 82 | the same "over the sea" message, on land north of the grid |
| `pvgis-lake-victoria` | −1.0, 33.0 | saved, 200 | 1,268,097 | TMY; `PVGIS-SARAH3`, `ERA5`, 2005–2023, elevation 1,134 m |
| `pvgis-northsea-r1` | 52.30, 4.20 | 400 | 82 | "over the sea", about 19 km off Noordwijk |

**Collector change.** The P1 exception admits these exact IDs and one `-r1` revision at
`re.jrc.ec.europa.eu/api/v5_3/tmy`, with a cap of 7 PVGIS probes and 1.5 MB per request. For
them alone, a 4xx body of up to 16 KB is kept as `raw/<id>.error.body`. It is recorded as
`error_sha256` and `error_snapshot`, never as a snapshot the analysis reads. Error bodies of
other requests are still never stored.

**Totals.** Stage 1 ceilings after this work:
- metadata requests: 50 of 60;
- probes: 12 of 12, so none are left;
- bytes: 185.7 MB of 200 MB charged (14.3 MB left).

## Findings

- **ERA5 fallback.** Through `tmy`, ERA5 radiation is used outside the SARAH3 default area,
  with the same 2005–2023 period.
  - The response reports `radiation_db` and the irradiance time offset: 0.5 h for ERA5's
    hourly means, 0.18 h at London and 0.10 h at Lake Victoria for SARAH3.
  - The adapter already keeps both in `provider_inputs`. Its warning and lineage now name the
    radiation database of each run.
- **Open sea and polar land are refused** with the same 400 message.
- **The documented 25 km sea zone does not hold for `tmy` at the North Sea point.**
- **A large lake is served.** PVGIS's coastline comes from elevation data, so inland water is
  land to it.

## Decisions (owner, 2026-10-13)

- **D1.** PVGIS TMY 5.3 is one product, with SARAH3 or ERA5 radiation by location, recorded
  per run.
  - The choice label is "PVGIS TMY 5.3 · SARAH3/ERA5". The approved wording "SARAH3 or ERA5"
    breaks the existing rule that a choice label never contains " or ".
- **D2.** A domain mask from the ERA5-Land land–sea mask, with an explicit unknown band.
- **D3.** The P1 budget as listed.

**Two departures from the proposed D2 rule, both towards "unknown".**
- **Water not connected to the open ocean** is never outside. The rule excluded only
  ocean-connected water more than 50 km from land. Without this change, the middle of large
  lakes would have been excluded, which Lake Victoria contradicts. The approval intended
  lakes to be unknown.
- **Published station positions count as land** for the 50 km test: NOAA ISD sites, without
  placeholder (0, 0) positions, and every OneBuilding workbook row. Without them, the 50 km
  test excluded inhabited atolls that ERA5-Land does not resolve, such as Malé and Funafuti.
  - 100,730 positions from 13 inventories.
  - Offshore platforms among them only widen the unknown band.

## Mask

`scripts/mcp_availability_map/pvgis_mask.py`, on the 0.1° ERA5-Land grid by cell centre.

| Class | Rule | Points |
|---|---|---:|
| inside (`runs`) | land fraction ≥ 0.5, centre between 59.9° S and 74.9° N | 1,461,075 |
| unknown (`edge_runs`) | everything else | 367,808 |
| outside | ocean-connected water more than 50 km from any land fraction or station, or beyond 60.5° S / 75.5° N | 4,654,717 |

- The mask is 703,422 bytes, SHA-256 `78c3ecadd04d3a70…`.
- It gates `pvgis:PVGIS TMY`. `coverage.py` reads `edge_runs`: when every mask of a product
  lists one, the band replaces the one-cell neighbour rule.
- The builder refuses to write the mask unless every probe falls in its class:
  - London and Ithaca inside;
  - Lake Victoria and the North Sea unknown;
  - the Atlantic, Svalbard, Antarctica and the mid-Pacific outside;
  - Malé and Funafuti unknown.

**Further spot checks.**
- Unknown: Lake Superior, Lake Michigan, the Caspian, the Black Sea, Baikal, Ladoga, the Gulf
  of Bothnia, Titicaca, Malawi, the English Channel and Pitcairn.
- Outside: the Baltic, Mediterranean, Red Sea, Persian Gulf and Hudson Bay centres, and the
  central North Sea.
- Inside: Lake Geneva.

**Published station positions.**
- Inside 60° S–75° N: 28,601 inside, 5,951 unknown (17%), none outside.
- Beyond those latitudes: all 420 outside.

## Catalog

- **Importer:** one entry per saved probe, each with its own selected month-years, and a
  documented `pvgis:tmy:v5_3:documented-domain` entry. That entry covers 2005–2023, has no
  months and no probe location.
- **Evaluator:** for NSRDB and PVGIS, at a probe point the probe's own entries apply. Inside
  the mask the documented entry applies, and only without one do the probes' lists apply, as
  for NSRDB. Elsewhere it stays unknown. A probe's selected months never move to another
  point, and NSRDB's behaviour is unchanged.
- **Map:** the PVGIS layer draws the mask's inside area in 0.5° display cells (2,007
  rectangles, 12 KB gzipped) instead of the traced SARAH3 envelope, which stays the fallback
  without a mask.
- **Generation `d3940fbe`:** 51 sources, 73,403 products, 106,991 sites, 99,441 entries,
  61 reviews. Before: 49 / 73,403 / 106,991 / 99,438 / 61. Only PVGIS changed in the analysis.

**Availability matrix.** PVGIS TMY at 24 points, before with `main` (6a9f53d) on the previous
catalog, after with this branch and the mask:

| Before | After | Points |
|---|---|---|
| supported (probe) | supported (probe) | London |
| unknown | supported (`INSIDE_SOURCE_COVERAGE`) | Paris, Madrid, Cairo, Nairobi, Mumbai, Tokyo, Sydney, New York, Phoenix, Anchorage, Reykjavik, Ushuaia |
| unknown | supported (probe) | Ithaca, Lake Victoria |
| unknown | unknown (`NEAR_SOURCE_COVERAGE_EDGE`) | Cape Town, Singapore, Rio de Janeiro, Honolulu, Malé, North Sea |
| unknown | excluded (`OUTSIDE_SOURCE_COVERAGE`) | Atlantic, Svalbard, McMurdo |

- The option counts of every other product are unchanged at these points, for typical-year
  and 2018 queries.
- PVGIS options went from 1 supported, 23 unknown and 24 excluded to 15 supported, 6 unknown
  and 27 excluded. The 2018 queries exclude the typical-year product by kind.
- `SOURCE_CHECK_DUE` remains, because the London probe and `pvgis-doc` date from 2026-09-23.

## Package 2026.10.13.1

- Exported to the open-data checkout, branch `data/weather-availability-catalog-2026.10.13.1`,
  commit `b606e1e`, with the published 2026.10.13 descriptor metadata.
- 39 files, 88.1 MB; `datapackage.json` SHA-256
  `9ac15ee7bac1c1ed5345fee8f6235a4a7f9dcc2be7f9df61c11f3ac3cbbd3ecc`.
- The export is lossless: importing it gives identical records of every type, and the 12
  footprint files are byte-identical.
- Each of the 39 committed blobs matches its size and SHA-256.
- Pushing to Energy-Atlas/open-data waits for the owner's confirmation. Staging is then
  pinned to the commit URL and this SHA-256.

## Checks

- ruff and mypy are clean.
- pytest: 1,054 passed, 20 skipped, 2 failed.
  - The 2 failures are in `tests/agent/test_policy_config.py`: security profiles, with no
    `OPENAI_API_KEY` set.
  - Both also fail on a clean `main` (6a9f53d), so this work did not cause them.

## What this does not establish

- That every inside point returns a TMY. The mask is documentation plus six requests.
- PVGIS's own coastline, sea zone or lake handling at any unprobed point.
- Which radiation database serves a point before it is requested. The run records it.
- The EPW timing of ERA5-sourced TMY. PVGIS's native EPW is used as published. The reported
  irradiance offset is kept, and no transform is applied.

# Items 3 and 4: NSRDB years and the ERA5-Land mask

Under owner decisions D4–D6 (2026-10-13) in the [plan](../../superpowers/plans/2026-10-13-availability-gaps.md).

## Requests

**Collector (`collect --manifest`, appended to [requests.json](requests.json)).** All 19 were
saved.

| Group | IDs | Bytes |
|---|---|---:|
| N3, NLR dataset pages | `nsrdb-doc-*`: GOES aggregated and TMY, Himawari-7, Himawari TMY, Meteosat and its TMY/TDY/TGY, IODC (`meteosat-download`) | 306,300 |
| N1, edge probes (`DEMO_KEY`) | `nsrdb-honolulu`, `-recife`, `-juneau`, `-buenos-aires`, `-cape-town`, `-oslo`, `-dakar`, `-auckland`, `-sapporo`, `-almaty` | 152,510 |

- A first run of N3 sent nothing: the collector rejected upper-case IDs, and the IDs were
  lower-cased.

**Ceilings after this work:**
- metadata requests: 59 of 60;
- probes: 22 of 23, the ceiling raised for N1 only;
- bytes: 186.2 MB of 200 MB charged.

**Outside the collector.** The key comes from `.env` and never enters a log or file. The logs
record host and path only.

- **N2, earliest-year downloads.** Four hourly CSVs with the nine EPW attributes.
  - The first attempt of each returned NLR's 302 to its file store, which the script did not
    follow: about 600 bytes, no data.
  - One revision each followed HTTPS redirects only.

| Dataset, year | Point | Bytes | Rows | Fill values | GHI max (W/m²) |
|---|---|---:|---:|---:|---:|
| GOES aggregated 1998 | Juneau | 585,157 | 8,760 | 0 | 863 |
| GOES aggregated 1998 | Honolulu | 601,773 | 8,760 | 0 | 1,043 |
| Meteosat 2005 | Oslo | 590,052 | 8,760 | 0 | 833 |
| Himawari-7 2011 | Auckland | 597,539 | 8,760 | 0 | 1,102 |

- **C1, one ERA5-Land field.**
  - Requests: 1 submit, 4 status polls, 1 results lookup and 1 download from
    `object-store.os-api.cci2.ecmwf.int`.
  - The download is 5,236,290 bytes, SHA-256 `b1c2c41d5157b3b0…`: GRIB edition 1, 3600 × 1801
    at 0.1°, with a bit map.

## Findings

**Every probe lists the same years and files per dataset**, at the edges and at the five
earlier points:

| Dataset | Years or files |
|---|---|
| GOES aggregated v4 | 1998–2025 |
| GOES TMY v4 | `tmy`, `tdy` and `tgy` with `-2022` to `-2025` |
| Himawari-7 | 2011–2015 |
| Himawari TMY | `tmy` and `-2020` |
| Meteosat | 2005–2022 |
| Meteosat TMY/TDY/TGY | `-2014` and `-2022` |
| IODC | 2017–2019 |

- **NLR's pages agree, except one lag.** The GOES TMY page omits the `-2025` files.
  - The Meteosat page's prose says "2017–2019", but its `names` list is 2005–2022.
- **The GOES gate is right at Buenos Aires.** Just south of the GOES mask (21° S), only GOES
  full disc is listed, which is not downloaded. GOES aggregated and TMY do not reach there.
- **Oslo lists NSRDB Polar** (2013–2023) and Polar TMY, which are now catalogued as upstream
  products.
- **Earliest years hold full data at every edge tried.**
  - One quality note: Meteosat 2005 wind speed at Oslo never exceeds 1.3 m/s, which looks
    implausible.

**The ERA5-Land field has 2,212,863 points with values.**
- 2 m temperatures range from 224.7 to 313.9 K.
- Compared with the land-fraction mask (≥ 0.5):
  - 24,726 points with values have a lower fraction (lakes and coasts), and 6,737 of them
    have a fraction of 0;
  - 7,105 points of fraction ≥ 0.5 have no value, mostly Arctic, fjord and Patagonian coasts.

## Catalog

- **Importer.** For each adapted NSRDB dataset where every probe agrees and the page lists
  nothing more, it adds an area-wide documented entry (`…:documented:…`). Nine datasets
  qualify.
  - The probes' list is used, so GOES TMY keeps its `-2025` files.
- **ERA5-Land mask.** `scripts/mcp_availability_map/era5land_present.py` (GRIB 1, bit map)
  writes `cds/reanalysis-era5-land/present-t2m`. The `lsm` mask is retired from the data root
  and the package, and stays in the research root.
- **Generation `b17c5cf4`:** 70 sources, 73,405 products (the two Polar products added),
  106,991 sites, 99,583 entries, 61 reviews.

**Matrix.** 18 points, against package 2026.10.13.1 imported into an empty root:
- ERA5-Land (CDS and Open-Meteo): Lake Victoria, Lake Superior and the Caspian move from
  excluded to supported, and the open Atlantic stays excluded.
- NSRDB statuses are unchanged at these points. Unprobed points inside a mask are now
  supported on documentation (for example Denver for 2018 and for `tmy-2025`, and Madrid for
  2005) rather than on the probes' lists.
- The new Polar products are excluded everywhere: the adapter does not download them.

## Package 2026.10.13.2

- Local open-data branch `data/weather-availability-catalog-2026.10.13.2`, commit `958907a`.
- 39 files, 88.2 MB; `datapackage.json` SHA-256
  `e46dace1892aacce26c7d3173ad0514dcc7618e22ecc9b92f4f6e8103cf3fcd5`.
- The export is lossless: identical records, and the 12 footprint files are byte-identical.
- Every committed blob matches its size and SHA-256, and no source URL carries a query string.
- The push waits for the owner.

## Checks

- ruff and mypy are clean.
- pytest: 1,059 passed, 20 skipped, 2 failed. The failures are the security-profile tests,
  which also fail on `main`.

## What this does not establish

- That every NSRDB grid site has every listed year: 15 probes and 4 downloads are checks, not
  a census.
- Hourly completeness or quality beyond the four downloads.
- That Open-Meteo's ERA5-Land covers exactly CDS's points. It is gated by the same mask.
