# Stage 1 completion checklist

Date: 2026-09-20. This validates the research handoff, not an implemented v0.1.

| Required deliverable | Evidence |
| --- | --- |
| All six provider targets and real small requests | [Matrix](../providers/README.md) and five JSON reports in this directory |
| Auth / years / resolution / important variables | Matrix plus six provider notes; no credential values in reports |
| Libraries, copied-code candidates and unusual SDK licenses | [Reuse review](../methods/reuse-review.md), pinned revisions and response hashes |
| Current EPW conventions and missing markers | [EPW contract](../methods/epw-conventions.md), three inspected native EPWs |
| Two genuinely distinct future approaches | [Morphing and hourly selection](../methods/future-weather.md); metadata and ZIP64 sample access |
| Package/modules, schemas, REST, MCP, jobs/artifacts | [ARCHITECTURE.md](../../ARCHITECTURE.md) |
| Baseline repo/contributor/product docs | README, AGENTS, CONTRIBUTING, FEATURES, ROADMAP, ADR 0001 |
| Stage 2 milestones, tests, blockers and requested input | [Approval plan](../plans/2026-09-20-stage-2.md) |

Executed checks:

- `python -m compileall -q scripts`: passed.
- `git diff --check` and staged equivalent: checked before commits.
- Every relative Markdown file link resolves.
- All five JSON evidence files parse; provider response hashes match retained
  local bodies. Archive range-byte sum and extracted member hash agree.
- PVGIS and OneBuilding samples each have 8,760 rows × 35 fields; OEDI sample
  has the same structure and passed ZIP CRC verification.
- Relevant NLR/CDS environment variables were absent; no home `.cdsapirc` existed.
  Only presence was checked, never printed credential values.
- Raw bodies, local research source and secret-bearing config names are ignored.

Limits: no product tests, product package, climate numeric execution or EnergyPlus
run yet. Four providers returned weather; two authenticated download paths remain
unverified. Method B access is proven at one location/year, not all sites/periods.
The CMIP6 probe establishes paired metadata access, not full-variable availability.

Stage 1 stops for the owner's plan approval. Nothing here authorizes Stage 2 by itself.
