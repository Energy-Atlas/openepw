# Roadmap

## Stage 1 — complete, awaiting plan approval

- [x] Inspect clean repository, branches, brief and MIT license.
- [x] Probe all six provider targets, auth gates, native EPWs and geocoding.
- [x] Inspect EPW conventions and candidate code/data licenses.
- [x] Validate a distinct hourly future-weather source by partial archive access.
- [x] Establish contributor rules, architecture, schemas and implementation plan.
- [ ] Owner approves [Stage 2 plan](docs/plans/2026-09-20-stage-2.md).

## Stage 2 — not started

1. Core schemas, configuration, EPW/QC and packaging/CI.
2. Open-Meteo historical and PVGIS native TMY retrieval with manifests (MVP A).
3. OneBuilding, NOAA, NSRDB and optional direct CDS; realistic provider statuses.
4. Explicit hybrids, spatial sampling, deduplication and artifact bundles (MVP B).
5. Durable local jobs and REST.
6. CMIP6 morphing and hourly WRF profile selection, profile/ensemble semantics
   and scientific acceptance tests (MVP C after first method).
7. MCP and lightweight CLI/examples.
8. Cross-platform packaging, reproducibility, documentation and whole-scope review.

MVPs are feedback opportunities, not additional required approvals. After Stage 2
approval continue autonomously under [AGENTS.md](AGENTS.md). Publication remains
a separate explicit human action.

## Provider/method follow-ups

- Credentials: NLR API key/email; CDS token and manually accepted terms.
- OneBuilding: establish redistribution rights before bundling/rehosting data.
- NOAA: probe GHCNh current availability before promising years after ISD's end.
- CMIP6: validate multivariable numeric access and license-aware model selection.
- Future: more hourly sources/geographies/scenarios, sampled methods only after
  two defensible core methods work.
