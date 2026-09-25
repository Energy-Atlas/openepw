# Provider implementation status — v0.1

## MCP Stage 2 availability layer — 2026-09-24

The local catalog imports the accepted Stage 1 metadata once through explicit
`openepw catalog import --from <snapshot-root>`. It keeps source checksums,
evidence dates and accepted OneBuilding review annotations in immutable SQLite
generations. It screens sparse NOAA years, distinct published TMY reference periods,
and exact OEDI future-window membership. Catalog `supported` means retrieval can
be attempted; no row certifies complete hourly weather, QC or simulation fitness.
The [Stage 2 acceptance](../validation/mcp-stage-2-acceptance.md) covers offline
behavior; the 2026-09-20 live retrieval claims below remain separate.

Later metadata investigation: [MCP Stage 1 availability findings](../validation/mcp-stage-1/README.md)
(2026-09-23). These distinguish catalog evidence from usable weather, document
stale inventories and incomplete indexes, and do not expand the live acceptance
claims below.

All six access providers returned data through the implemented service on
2026-09-20. Credentials stayed local. This demonstrates the tested requests,
not universal geographic/year coverage or simulation fitness.

The [2026-09-25 Stage 6 local MCP pilot](../validation/mcp-stage-6-acceptance.md)
retrieved one full 2024 Open-Meteo ERA5 EPW and one explicitly named
OneBuilding Ithaca TMYx EPW through a real stdio client. Both completed with
`simulation_ready=false`; the native OneBuilding file reported
`NATIVE_MINUTE_ZERO`. These were local downloads, not redistributed fixtures.

| Provider | Adapter acceptance | Principal boundary |
| --- | --- | --- |
| [Open-Meteo](openmeteo.md) | ERA5 full 2024 local-standard year, 8,784 hours | Explicit model; no inferred grid deduplication |
| [PVGIS](pvgis.md) | Native TMY, 8,760 hours | Native file plus selected-month metadata |
| [OneBuilding](onebuilding.md) | Native Ithaca TMYx, 8,760 hours | Explicit product or country/name catalog; redistribution unverified |
| [NOAA](noaa.md) | 48 requested station hours | Missing fields retained; no radiation; ISD successor deferred |
| [NSRDB](nsrdb.md) | Actual 2024: 8,784 hours; native TMY: 8,760 hours | Key/email; aggregate v4 actual and published v4 TMY/TDY/TGY |
| [CDS](era5.md) | ERA5 and Land, 24 hours each | Token/accepted terms; GHI only, no DNI/DHI |

See [acceptance](../validation/v0.1-acceptance.md) for commands and limits.
The original pre-implementation access evidence is retained below as history.

# Provider feasibility — 2026-09-20

Stage 1 probes validate access, not completed integrations or simulation fitness.
Exact requests, timestamps, status codes, sizes and response hashes are in
[validation evidence](../validation/README.md). No personal credentials were used.

| Target | Real result | Auth | Documented/observed coverage and resolution | Stage 2 disposition |
| --- | --- | --- | --- | --- |
| [Open-Meteo](openmeteo.md) | ERA5: 48 hourly records, all 9 requested weather variables populated | Free endpoint: no key, noncommercial use; commercial endpoint requires subscription | ERA5: global, 1940–present, 0.25°, hourly; ERA5-Land: 1950–present, 0.1°, hourly | First converted-EPW slice; pin explicit model |
| [PVGIS](pvgis.md) | JSON TMY and native EPW; 8,760 rows, 35 EPW fields | None | Probe: SARAH3 radiation + ERA5 meteorology, source years 2005–2023; hourly TMY | First native-EPW slice, explicit API v5_3 |
| [Climate.OneBuilding](onebuilding.md) | Catalog + Ithaca TMYx 2011–2025 ZIP; 8,760 EPW rows | None | Worldwide published station products; availability and source periods vary by file | Catalog/retrieval; no bundled third-party files until redistribution terms resolved |
| [NOAA/ISD](noaa.md) | Binghamton: 64 reports in one day; station inventory accessible | None for tested Access Data Service/HTTPS | Station-specific years; subhourly/synoptic reports, not automatically 24 rows/day | Historical station provider; explicit missing-solar policy; recognize GHCNh successor |
| [NSRDB/NLR](nsrdb.md) | DEMO_KEY discovery: 4 GOES products; no key: 403; CSV request without email: 400 | Production API key + valid email | At Ithaca: aggregated 1998–2025, 4 km/30 min; CONUS 2018–2025, 2 km/5 min; full disc 2 km/10 min; TMY 4 km/hour | Implement discovery and credential-ready CSV adapter; full download acceptance needs local credentials |
| [ERA5/CDS](era5.md) | Public catalog/process schemas: 200; tiny unauthenticated retrieval: 401 | CDS account, personal token, manually accepted dataset terms | ERA5 global 1940–present, 0.25° delivery grid/hour; Land 1950–present, 0.1°/hour | Optional direct adapter; authenticated live acceptance pending |

Four distinct access providers have returned actual weather data: Open-Meteo,
PVGIS, OneBuilding and NOAA. NOAA alone lacks the radiation normally needed for
building simulation. ERA5 via Open-Meteo is not counted twice. NSRDB remains the
preferred additional U.S. solar-rich actual-year source when credentials exist.

## Selection policy

Keep all alternatives. Rank by explicit product/year/coverage compatibility,
important-variable completeness, access eligibility and station distance. Return
the reasons and gaps, not an unsupported universal quality score. Known coverage
is not proof of a complete year. Record `metadata_checked_at` and distinguish
documented coverage from actual observed availability.

Use provider-declared native identities for deduplication. Never infer identical
data merely from rounded coordinates; elevation correction, horizons and requested
parameters can change a result inside one nominal cell.
