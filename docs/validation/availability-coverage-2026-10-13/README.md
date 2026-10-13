# Availability coverage, 2026-10-13: evidence, checks and limits

The record of the [2026-10-13 plan](../../superpowers/plans/2026-10-13-availability-coverage.md),
in the format of the [Stage 1 findings](../mcp-stage-1/README.md).
- Raw responses, the ledger and the analysis stay local, under `.local/mcp-availability/`.
- This page and [requests.json](requests.json), the sanitised manifest, are the tracked record.

## Requests

All research requests went through the collector and its ledger, except where noted.

**Collector (`scripts/probe_mcp_availability.py collect`):**

| ID | Kind | Outcome | Bytes | SHA-256 (prefix) |
|---|---|---|---:|---|
| `onebuilding-region1-xlsx` | inventory | saved | 689,278 | `5ba085f6cd58fa99` |
| `onebuilding-region2-xlsx` | inventory | saved | 1,448,838 | `55f9b568d53afea6` |
| `onebuilding-region2-6-russia-xlsx` | inventory | saved | 671,129 | `b5b362c988e340f5` |
| `onebuilding-region3-xlsx` | inventory | saved | 567,633 | `47124ed655b2f329` |
| `onebuilding-region4-canada-xlsx` | inventory | saved | 507,201 | `b9aeb3a4485a0d41` |
| `onebuilding-region4-caribbean-xlsx` | inventory | saved | 251,585 | `363f697260022064` |
| `onebuilding-region7-xlsx` | inventory | saved | 60,654 | `acae6b01512d7f9c` |
| `nsrdb-singapore` | probe | saved | 8,971 | `12b91a27cd34ed31` |
| `nsrdb-nairobi` | probe | refused by the collector (`provider_limit`), not sent | 0 | |
| `nsrdb-london` | probe | refused by the collector (`provider_limit`), not sent | 0 | |
| `era5land-lsm` | inventory | `sensitive_response`, body discarded | 19,451,040 charged | |
| `nsrdb-nairobi-r1` | probe, revision | saved | 16,367 | `2a2c8e76d5caba31` |
| `nsrdb-london-r1` | probe, revision | saved | 16,367 | `29b0cbf86a8b1619` |
| `era5land-lsm-r1` | inventory, revision | saved | 19,451,040 | `4a790339465a8482` |

**Corrections.**
- The Nairobi and London probes were refused, without being sent, by a second copy of the Stage 1
  NSRDB probe cap inside the collector's fetch step. It is now the same exception as the first check.
- The first mask request carried Confluence's `version`, `modificationDate` and `api` query values.
  The collector treats unknown query values as possible secrets, found the short strings by chance
  in the binary body, and discarded it. The revision requested the same file without the query.
- Both corrections used the one allowed revision, with `revision_of` and `correction`.

**Totals.** Stage 1 ceilings after this work:
- metadata requests: 50 of 60;
- probes: 6 of 12;
- bytes: 183.2 MB of 200 MB charged (16.8 MB left). The discarded mask transfer counts.

**Outside the collector:**
- **2 HEAD requests** to `confluence.ecmwf.int`, for the sizes of the ERA5-Land mask files: netCDF
  51,898,361 bytes, GRIB 19,451,040 bytes. They were made before the download, to choose the
  file within the 50 MB cap.
- **E3, S3 listing:** 5 anonymous ListObjectsV2 requests to `nrel-pds-nsrdb` (cap 6), logged locally.
  - One was wasted: the shell rewrote the prefix `/` into a Windows path, so it listed a
    non-existent prefix.
  - The others listed the root and the `himawari/`, `meteosat/` and `msg/` prefixes in full,
    none truncated.
- **E3, Himawari grid table — cap exceeded.**
  - The plan allows 12 requests per product. The `himawari_tmy-2020.h5` acquisition used about 20
    and about 64 MiB:
    - one failed acquisition (up to 12 requests; the script did not record the count on failure);
    - two layout diagnostics (4 + 4 requests, 1 MiB and 16 MiB blocks).
  - The cause is that this file's `meta` table is chunked and its HDF5 metadata is not reachable
    within the cap, unlike the GOES file's contiguous table.
  - All E3 reads stopped and the overrun was reported.
- **E3 after the owner raised the caps.**
  - Caps: 80 range requests per product. Bytes: 300 MB, raised further to 400 MB for Meteosat
    and 550 MB for IODC.
  - Himawari's earlier use counts against its share.
  - Each acquisition first inspected the table's layout with small cached header blocks, then read
    its rows as a few contiguous spans. Every request was logged.

