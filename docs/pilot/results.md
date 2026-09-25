# Stage 6 local pilot results

Date: 2026-09-25. Host: Windows, Python 3.13.9, MCP Python SDK 1.30.0,
negotiated protocol 2025-11-25. The client was an actual SDK stdio session;
the agent used the same client and public MCP tools. A fresh ignored virtual
environment installed `.[harness]`, started the server, listed 18 tools and
one resource template, and inspected a checksum-verified artifact. No desktop
LLM host or human participant was used.

The [scorecard](scorecard.md) was fixed before these journeys. Eight of nine
rows passed the deterministic offline matrix; B was partial because the far
point remained `unresolved`, while the frozen scorecard expected an explicit
`unsupported` row. The active catalog had no evidence for a hard exclusion,
so the client preserved uncertainty. This meets the predefined 8/9 threshold
and the critical rule against fabricated availability. Every journey used synthetic or
synthetic-inventory data and finished under the 120-second case limit. The
agent and client traversed discovery/plan/job/artifact IDs through the actual
stdio protocol, including EPW resource bytes; ordinary tool responses remained
bounded summaries. `simulation_ready=false` was retained for emitted weather.

| Row | Observed result |
| --- | --- |
| A | One 2024 Ithaca point, station and uncertain alternative, selected source/reasons, 8,784-row EPW, manifest/QC IDs, resource read and agent resume after reconnect. |
| B — partial | Exact named TMYx product, four occurrences with one duplicate and one unresolved far point, three distinct outputs, one shared published source, compact ZIP and agent partial-result explanation. Hard `unsupported` status was not established. |
| C1 | User-uploaded 8,760-row EPW ID, SSP245 morph, explicit 1985–2014 reference and 2036–2065 climate window, `user_provided` origin. |
| C2 | A fetched weather artifact ID used as morph baseline with `weather_output` origin; separate synthetic PUMA RCP8.5 hourly profile used bounded HTTP Range/ETag/CRC archive access and retained OEDI lineage and comparison-baseline identity. |
| C3 | SSP with hourly profile, unsupported RCP window and distant PUMA site were rejected with typed errors; no substitute source or scenario was chosen. |
| G warn | Sparse NOAA reports emitted a sentinel-bearing EPW, linked missing-variable QC and `simulation_ready=false`; agent resumed and explained the gap. |
| G error | The same gap emitted no EPW; a two-point batch kept the other valid output while one failed. Failed-output retry preserved the distinction. |
| Recovery | Reconnect and resume, cooperative active cancellation of a two-output job, preservation of any completed output, retry of only missing output, path allowlist, malformed upload and missing/corrupt artifact handling. |
| Merged evidence | Published `tdy-2023` identity stayed separate from unprobed actual-year 2023. An allowed effective CMIP6 license did not turn unverified climate/reference windows into supported weather. |

## Bounded live observations

Two public provider GETs were initiated through the real MCP stdio client, in
an ignored local data root. Open-Meteo ERA5 returned a full 2024 Ithaca EPW in
2.36 seconds with seven MCP calls, one output, no QC issue codes and
`simulation_ready=false`. A named OneBuilding Ithaca TMYx ZIP returned one EPW
in 1.31 seconds with five MCP calls, `NATIVE_MINUTE_ZERO` QC and
`simulation_ready=false`. The downloaded provider files and local run JSON are
ignored; they are not redistribution fixtures. These observations establish
only the exact tested product, location and period. PVGIS, NOAA, NSRDB, CDS
and live future archives were not repeated in this Stage 6 live matrix;
their earlier provider evidence and the synthetic pilot are separate.

The optional `gpt-6-luna` Responses parser was exercised with a synthetic
actual-year point and named four-point TMYx batch. The first batch parse
classified explicit TMYx as generic `published` and capitalized OneBuilding,
which led to no executable output. The parser guidance now distinguishes
TMYx and lowercase provider IDs, and the agent normalizes provider casing.
The bounded rerun selected `tmyx`/`onebuilding`, completed three outputs and
reported the unresolved far point. Across Stages 5–6, eight model calls used
3,161 input and 1,568 output tokens, estimated US$0.0011001 at the checked
standard model rates. No LangSmith call or hosted trace was made. The `.env`
file was read only for the model test and remained unmodified.

## Limits and minor findings

- The real SDK client read EPW resource bytes successfully; behavior in other
  desktop hosts, operating systems and smaller resource limits remains unknown.
- No EnergyPlus consumption or human comprehension study was performed. An EPW
  can be structurally valid while containing sentinel gaps or other warnings.
- The malformed/unknown artifact MCP code is the generic `INVALID_ARTIFACT`;
  the pilot assertions were aligned to that existing contract. Unsupported
  SSP/RCP method combinations return `INVALID_SCENARIO_PERIOD`.
- The fresh environment installed and started correctly. Pip printed a local
  pre-existing `Ignoring invalid distribution ~penepw` warning; it did not
  prevent installation or the protocol smoke.
- Only synthetic offline fixtures are tracked. Stage 1 snapshot files and
  accepted annotations were not recollected or changed.
