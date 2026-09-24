# MCP Stage 1 — availability findings

Investigated 2026-09-23–24 on `feature/mcp`. Stage 1 research is complete with the
specific unresolved items below. This is availability evidence, not weather-data
acceptance, QC certification or a production MCP release.

The owner accepted Stage 1 as finished on 2026-09-24 and authorized progression
to Stage 2 design/planning. Continue from the
[agent handoff](../../handoffs/2026-09-24-mcp-stage-2.md); remaining documented
unknowns are Stage 2 inputs, not reasons to restart this investigation.

Artifacts: [sanitized evidence and ledger](evidence.json),
[executed follow-up requests](requests.json), [source register](sources.md),
[Stage 2 catalog contract](catalog-contract.md),
[research tool instructions](../../../scripts/mcp_research/README.md), and
[execution plan/ledger](../../superpowers/plans/2026-09-23-mcp-stage-1.md).

## Actual network work

| Budget | Used | Ceiling | Remaining |
| --- | ---: | ---: | ---: |
| Documentation/inventory/metadata HTTP attempts | 41 | 60 | 19 |
| Location-specific API probes | 3 | 12 | 9 |
| Application response bytes, including aborted reads | 140,069,725 | 200,000,000 | 59,930,275 |
| OneBuilding pages/inventory requests | 15 | 15 | 0 |
| CMIP6 selected Zarr metadata documents | 4 | 4 | 0 |
| OEDI RCP4.5 directory-related bytes | 11,816,413 | 17,000,000 | 5,183,587 |
| OEDI RCP8.5 directory-related bytes | 11,816,677 | 17,000,000 | 5,183,323 |

Calls were serial. Three responses were aborted at the original collector's byte
limits and three oversized KMLs were rejected before body download; 38 successful
responses were retained locally. OEDI allowances include the owner's additional
7 MB per archive, with all original charges retained. No automatic retries,
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
| OneBuilding published EPW/TMYx | Published spreadsheets supply exact-product coordinates for selected U.S./U.K. products; corroborated NOAA identifiers supply additional candidate coordinates including Australia | U.S./U.K./Australia catalogs list TMYx 2004–2018, 2007–2021, 2009–2023 and 2011–2025 variants, plus products without those suffixes | Local candidate mapping is possible for the matched subset. Preserve index versus inferred station evidence, unresolved products and unverified EPW coordinates |
| NOAA ISD | 28,474 station records with usable coordinates and stable USAF/WBAN IDs | Operating intervals range across the inventory from 1901-01-01 to 2025-08-28; individual station ranges vary | A locally indexed history file can resolve station candidates. It cannot prove continuous hours or current-year support. GHCNh is not this adapter |
| NSRDB aggregate v4 | Ithaca and Phoenix location catalogs both list the aggregate product; these are point observations, not a coverage polygon | Both list actual years 1998–2025 and upstream 30/60-minute intervals | Current adapter uses hourly aggregate only. Keep these tested-point results distinct from documented regional extent and unknown points |
| NSRDB published v4 | Both point catalogs list the published product | TMY/TDY/TGY identifiers and 2022–2025 suffix variants; hourly interval | Product labels are not calendar-year coverage. Weather retrieval requires runtime key/email; public DEMO_KEY catalog access does not establish download eligibility |
| Direct CDS ERA5 | Collection calls itself global; its machine-readable bbox is [0,-89,360,89] | Catalog interval starts 1940-01-01 and ends 2026-09-17; request schema offers 1940–2026 | Preserve 0–360 longitude encoding and the discrepancy between global wording and bbox; don't silently exclude polar requests or promise all of 2026 |
| Direct CDS ERA5-Land | Global land product; same returned bbox, not a land mask | Catalog interval starts 1950-01-01 and ends 2026-09-17; schema offers 1950–2026 | Land/ocean eligibility requires a suitable mask or explicit uncertainty. Current direct adapter supplies GHI but no DNI/DHI |
| Pangeo CMIP6 monthly morph inputs | Catalog separates model/member/grid stores; four ACCESS-CM2 metadata samples describe a coarse native atmosphere grid | 636 coherent historical/scenario seven-variable combinations across 28 models; actual coordinate periods remain unverified | Catalog can eliminate absent variable combinations locally. It cannot certify climate-window coverage or numeric completeness without additional bounded metadata/data work |
| OEDI WRF/CCSM4 | Published PUMA table contains 2,368 sites; both scenario directories match all site IDs | Each scenario lists all 20 years in 2045–2054 and 2085–2094 for every site; baseline 1995–2004 remains documentation-only | Local scenario/site/year membership is now established. No EPW content or baseline archive was fetched; weather quality remains unverified |

## Inventory results and consequential distinctions

**NOAA:** the returned station-history file has a Last-Modified date of
2025-08-30. Its newest station end date is 2025-08-28. This is a dated historical
inventory, not evidence that stations stopped operating. The first station/month
inventory attempt exceeded the 5 MB cap. The owner subsequently authorized further
NOAA investigation; one revised request with a narrowly scoped 20 MB allowance
retrieved the full **14,969,485-byte** file. The prior failed transfer remains charged
and the 200 MB total ceiling is unchanged.

