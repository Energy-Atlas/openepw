# Repository operating rules

Read [the human handoff](docs/20260920-openepw-brief.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[FEATURES.md](FEATURES.md) and the current [plan](docs/plans/2026-09-20-stage-2.md)
before broad work. The newest explicit human decision wins; record unresolved
conflicts. Stage 2 is **not approved** until the owner explicitly approves it.
Record approval in the plan when received; never infer approval from elapsed time.

## Scope and implementation

- Python package is canonical. REST, MCP and CLI call the same service layer.
- No historical TMY/XMY generator, frontend, or mandatory distributed services.
- Implement two genuinely distinct future methods; retain actual scenario/window
  semantics and per-variable provenance. No fabricated availability or metadata.
- Keep scientific/data core independent of server/MCP/xarray imports.
- Make routine choices, document them and continue after Stage 2 approval.
- Preserve other contributors' work. Inspect status, branches, docs and recent
  commits before broad refactors. Do not assume this is the only active machine.

## Git and secrets

- Use normal configured human authorship; no agent/model coauthors or trailers.
- Commit moderately often at feature/provider/docs/test boundaries using
  `fix(topic): concise description`, as required by the handoff.
- Prefer `codex/` branches. No force push, destructive rebase/reset, published
  history rewrite, deletion of collaborators' work, or branch deletion without
  explicit human authorization.
- Only secret templates belong in git. Keep local credentials ignored; never
  serialize keys into plans, URLs in logs, manifests, fixtures or exceptions.
- If a real secret is found in tracked history, stop and alert the owner for
  rotation; do not rewrite history on your own.

## Verification and documentation

- Update architecture, features, roadmap, provider limitations and ADRs when
  decisions change. Chat history and local-only notes are not project memory.
- Deterministic offline tests cover schemas, planning, EPW, QC, normalization,
  provenance, artifacts and future transforms. Live tests are opt-in and tagged.
- Keep small sanitized fixtures only when redistribution permits; prefer
  synthetic fixtures for uncertain sources. Check relevant licenses before reuse.
- Validate timezone, interval, leap-year, solar-energy and missing-data semantics.
  Do not repair silently or call a syntactically valid EPW simulation-ready.
- Run checks appropriate to each change; report actual results and limits.
- Preserve third-party notices for adapted code and data attribution in artifacts.

## Human-intervention boundaries

Stop at the Stage 1 plan review. After Stage 2 approval, do not add routine gates.
Escalate only: major scope contradictions; essential restrictive/unclear code
reuse; materially necessary credentials/accounts the agent cannot obtain;
irreversible external actions (including PyPI publication, ownership, purchases,
paid terms/accounts); security incidents; destructive git; material scientific
ambiguity without a defensible default; or breaking an explicitly stable approved
public API. Work on independent unblocked tasks before requesting credentials.

For blocked providers: reproduce, read current docs, try a few reasonable paths,
classify and document the exact restriction, implement a practical fallback, then
defer transparently. Never stall the whole project for a provider count or claim
a credential-gated adapter has passed live acceptance.
