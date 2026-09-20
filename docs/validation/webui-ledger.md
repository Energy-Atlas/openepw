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
