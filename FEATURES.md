# Features and implementation status

Updated 2026-09-26. v0.1 Stage 2 and MCP Stage 2 are distinct; acceptance and limitations
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
| Place lists and sets | Implemented, offline tested; GeoNames live check | Up to 1,000 names/coordinates previewed without per-place confirmation (ambiguity flagged, misses kept); points-only coordinate parsing; descriptive sets ask region/definition/limit before a GeoNames (CC BY 4.0) population-ordered listing |
| Source reuse and output identity | Tested 73 requests → 11 verified sources → 73 EPWs | Fetch tasks deduplicate; requested outputs do not collapse |
| Semantic EPW names | Implemented, offline tested | Location/source/period or future method/scenario/window/member with digest suffix |
| Multi-dataset planning | Implemented, offline tested | Provider/dataset selection resolves local candidate at each point; an optional `variant` (e.g. `TMYx.2009-2023`) picks that published file family at each point; unavailable combinations are explicit issues |
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
| Local MCP contract | MCP Stage 4 implemented, offline tested; future endpoints temporarily suspended | Real stdio and in-memory SDK sessions, typed tool schemas, summarized results, location review and product offer tools, elicitation-confirmed submission, one runner per data root; existing future records remain readable; no remote auth rollout |
| Agent chat core (guided) | P2 implemented, offline tested | One MCP-client session for CLI (and later web): typed forms, approval gates, host-built plans, one-shot approvals, guided mode, `openepw chat` |
| Agent mode and evals | P3 implemented; offline tested; live evals run locally, final run 33/33 (P3 plan execution notes) | Tool-calling OpenAI model behind the same forms and gates, host ask-tools, guided fallback, `/mode`, `openepw eval` with packaged scenarios, offline stubs and opt-in live runs; web renderer not yet (P4) |
| Weather visualization JSON | Initial families implemented, offline tested | Framework-neutral spec and immutable paged data for hourly, annual, monthly, histogram and spatial views; complete planned family catalog; basic `openepw-chat` follow-ups return JSON, while the optional browser renders charts |
| Reference MCP agent | MCP Stage 5 implemented, offline and bounded live tested | Optional direct stdio harness; typed low-cost model intent, plan review, job resume and QC explanations; local redacted records, no LangSmith trace |
| Interactive console chat | Implemented; checkpointed flow offline tested, extraction live smoke tested | LangGraph SQLite conversation memory, LangChain multi-intent extraction, arrow-key location/product choices with Other/text fallback and one actual-year (AMY/historical) choice, read-only catalog exploration; automatic weather plan execution with an in-place output progress bar, structured redacted MCP call/result/error messages, and Ctrl+C cancellation, EPW upload/inspect/save, future request suspension, optional LangSmith traces; one writer per data root/thread; existing ignored `.env` read only |
| Map-first browser chat | Implemented on `feature/chat-ui` for local review | Optional React/Vite client over shared REST: durable session facts, explicit plan/Run, nominal longitude-based standard-time offset for chat locations without one (shown at plan review), on-demand map geography toolbar, faint documented catalog scopes, manifest mapping, one/all browser downloads, composer attachment for EPW/GeoJSON, and floating prepared-data charts; see [validation](docs/validation/2026-09-26-chat-ui.md) |
| Map availability layers | Implemented for local review | `/v1/catalog/map` serves Stage 1 catalog detail: 15,476 NOAA stations with inventory years, 21,648 OneBuilding sites, NSRDB `tdy-2023` source-grid cells (local verified mask), approximate PVGIS SARAH3 envelope and ERA5/ERA5-Land extents; all toggled in the map legend, none asserts point eligibility |
| Globe and decorative scene shadows | Bounded renderer implemented for local review | OpenFreeMap globe/buildings, automatic 3D at district zoom (no scene panel; terrain and alternate appearances not exposed in the UI), projected building ground/roof shadows and sampled relief occlusion; vector heights/DEM grid are approximations and never energy-model inputs |
| Agent and real-client local pilot | MCP Stage 6 accepted on Windows | Real SDK stdio journeys and bounded Open-Meteo/OneBuilding runs; no human participant, other desktop host or EnergyPlus certification |
| Local availability map | Research artifact, outside installed package | [PVGIS source-region approximation, NSRDB published grid, CMIP6 license counts](docs/validation/README.md); layers have different evidence bases and do not certify request eligibility |
| Packaging/CI | Wheel/sdist built; local installation verified | Cross-OS runners configured; see actual run evidence |

Reserved: sampled/stochastic weather, additional hourly scenarios/geographies,
GHCNh successor adapter, automatic global OneBuilding proximity catalog, simulator
certification. No historical TMY/XMY generator or distributed service. The
separate `feature/webui` branch remains independent; `feature/chat-ui` is not
merged into `feature/mcp` or `main`.
See [limitations](docs/limitations.md) for exact reduced capabilities and follow-ups.
