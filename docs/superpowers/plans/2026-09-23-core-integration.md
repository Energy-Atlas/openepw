# Core integration and output identity implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring independent backend fixes from `feature/webui` into `main`, give each requested output a stable identity and semantic filename, make dataset selection work per requested point, support retry of failed outputs, then integrate `main` back into `feature/webui` and start `feature/mcp` from updated `main`.

**Architecture:** Keep canonical behavior in Python models, planning, service, and job store/worker. REST/MCP/UI remain adapters. Distinguish a provider/dataset selection from a station-specific product candidate; represent each requested output by an explicit identity independent of the filename. Keep legacy serialized plans readable and their hashes valid. No global-coverage claims based on UI polygons enter the core.

**Tech Stack:** Python 3.11+, Pydantic, SQLite, pytest; PowerShell and Git.

**Spec:** `docs/superpowers/specs/2026-09-23-core-integration-design.md` (owner approved 2026-09-23).

## Global constraints

- Work in the isolated `fix/core-output-identity` worktree. Preserve the original `feature/webui` worktree and all unrelated edits.
- For each behavior change, first add a focused failing offline test, then implement the smallest change, run the test, and commit at a feature/provider/docs/test boundary using `fix(topic): ...`.
- Use `C:\github\Energy-Atlas\openepw\.venv\Scripts\python.exe` with `PYTHONPATH` set to the current worktree's `src` directory for all test commands.
- Do not alter public REST/MCP contracts beyond additive optional fields. Validate legacy JSON plans and plan hashes with a pre-change fixture.
- Do not cherry-pick generated UI assets into the core branch. Do not push or delete any branch.

## Task 1: independent job persistence fixes

**Files:** `src/openepw/jobs/store.py`, `src/openepw/jobs/worker.py`, `src/openepw/models/__init__.py`, `tests/unit/test_jobs.py`.

- [ ] Add tests proving SQLite connections close after store operations, a failed job reports failed count before final completion, and historical/future job kind survives storage/reload.
- [ ] Run `python -m pytest tests/unit/test_jobs.py -q` and confirm the new assertions fail.
- [ ] Port the focused logic from web UI commits `ee70569`, `8bede45`, and `9c2030c`, excluding UI-generated files.
- [ ] Run the focused tests and commit `fix(jobs): preserve kind and failure progress`.

## Task 2: provider and location independent fixes

**Files:** `src/openepw/providers/http.py`, `src/openepw/providers/nsrdb.py`, `src/openepw/planning/spatial.py`, `src/openepw/models/__init__.py`, `src/openepw/service.py`, `tests/unit/test_service.py`, `tests/unit/test_models.py`, `tests/unit/test_spatial.py`, `docs/providers/nsrdb.md`.

- [ ] Add tests for provider-specific HTTP retry status override including NSRDB 429, ranked candidate IDs per requested location, and explicit longitude-derived standard offset. Keep UTC default hash compatibility.
- [ ] Run the focused tests and confirm failure.
- [ ] Port focused behavior from `372c689`, `2f8f425`, and `09dd95c`; preserve scientific core independence from server/MCP/xarray.
- [ ] Run focused tests and commit at provider and planning boundaries (`fix(nsrdb): ...`, `fix(planning): ...`).

## Task 3: output identity and semantic names

**Files:** `src/openepw/models/__init__.py`, `src/openepw/service.py`, `src/openepw/planning/future.py`, new `src/openepw/planning/output_identity.py`, `tests/unit/test_models.py`, `tests/unit/test_service.py`, `tests/unit/test_future.py` (or the existing future test module), `tests/fixtures/` only if needed for a small synthetic legacy plan.

- [ ] Add tests: two distinct requested points sharing one station yield two outputs with distinct IDs/names; two identical point entries also remain distinct by occurrence; repeated planning produces identical IDs; historical and future names are semantic, filesystem-safe, at most 100 characters, and end in a short identity suffix; old plans without IDs parse and retain their existing hash.
- [ ] Run focused tests and confirm failure.
- [ ] Add optional `OutputSpec.id` and deterministic ID construction using requested location key, occurrence index, candidate/provider/dataset/product, period/scenario/window and output index as relevant. A stable digest suffix resolves truncation/collision. Do not use display filename as the identity.
- [ ] Implement naming helpers and use them in both historical and future planning. Avoid embedding secrets, provider query strings, or unstable timestamps in names.
- [ ] Run focused tests and commit `fix(planning): identify outputs and name epws semantically`.

## Task 4: execution and persistence keyed by output identity