The count inventory contains **154,841 station/year rows for 16,513 station IDs**,
with listed years ranging from **1930 to 2025**. Preserve sparse listed years; do
not expand the range into assumed availability. There are 129,601 zero-report
months across those rows. IDs include alphanumeric USAF codes such as `A00002`;
the parser preserves them and leading zeroes. Conflicting duplicate station/year
rows fail analysis instead of being silently overwritten.

Of those station IDs, **15,479** join to the downloaded history's coordinate-bearing
records; **1,034** do not. Those unmatched IDs remain unresolved geographically,
not assigned guessed coordinates. The inventory has 13,345 listed station/year
rows for 2024 and 12,815 for 2025; the source Last-Modified is 2025-08-30, so this
does not establish present-day availability.

The four stations in the local batch example all have 2024 inventory entries.
For example, Ithaca has 1,060 January reports, while London has 744 January and
694 February reports. Counts can exceed or fall below the number of hours; neither
comparison is a completeness/QC test. The full local station/year/month index can
screen candidate periods without weather API calls, but counts do not establish
distinct valid hours or variable availability. Published evidence contains summaries
and selected examples; the full index and raw inventory stay local.

**OneBuilding:** the selected catalogs contained 16,470 U.S., 1,451 U.K., and 3,732
Australia ZIP links. These are product counts, not distinct sites. Identifiers retain leading zeros.
The NOAA snapshot contains ambiguous country-code conventions: `AU` is not globally
reinterpreted as Australia. The Australian published product index now independently
resolves its product positions. Short names such as Hay require exact distinctive
name agreement after generic facility terms are removed; aliases are not guessed.

NOAA candidates sharing exactly the same latitude/longitude can establish a
horizontal position while retaining distinct WBAN identities. No rounding or
averaging is used. Two final products use this evidence: Denver–Stapleton older TMY
(elevation remains unknown) and Port Allen TMYx. Elevation is retained only if all
candidates supply the same finite value. Published indexes similarly retain an
agreed horizontal position when elevation differs or is missing, with uncertainty
explicitly flagged. No arbitrary station ID is chosen for a consensus position.

Published exact-product positions remain preferred, with all competing evidence
retained. Numerical NOAA/index disagreements affect 13,352 U.S., 542 U.K. and 1,927
Australian products; the exact-value comparison includes rounding and elevation
differences and is not a count of bad matches. Conflicting horizontal points remain
unknown. None of these methods verifies native coordinates in an EPW header or
establishes weather equivalence for batch deduplication.

Approximate place geocoding remains a fallback for unresolved products, not a
completed feature: source-published coordinates provided stronger evidence within
the budget. No town-centre points were fabricated. Full spreadsheets and local
joins remain ignored; the source copyright notice does not grant a blanket right
to redistribute these indexes. Production shipping/reuse terms still need review.

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
was retained. The bug was fixed with a synthetic regression test. The owner then
approved another 7 MB per archive, increasing each cumulative allowance to 17 MB
while retaining the overall 200 MB ceiling and all original charges.

One revised Range request per archive succeeded with the saved If-Match version.
Each directory contains 47,360 EPW filenames plus one directory entry. All 2,368
sites match the published PUMA IDs, and every site lists all 20 expected years in
the two windows for its scenario. There are no duplicate filenames, unparsed EPW
names, unexpected scenarios or unmatched site IDs. This resolves filename
membership, not weather validity or variable completeness. No baseline or EPW
member was read. Retain the source's late-century RCP4.5 Great Plains warming warning.

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

The full offline suite after the follow-ups passed: **165 passed, 14 opt-in live tests skipped**, with
two dependency deprecation warnings from FastAPI/Starlette. The research module
now has **64 offline safeguard/parser tests**. The NOAA follow-up adds five
regressions for the scoped allowance, sparse month counts, conflicting rows,
alphanumeric station IDs and nonzero CLI status on analysis failures. Focused Ruff
checks pass. Follow-up tests cover scoped OEDI resume, conservative
coordinate matches, conflicting evidence, workbook validation and incomplete directory
membership, conservative short names, country ambiguity, coordinate/elevation
consensus, exact product URLs, budget extensions and offline before/after accounting. Independent
read-only review findings on deadlines, headers and byte limits were reproduced
as failing tests and fixed. No production files or public interfaces changed.

Every connected source now has a documented catalog strategy or precise unknown.
NOAA count and OEDI scenario-member inventories are now resolved. Remaining
OneBuilding product coordinates/reuse terms, general NSRDB/PVGIS footprint details
and CMIP6 window validation are explicit
Stage 2 inputs, not hidden availability claims. Previous-run/QC reuse remains a
future advanced feature.

The local `coordinate-baseline.json` preserves the earlier matcher output and
source checksums. Repeated offline analysis produces identical evidence bytes and
unchanged network charges. It is a research metadata baseline, not prior weather/QC
reuse. The published report contains only aggregate transitions and bounded
examples. Minor deferred reporting enhancement: primary unresolved reasons are
classified; lists of independently applicable secondary reasons are not yet
exhaustive. Full raw candidate evidence remains available locally.

An [individual case review](onebuilding-manual-review.md) subsequently found that all 56 Hawaiian unknown products have exact filenames in published indexes under a different WMO region directory. The owner accepted these judgments. Research annotations now record **56 reviewed metadata matches, three approximate localities and two name/code conflicts**, separately from the unchanged automated counts above. They are pinned to the evidence snapshots and remain unverified against EPW contents.
