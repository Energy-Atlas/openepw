# Stage 2 execution record

Owner approval: 2026-09-20, recorded in the [plan](../plans/2026-09-20-stage-2.md).
The current feature/stage-1-validation branch and owner's credentials were preserved.
The owner authorized autonomous implementation through substantial v0.1 completion.

## Implemented increments

| Task | Result / commit |
| --- | --- |
| 1 Foundation | Typed models, configuration, package, CI — efe9fca |
| 2 EPW/QC | Codec, sentinels, calendars, annual/partial QC — c98edf7 |
| 3 Historical vertical slice | Open-Meteo, plans, artifacts/cache — 41581f6 |
| 4 Native products | PVGIS and OneBuilding — af82efb |
| 5 Additional providers | NOAA, NSRDB and direct CDS — 6e65d64 |
| 6 Batch/spatial/hybrid | Verified identity reuse, explicit variable assignment — 1eab6da |
| 7 Jobs/REST | SQLite item checkpoints, artifact endpoints, auth — 1eab6da |
| 8 Monthly future method | Seven-variable CMIP6 and independent morph equations — 8b4ca21 |
| 9 Hourly future method | Coherent WRF typical/extreme/ensemble selection — 8b4ca21 |
| 10 Interfaces | CLI, six MCP tools, artifact resource — 01bd1e7 |
| 11 Acceptance | Review fixes and regressions — 7ef543f; installation/docs — final delivery commit |

## Empirical findings and resolved issues

- CMIP6 catalog yielded 170 complete historical/SSP245 seven-variable pairs.
  ACCESS-CM2 r1i1p1f1 gn numeric access passed tas/tasmin/tasmax/hurs/ps/sfcWind/rsds,
  with 360 months for each 1985–2014 and 2036–2065 period. Nearest cells, source
  calendars and units are preserved. Planning estimates large spatial chunks.
- NSRDB requires the current NLR host and a narrowly allowed S3 redirect. Both
  actual-year and native TMY adapters passed with runtime-only credentials.
- NOAA cross-year requests returned empty; splitting by calendar year recovered
  reports. Unsupported radiation and station pressure are not synthesized.
- CDS returns a ZIP containing instantaneous and accumulated NetCDFs. Separate
  coordinate-consistent decoding and ERA5-Land deaccumulation passed real data.
  Concatenate monthly pieces before differencing to retain boundary-midnight energy.
- OEDI location CSV uses Latin-1. Its future source years use 365-day calendars,
  including leap-labeled years. Explicit noleap handling fixed the ten-year ensemble.
- WCRP records ACCESS-CM2's 2022-06-10 CC BY-SA to CC BY license relaxation;
  both original attributes and the authoritative snapshot are preserved.
- TLS verification uses the operating system trust store; no disabled certificate
  verification was introduced to work around the CDS object store.

## Independent review and hardening

One read-only review examined scientific contracts, security and job behavior.
All material findings were addressed: cache-key path validation; approved CMIP6
store origins and execution budgets; Windows artifact names; missing values during
hybrid downsampling; baseline per-variable lineage; Land month boundaries.
Additional regressions cover archive truncation/ETag changes, native noleap EPWs,
future ensemble progress/cancellation, completed-item restart reuse, future-plan
scenario integrity, missing-temperature extreme ranking and secret log redaction.

Signed CDS results originally appeared in an ignored development metadata cache;
that cache was removed and those responses now remain memory-only. No committed
credential or shared artifact exposure was found. Public fixtures are synthetic.

## Collected follow-ups, not blockers

See [limitations](../limitations.md): global OneBuilding proximity discovery and
redistribution, NOAA GHCNh, fractional-hour interpolation, remote MCP auth,
single-process jobs, simulator validation, wider hourly climate coverage and
experimental sampled weather. Optional HTTP test dependencies emit two deprecation
warnings. Cross-platform CI is configured but was not executed from this Windows
session. No purchase, account creation, publication or destructive git action occurred.

The [acceptance record](v0.1-acceptance.md) is the final source of command results,
coverage, installation evidence and the brief section 35 checklist.
