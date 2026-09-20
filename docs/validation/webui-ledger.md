# Web UI execution ledger

Plan: docs/superpowers/plans/2026-09-20-webui.md
Approval: owner confirmed local-first single-user and autonomous execution 2026-09-20.
Start: a5d7f66, feature/webui, clean checkout.

Ruling: preserve owner's existing checkout/branch; no new worktree. User explicitly selected it.
Ruling: use this tracked Windows-native ledger instead of skill shell scratch scripts; durable repository memory takes precedence.
Preflight: Task 1 typed REST -> Tasks 2/3/5/7 client/docs; additive contracts only.
Preflight: Task 2 state/actions -> Tasks 3/4/5/6; one dispatcher, server owns scientific calculations.
Preflight: Task 7 optional /ui hosting -> Task 8 built browser tests; API routes retain their own semantics.
Task 1: implemented; targeted API/preview/jobs suite 9 passed. OpenAPI exports offline. Type checking corrected numeric summary dictionary inference.
Tasks 2–8: pending.

Tasks 2–3: shell/client/manual retrieval implemented. TypeScript, ESLint and 5 unit tests passed. Browser retrieval with a real fixture backend passed discovery, execution, preview and download; compact workflow passed.
Tasks 4–7: first integrated map/future/agent/docs views exist; expanded acceptance in progress.
Ruling: TypeScript 5.9.3 replaces reference 6.0.3 because openapi-typescript 7.13.0 declares a TypeScript 5 peer; no forced dependency install. Cost: fewer new TS6 features, none used.
Ruling: include optional hosting early to test the actual built app rather than wait until final integration. Existing API behavior preserved.
Browser finding: Vite prebundling orphaned MapLibre workers; match reference optimizeDeps exclusion and production worker emission. Missing FlexLayout sourcemap stripped, not a real application source error.
Initial visual check: 1440x950 results screen inspected; dense two-column layout, actual download controls, chart units and QC warning visible.

Tasks 4–7: complete. Optional /ui hosting, generated REST/Python/MCP references, MapLibre terrain/hillshade/buildings/globe, requested/known source distinction, future uploads and real scripted dispatch integrated.
Review: independent read-only reviewer found stale preview after submit, lost source-year mapping, ineffective client cancellation; reproduced each in failing tests and fixed. Also fixed comma-list editing, persisted versioned drafts, guarded/deduplicated pagination, and persisted submission intent hashes for reload/retry reconciliation. Reviewed plans never auto-run after reload; explicit rerun creates a new key.
Acceptance: 77 Python passed / 15 live skipped; Ruff and mypy (42 source files) passed. 14 UI unit tests, typecheck/lint/build passed; 8 development and 8 production Edge browser scenarios passed. Six theme readability checks and Axe serious/critical check passed. Actual screenshot inspected for light/results and dark/map layouts.
Live: fresh empty-cache Open-Meteo 2024-02-14 Ithaca returned 24/24 temperature samples, no bundle issues. Real REST retrieval of 2023 baseline plus ACCESS-CM2 SSP245 2050 morph, preview and artifact download passed using the existing .local/live-cmip cache. This is not a fresh climate-download or all-provider acceptance claim.
Ruling: preserve current branch at delivery; no push/merge/publication. Finish-branch menu is unnecessary because the owner requested autonomous implementation on this branch and the approved plan already says preserve it.

Final acceptance expanded: 10/10 development and 10/10 production browser tests passed, including forced WebGL failure and partial/cancel UI states. Source-year and cancellation regressions remain green; 14 UI unit tests. Final Python suite 77 passed / 15 skipped. Generated artifact binary response now explicitly documented. Wheel/sdist built; core wheel installed without API/MCP/climate extras; archive exclusions checked. Final docs/ADR/roadmap and CI completed. Cross-OS/browser and full ten-output UI ensemble permutations remain documented follow-ups.