**Files:** `src/openepw/service.py`, `src/openepw/jobs/store.py`, `src/openepw/jobs/worker.py`, `src/openepw/models/__init__.py`, `tests/unit/test_jobs.py`, `tests/unit/test_service.py`.

- [ ] Add tests for shared fetch task fan-out into two requested outputs, separate job items/artifacts for identical requested point entries, and correct requested-location attribution in manifests. Add one legacy-plan execution case without IDs.
- [ ] Run focused tests and confirm failure.
- [ ] Key execution dedupe, store items and worker subplans by output ID, falling back to the legacy name only for old plans. Keep `name` as a presentation/download filename.
- [ ] Ensure a completed output increments job counts exactly once and neither duplicate point nor station sharing is collapsed.
- [ ] Run focused tests and commit `fix(jobs): track outputs by identity`.

## Task 5: multi-dataset planning semantics

**Files:** `src/openepw/models/__init__.py`, `src/openepw/service.py`, `src/openepw/planning/` as required, `tests/unit/test_service.py`, `tests/unit/test_models.py`, REST schema tests if affected.

- [ ] Add tests: two selected datasets yield each requested dataset at each eligible location; a station-specific `product_id` does not masquerade as a global dataset choice; each point resolves its own ranked candidate; an unavailable dataset yields a structured per-point/per-dataset issue without silently substituting a different dataset; output order and IDs remain deterministic.
- [ ] Run focused tests and confirm failure.
- [ ] Add optional request-level dataset selections (provider/dataset with optional product variant). Make explicit selections authoritative; preserve existing default/hybrid behavior when absent. Resolve station candidates locally and report exact selection failures. Keep data provenance per variable.
- [ ] Run focused tests and commit `fix(planning): resolve datasets per location`.

## Task 6: failed-output retry

**Files:** `src/openepw/jobs/store.py`, `src/openepw/jobs/worker.py`, `src/openepw/api/app.py` if an additive route is appropriate, `tests/unit/test_jobs.py`, `tests/unit/test_api.py`.

- [ ] Add tests: a partial job retries failed/unavailable outputs only, retains successful artifacts, never duplicates successful outputs, and records retry relationship and failure reason; no-op retry when nothing failed is explicit.
- [ ] Run focused tests and confirm failure.
- [ ] Implement retry as a new job referencing the original, using a subplan of failed output IDs. Keep original job/artifacts immutable. Expose through a narrow service/store or additive REST operation as appropriate; do not require MCP-specific logic.
- [ ] Run focused tests and commit `fix(jobs): retry failed outputs only`.

## Task 7: documentation and verification

**Files:** `ARCHITECTURE.md`, `FEATURES.md`, `docs/ROADMAP.md` or actual roadmap file, `docs/plans/2026-09-20-stage-2.md`, relevant ADR/provider docs, this plan.

- [ ] Document output identity versus display name, local candidate resolution, multi-dataset semantics, retry and known coverage limitations. Do not claim global data coverage or simulation readiness from syntactic EPW validity.
- [ ] Run `python -m pytest -q`, `python -m ruff check src tests`, and `python -m mypy src/openepw` using the configured venv. Capture exact output and any pre-existing failures.
- [ ] Inspect `git diff main...HEAD` for accidental UI/static hosting changes, generated assets, secrets, or unrelated edits; commit documentation and verification fixes.

## Task 8: branch integration

- [ ] Confirm `main` and `feature/webui` worktrees are clean or preserve their existing changes. Record branch heads and merge bases.
- [ ] Merge `fix/core-output-identity` into `main` using a normal merge, never a destructive reset/rebase. Run focused and full tests on `main`.
- [ ] Merge updated `main` into `feature/webui`, resolve only actual conflicts while preserving UI work, and run backend/UI checks appropriate to changed files.
- [ ] Create `feature/mcp` from updated `main`; do not incorporate UI-only commits. Verify `git merge-base feature/mcp main` equals `main` and that `feature/webui` contains updated `main`.
- [ ] Report branch heads, commits, test results and any remaining UI-only coverage/map issue. Do not push unless asked.

## Review focus

- Identity survives duplicate requested entries and shared station fetches without mutating source-task dedupe.
- New optional model fields cannot change legacy plan hashes or make old persisted plans unreadable.
- Dataset selections describe datasets, not station IDs; unavailable combinations produce visible issues.
- Future output naming remains deterministic and compatible with future execution's output indexing.
- A retry references original failures without rewriting original artifacts or claiming success for failed output.