| Grid (file) | Rows | Table | Requests (inspection + read) | Bytes | Probe check |
|---|---:|---:|---:|---:|---|
| Himawari-7 (`himawari7_irradiance_2015.h5`) | 2,170,782 | 260 MB, 130 chunks in 3 spans | 5 + 8 | 262 MB | Singapore within 8 km |
| Himawari TMY (`himawari_tmy-2020.h5`) | 2,170,782 | same layout | about 20 (overrun) + 6 + 11 | about 78 MB | grid identity, below |
| Meteosat (`msg_tmy-2022.h5`) | 2,693,287 | 361 MB, contiguous | 3 + 5 | 362 MB | Nairobi, London |
| Meteosat IODC (`meteosat_irradiance_2018.h5`) | 3,869,544 | 515 MB, 248 chunks in 5 spans | 8 + 13 | 518 MB | Singapore, Nairobi, London |

  - The Himawari TMY table was not read whole. It has Himawari-7's exact layout, and five chunks
    spread over it (rows 0, 537,792, 1,092,390, 1,630,182 and 2,167,974) are byte-identical to
    the Himawari-7 table. So the Himawari-7 mask gates both products.
  - The masks are 0.25° cells of grid sites, as for GOES:
    - Himawari: 59,365 cells.
    - Meteosat: 70,892 cells.
    - IODC: 101,547 cells.
  - The raw coordinate tables stay local; only the masks are published.
- **E5, live acceptance:** 6 hourly downloads with the configured NLR key, one per dataset. The raw
  CSVs stay local.

## Findings

**OneBuilding.**
- The ten TMYx regional workbooks (three held since Stage 1, seven new) list 69,632 TMYx files,
  every row with published coordinates. Five rows of the Caribbean workbook are invalid and left out.
- 18,538 of the files were already catalogued from the country index pages. The other 51,094 are
  new products, each with its workbook coordinates (`published_product_index`).
- None is unresolved.
- 74 differ from NOAA's position for the same station. As in Stage 1, the single published
  workbook coordinate is used.
- The 3,115 files only the index pages list keep their Stage 1 import.
- The 61 owner reviews are unchanged.

**NSRDB data query.**
- Singapore: `himawari` 2016–2020, `himawari7` 2011–2015, `himawari-tmy` (`tmy-2020`, `tdy-2020`,
  `tgy-2020`), `msg-iodc` 2017–2019.
- Nairobi and London: `msg-iodc` 2017–2019, `nsrdb-msg-v1-0-0` 2005–2022, and its `-tmy`, `-tdy`
  and `-tgy` products (`*-2022`).
- No GOES dataset at any of the three.

**NSRDB live acceptance (E5).**
- Each dataset returned a full hourly year (8,760 rows) with the nine EPW fields. NLR's endpoint
  pages do not say where in its interval an hourly value is labelled.
- The check: the GHI-weighted mean of the labels' offset from solar noon over the year. Centre
  labels give about 0 minutes; start labels about −30 minutes.

| Dataset | Labels | Offset from solar noon | Decision |
|---|---|---:|---|
| `himawari7` 2015, Singapore | :30 | −5.2 min | supported (centre) |
| `himawari-tmy` `tmy-2020`, Singapore | :30 | −4.4 min | supported |
| `nsrdb-msg-v1-0-0` 2018, London | :30 | +1.9 min | supported |
| `nsrdb-msg-v1-0-0-tmy` `tmy-2022`, London | :30 | +13.6 min (months of different years) | supported |
| `msg-iodc` 2018, Nairobi | :30 | +3.9 min | supported |
| `himawari` 2018, Singapore | **:00** | −5.6 min | **not supported** |

- Himawari-8's hourly values are centred on the hour. Their intervals run from :30 to :30 and cannot
  become EPW's hour-ending rows without a temporal transform, which ADR 0002 defers.
- It stays catalogued as an upstream dataset the adapter does not download.

**ERA5-Land land–sea mask (E4).**
- ECMWF's published GRIB 2 file holds one field: land fraction 0–1 on a 0.1° grid of 3600 × 1801
  points.
- It was decoded without a GRIB library and checked against land and sea points.
- Land is a fraction of at least 0.5: 2,195,242 points. The mask is stored as row runs, 273 KB.
- Limits:
  - ERA5-Land masks the oceans but has values over lakes and at some coastal points with a smaller
    land fraction.
  - The coverage edge rule leaves coasts and lake shores unknown.
  - Open water away from land, including the middle of large lakes, is excluded.

**ERA5 (CDS).** Copernicus's catalogue record (1940 to 2026-09-17) now counts as documented coverage.
- A year the dated end cuts short stays unknown.
- When the evidence is old, the newest year stays unknown.

## Catalog and package

- Generation: 49 sources, 73,403 products, 106,991 sites, 99,438 entries, 61 reviews. Before:
  38 / 22,301 / 55,897 / 48,315 / 61.
- Package 2026.10.13: 38 files, 87.5 MB, the largest `onebuilding/products.csv` at 31.2 MB.
- Export, then import, is lossless: every record type is identical, and the 10 footprint files are
  byte-identical.

## What this does not establish

- Weather completeness, EPW quality, or that every OneBuilding file downloads.
- That a point inside a grid's mask has data for every year: years still come from the probes.
- Lake and coastal ERA5-Land coverage.
