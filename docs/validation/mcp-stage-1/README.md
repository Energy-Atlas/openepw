# MCP Stage 1 — availability findings

Investigated 2026-09-23 on `feature/mcp`. Stage 1 research is complete with the
specific unresolved items below. This is availability evidence, not weather-data
acceptance, QC certification or a production MCP release.

Artifacts: [sanitized evidence and ledger](evidence.json),
[executed follow-up requests](requests.json), [source register](sources.md),
[Stage 2 catalog contract](catalog-contract.md),
[research tool instructions](../../../scripts/mcp_research/README.md), and
[execution plan/ledger](../../superpowers/plans/2026-09-23-mcp-stage-1.md).

## Actual network work

| Budget | Used | Ceiling | Remaining |
| --- | ---: | ---: | ---: |
| Documentation/inventory/metadata HTTP attempts | 30 | 60 | 30 |
| Location-specific API probes | 3 | 12 | 9 |
| Application response bytes, including aborted reads | 106,760,281 | 200,000,000 | 93,239,719 |
| OneBuilding pages | 7 | 12 | 5 |
| CMIP6 selected Zarr metadata documents | 4 | 4 | 0 |
| OEDI RCP4.5 directory-related bytes | 5,075,668 | 10,000,000 | 4,924,332 |
| OEDI RCP8.5 directory-related bytes | 5,075,668 | 10,000,000 | 4,924,332 |

Calls were serial. Three responses were aborted at the original collector's byte
limits; 30 successful responses were retained locally. No automatic retries,
credentialed calls, queued CDS retrievals, station weather downloads, climate
variable chunks, archive members or exhaustive location/year sweeps were used.

The three probes were NSRDB location catalogs for Ithaca and Phoenix, and one
PVGIS v5_3 TMY JSON for London. The latter necessarily returned 8,760 hourly rows;
only its source/location/selected-month metadata was analyzed and published. No
second EPW was downloaded and no QC acceptance is claimed from that response.
Unused probe capacity was deliberately left unused. No previous weather run or
QC summary was consulted as availability evidence.

## Availability matrix

All findings below describe a particular evidence snapshot. Global/domain
documentation, an inventory entry and a successful probe are different evidence
bases; none is a guarantee of complete hourly weather for another request.

| Dataset/access route | Geographic evidence | Temporal evidence | Implication for local discovery |
| --- | --- | --- | --- |
| Open-Meteo ERA5 | Documented global 0.25-degree grid; returned locations/elevation can differ from requested points | Documented hourly history from 1940 with a delayed moving end | Rule out clearly incompatible product/year requests locally. Latest date and exact resolved cell still require fresher metadata/retrieval |
| Open-Meteo ERA5-Land | Documented 0.1-degree land reanalysis; statistical elevation adjustment is an API option | Documented history from 1950 | Current OpenEPW adapter exposes temperature, dew point, RH and pressure only. Do not infer wind/solar support from the wider API's variable list |
| PVGIS TMY v5_3 | Documentation distinguishes radiation databases; London probe uses SARAH3 solar and ERA5 meteorology | London default reference period is 2005–2023; 12 selected source-month years differ | This is a TMY reference period, not actual-year availability. London metadata must not be generalized into a worldwide database footprint or universal period |
| OneBuilding published EPW/TMYx | Country/region catalogs expose named product paths. Selected pages do not expose coordinates | U.S./U.K./Australia catalogs list TMYx 2004–2018, 2007–2021, 2009–2023 and 2011–2025 variants, plus products without those suffixes | Product discovery can be local. Nearest-station discovery needs a separately validated coordinate index; do not invent coordinates from names |
| NOAA ISD | 28,474 station records with usable coordinates and stable USAF/WBAN IDs | Operating intervals range across the inventory from 1901-01-01 to 2025-08-28; individual station ranges vary | A locally indexed history file can resolve station candidates. It cannot prove continuous hours or current-year support. GHCNh is not this adapter |
| NSRDB aggregate v4 | Ithaca and Phoenix location catalogs both list the aggregate product; these are point observations, not a coverage polygon | Both list actual years 1998–2025 and upstream 30/60-minute intervals | Current adapter uses hourly aggregate only. Keep these tested-point results distinct from documented regional extent and unknown points |
| NSRDB published v4 | Both point catalogs list the published product | TMY/TDY/TGY identifiers and 2022–2025 suffix variants; hourly interval | Product labels are not calendar-year coverage. Weather retrieval requires runtime key/email; public DEMO_KEY catalog access does not establish download eligibility |
| Direct CDS ERA5 | Collection calls itself global; its machine-readable bbox is [0,-89,360,89] | Catalog interval starts 1940-01-01 and ends 2026-09-17; request schema offers 1940–2026 | Preserve 0–360 longitude encoding and the discrepancy between global wording and bbox; don't silently exclude polar requests or promise all of 2026 |
| Direct CDS ERA5-Land | Global land product; same returned bbox, not a land mask | Catalog interval starts 1950-01-01 and ends 2026-09-17; schema offers 1950–2026 | Land/ocean eligibility requires a suitable mask or explicit uncertainty. Current direct adapter supplies GHI but no DNI/DHI |
| Pangeo CMIP6 monthly morph inputs | Catalog separates model/member/grid stores; four ACCESS-CM2 metadata samples describe a coarse native atmosphere grid | 636 coherent historical/scenario seven-variable combinations across 28 models; actual coordinate periods remain unverified | Catalog can eliminate absent variable combinations locally. It cannot certify climate-window coverage or numeric completeness without additional bounded metadata/data work |
| OEDI WRF/CCSM4 | Published PUMA table contains 2,368 sites; source describes U.S. PUMA delivery excluding Hawaii, distinct from the broader model domain | Documentation specifies RCP4.5/8.5, 2045–2054 and 2085–2094; paired baseline 1995–2004 | Use table locations and exact documented windows. Archive tails were verified, but full site/year membership remains unresolved in this run |

