# Features and implementation status

Updated 2026-09-23. Stage 2 approved and implemented; acceptance and limitations
are recorded separately. Installed source package version: 0.1.0.

| Capability | Status | Important boundary |
| --- | --- | --- |
| Python workflow and typed plans | Implemented, tested | Core API is canonical; no hidden provider fallback |
| EPW read/write/QC | Implemented, tested | 35 columns; partial/annual validation separate; optional explicit `skip_feb_29`; not simulator certification |
| Open-Meteo ERA5 | Live full leap-year accepted | Noncommercial free hosting; ERA5-Land variables may be unavailable |
| PVGIS native TMY | Live 8,760 rows accepted | Original EPW and selected-month/source metadata retained |
| OneBuilding published files | Live 8,760 rows accepted | Explicit product ID or country catalog + name; no global nearest-site index |
| NOAA ISD | Live 48-hour station result accepted | QC flags, nearest report within 30 minutes; gaps, no solar or station pressure |
| NSRDB/NLR | Live actual 8,784 and native TMY 8,760 rows accepted | Aggregate v4 actual years; native TMY/TDY/TGY IDs from catalog; key/email required |
| Direct CDS ERA5/Land | Both products live one-day outputs accepted | GHI only; bounded polling; terms/token and optional dependencies |
| Spatial/batch | Tested | Point lists, bbox/dateline, polygons/holes, grid offsets, preallocation cap |
| Source reuse and output identity | Tested 73 requests → 11 verified sources → 73 EPWs | Fetch tasks deduplicate; requested outputs do not collapse |
| Semantic EPW names | Implemented, offline tested | Location/source/period or future method/scenario/window/member with digest suffix |
| Multi-dataset planning | Implemented, offline tested | Provider/dataset selection resolves local candidate at each point; unavailable combinations are explicit issues |
| Explicit hybrids | Tested | Named source per variable; exact matching timelines; no missing-data fill |
| CMIP6 monthly morph | Live full output accepted | Seven-variable coherent signals; default ACCESS-CM2 SSP245 verified |
| Hourly climate profiles | Live typical, shock, persistence and ten-year ensemble accepted | U.S. PUMA sites, CCSM4/WRF, RCP4.5/8.5 and two exact windows |
| Future ensembles | Implemented | Model/member outputs for morph; temporal years for hourly archive |
| REST/jobs/artifacts | Implemented, offline tested | SQLite + filesystem; identity-keyed progress and failed-output retry; single server process; bearer auth for remote REST |
| MCP and CLI | Implemented, offline tested | Stdio and loopback Streamable HTTP; compact artifact references |
| MCP availability research | Stage 1 completed, tooling offline tested | Bounded inventory investigation; [findings](docs/validation/mcp-stage-1/README.md); production catalog/recommendation integration remains future work |
| Packaging/CI | Wheel/sdist built; local installation verified | Cross-OS runners configured; see actual run evidence |

Reserved: sampled/stochastic weather, additional hourly scenarios/geographies,
GHCNh successor adapter, automatic global OneBuilding proximity catalog, simulator
certification. No historical TMY/XMY generator or distributed service. An approved
web UI is under development on `feature/webui`; it is not yet part of `main`.
See [limitations](docs/limitations.md) for exact reduced capabilities and follow-ups.
