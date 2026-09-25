# Features and implementation status

Updated 2026-09-25. v0.1 Stage 2 and MCP Stage 2 are distinct; acceptance and limitations
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
| MCP availability research | Stage 1 accepted | Bounded inventory investigation and accepted annotations; [findings](docs/validation/mcp-stage-1/README.md) |
| Shared availability catalog | MCP Stage 2 implemented, offline tested | Explicit local import validates analysis input fingerprints; bundled safe contracts when inventories are absent; immutable generations, sparse years, future membership, stale fallback |
| Eligibility and recommendations | MCP Stage 2 implemented, offline tested | Per-occurrence reasons and unknowns; supported means retrieval eligible, not weather complete |
| Availability interfaces | Python, REST, CLI and MCP implemented | MCP includes shared evidence and bounded discovery; support is retrieval eligibility |
| Weather batch row accounting | MCP Stage 3a implemented, offline tested | Every occurrence/selection/period has a planned, unsupported or unresolved row; final manifests distinguish success, failure and cancellation |
| Stored weather plans and jobs | MCP Stage 3a implemented, offline tested | Hash references, partial completion, verified restart and explicit retry; job-local verified task reuse |
| Compact weather export | MCP Stage 3a implemented, offline tested | Explicit local ZIP with complete CSV mapping, one weather member per exact equivalence group, checksum verification; redistribution rights unchanged |
| Registered future baselines | MCP Stage 3b implemented, offline tested | Uploaded or trusted local EPW and fetched weather artifact IDs; annual/missing-variable preflight, checksum-linked source manifest/QC |
| Durable future members | MCP Stage 3b implemented, offline tested | Stored future plan hashes, member-level jobs, partial retry and cancellation; monthly morph and hourly climate profile remain distinct |
| Local MCP contract | MCP Stage 4 implemented, offline tested | Real stdio SDK sessions, structured tools, stored plan hashes, bounded baseline upload, verified artifacts/resources and QC; no remote auth rollout |
| Reference MCP agent | MCP Stage 5 implemented, offline and bounded live tested | Optional direct stdio harness; typed low-cost model intent, plan review, job resume and QC explanations; local redacted records, no LangSmith trace |
| Agent and real-client local pilot | MCP Stage 6 accepted on Windows | Real SDK stdio journeys and bounded Open-Meteo/OneBuilding runs; no human participant, other desktop host or EnergyPlus certification |
| Local availability map | Research artifact, outside installed package | [PVGIS source-region approximation, NSRDB published grid, CMIP6 license counts](docs/validation/README.md); layers have different evidence bases and do not certify request eligibility |
| Packaging/CI | Wheel/sdist built; local installation verified | Cross-OS runners configured; see actual run evidence |

Reserved: sampled/stochastic weather, additional hourly scenarios/geographies,
GHCNh successor adapter, automatic global OneBuilding proximity catalog, simulator
certification. No historical TMY/XMY generator or distributed service. An approved
web UI is under development on `feature/webui`; it is not yet part of `main`.
See [limitations](docs/limitations.md) for exact reduced capabilities and follow-ups.