## Inventory results and consequential distinctions

**NOAA:** the returned station-history file has a Last-Modified date of
2025-08-30. Its newest station end date is 2025-08-28. This is a dated historical
inventory, not evidence that stations stopped operating. The station/month count
inventory exceeded the 5 MB cap and was discarded without retry. Even if acquired
later, report counts are not unique valid hourly intervals or variable completeness.

**OneBuilding:** the selected catalogs contained 16,470 U.S., 1,451 U.K., and 3,732
Australia ZIP links. These are product counts, not unique station counts. Australia
also has a separately linked RMY catalog, which was deliberately not crawled.
The bounded root/region/country traversal remained within two levels for Australia
and the U.K.; the existing U.S. country entry point was read directly. No weather
ZIP or guessed station coordinate was used. Redistribution of raw catalogs/weather
is not asserted; full normalized product links stay local.

**CMIP6:** the downloaded Pangeo catalog's Last-Modified date is 2022-06-28.
The coherent combination counts are SSP126: 138, SSP245: 170, SSP370: 151,
SSP585: 177. They describe this catalog snapshot, not all CMIP6 data now available.
The intersection preserves model, member and grid and requires historical plus
scenario entries for tas/tasmin/tasmax/hurs/ps/sfcWind/rsds. License filtering is a
separate eligibility step: the 636 combinations are not all declared usable.

Four metadata documents sampled ACCESS-CM2 r1i1p1f1 historical/SSP245 tas and rsds.
Time-array shape and units were retained, but no coordinate chunks or weather
chunks were fetched, so complete reference/target windows remain unknown. Original
store text says CC BY-SA 4.0; the WCRP registry records relaxation to CC BY 4.0 on
2022-06-10. Preserve both records and their dates rather than overwrite provenance.

**OEDI:** each ZIP64 tail declares 47,361 directory entries, with central-directory
sizes 6,740,745 and 6,741,009 bytes. These counts do not identify which site/year
members exist. An initial collector bug applied the ordinary 5 MB limit to both
directory reads. Both reads stopped; no successful directory snapshot or EPW member
was retained. The bug is fixed with a synthetic regression test, but complete
retries would exceed the remaining approved per-archive budgets. Membership remains
unknown until a separately budgeted investigation. Do not classify the provider as
unavailable or infer membership from the declared count. Retain the source's
late-century RCP4.5 Great Plains warming warning.

The initial byte-limit checks observed the chunk that crossed their cap. The ledger
retains those actual counts rather than rewriting evidence. The final collector
rejects declared oversize responses early and stops application-byte consumption
at the allowance. OS/TLS/HTTP buffering is not measured as wire traffic.

## Local batch demonstration

Inventory-only resolution for 2024-01-01, using the existing 100 km NOAA search
radius, produced the following mapping without weather requests:

| Input occurrence | Requested site | Inventory station | Distance |
| --- | --- | --- | ---: |
| 0 | Ithaca | 72515594761 | 5.495 km |
| 1 | Ithaca, repeated input | 72515594761 | 5.495 km |
| 2 | Phoenix | 72278023183 | 6.595 km |
| 3 | London | 03770099999 | 1.089 km |
| 4 | Sydney | 94769099999 | 2.238 km |

Five requested occurrences remain visible and refer to four unique station IDs.
This demonstrates mapping, not a production recommendation or guaranteed weather
equivalence. No output files were generated. Future grouping must include period,
variables, adjustments and output semantics, not station ID alone. Elevation is
preserved where supplied, but this example does not apply an elevation suitability
threshold or substitute for later study-purpose ranking.

## Verification and conclusion

The full offline suite passed: **123 passed, 14 opt-in live tests skipped**, with
two dependency deprecation warnings from FastAPI/Starlette. The research module
has **22 offline safeguard/parser tests**. Focused Ruff checks pass. Independent
read-only review findings on deadlines, headers and byte limits were reproduced
as failing tests and fixed. No production files or public interfaces changed.

Every connected source now has a documented catalog strategy or precise unknown.
The unresolved NOAA count inventory, OneBuilding coordinate index, general NSRDB/
PVGIS footprint details, CMIP6 window validation and OEDI membership are explicit
Stage 2 inputs, not hidden availability claims. Previous-run/QC reuse remains a
future advanced feature.
