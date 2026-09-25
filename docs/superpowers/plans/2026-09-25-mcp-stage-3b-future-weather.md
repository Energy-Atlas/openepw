# Stage 3b implementation plan: future weather from both baseline paths

Status: owner approved autonomous Stages 3a–6 implementation on 2026-09-25. Begin Stage 3b after Stage 3a acceptance; no routine stage-by-stage review is required.

> **For agentic workers:** Use `superpowers:executing-plans` task by task after approval. Write failing tests for behavior changes, verify and commit each coherent increment. The checkboxes are execution tracking, not extra human approval gates.

**Goal:** Make future-weather planning, jobs and artifacts work equally well from a user-supplied local EPW and a weather artifact fetched by OpenEPW, while preserving the distinct science and limits of both existing methods.

**Architecture:** Add a typed baseline registration/resolution boundary in the service/artifact layer. Future planning snapshots the resolved EPW and linked provenance, stores an inspectable plan, and submits through the same durable jobs used for weather. The current morph and hourly-archive generators remain separate. REST/CLI stay thin; Stage 4 owns the MCP contract.

**Tech stack:** Existing Python/Pydantic, EPW/QC, artifact store, jobs/SQLite, CMIP6 and WRF optional readers, pytest/Ruff/mypy. No new future backend or compulsory climate dependency.

**Spec:** [Coordinated stages](2026-09-25-mcp-remaining-stages.md), [program allocation](../../plans/2026-09-24-production-mcp-program.md), [future method contract](../../methods/future-weather.md), [Stage 3a plan](2026-09-25-mcp-stage-3a-weather-fetch.md).

## Guardrails and review focus

- Preserve one immutable baseline artifact ID and checksum for either path. A fetched baseline additionally links the exact weather output, source manifest and QC. Unknown external EPW origin stays unknown; do not manufacture provider/source metadata.
- Validate annual completeness and method-required variables before describing an output as viable. NOAA sentinel-bearing gaps or `None`/NaN fields cannot pass as simulation ready. Keep `missing_policy` results from Stage 3a visible.
- `morph` is monthly CMIP6/local-signal shift/stretch of baseline hours, with SSP and explicit reference/target windows. `climate_profile` selects full hourly WRF trajectories at supported PUMA sites, with RCP and exact archive windows; its input EPW is a comparison identity, not the transformed sequence. Do not map RCP4.5 to SSP245.
- Future target year is shorthand for a climate window, not a single-year forecast. Retain actual baseline date semantics, TMY source/reference meaning, original source calendar and per-variable lineage. Never silently change geography, truncate periods or insert a leap day.
- Existing v0.1 future plan JSON/hashes, direct Python local-path convenience and current successful outputs remain readable. Prefer additive optional fields and migration-free artifact linkage.
- A fetched OpenEPW weather artifact ID is used directly as one baseline path. A user-provided EPW is uploaded or registered as a checksummed artifact before planning. Trusted Python/CLI may accept a local path; REST accepts bounded upload; Stage 4 defines bounded MCP upload and optional allowlisted-path registration. Future planning/execution on REST/MCP uses opaque artifact IDs, never an arbitrary raw path. Avoid path traversal or credential-bearing paths in results.
- The merged CMIP6 license-scope analysis screens 636 pinned catalog combinations against the effective WCRP model-license registry, but does not establish requested-window coverage, geographic footprint or original-store redistribution rights. The current Stage 2 importer uses registry license fields and does not consume derived `license_scope`. At preflight, use the derived local field only when present with valid accepted inputs; otherwise use independently available accepted registry evidence or return `unknown`. Keep original store license text separate and do not regenerate Stage 1 snapshots implicitly.

## Files and interfaces

| Area | Planned responsibility |
| --- | --- |
| `src/openepw/models/__init__.py` | Optional typed `BaselineRef`/future plan-output metadata; preserve legacy serialized hashes. |
| `src/openepw/artifacts/store.py`, `src/openepw/planning/future.py` | Idempotent checksum-verified baseline registration and resolution; snapshot provenance/QC when a fetched EPW is used. |
| `src/openepw/service.py`, `src/openepw/jobs/{worker,store}.py` | Stored future plan reference, durable future output items, partial/retry/cancel behavior. |
| `src/openepw/generation/{morph,hourly_archive,climate_profile}.py` | Only focused fixes exposed by the two-path tests; retain separate methods. |
| `src/openepw/api/app.py`, `src/openepw/cli/main.py` | Thin registration, plan-by-hash, job and artifact access; no future science. |
| `tests/unit/test_stage3b_*.py` | Deterministic local/fetched baselines, scenario/window/method, QC and recovery acceptance. |

The typed baseline reference carries artifact ID, SHA-256, origin (`user_provided` or `weather_output`), optional registration route (`upload` or `allowlisted_path`), optional source output/manifest/QC artifact IDs and input QC summary. It is an artifact relationship, not a claim that the external EPW's header identifies its provider. A future plan stores this resolved reference and method/scenario/window choices; a future manifest records the same IDs, source/calendar semantics, per-variable transformations and QC. Existing `FutureRequest.baseline` strings remain accepted and are normalized at planning.

The anchor is one study location with two baseline paths: (i) a synthetic complete annual EPW uploaded as a user file and (ii) Stage 3a anchor A's fetched weather artifact selected by ID, both with explicit reliable reference-period information. Run supported `morph` SSP245 2036–2065 with synthetic coherent monthly signals through both paths. Independently run a supported `climate_profile` RCP8.5 2045–2054 PUMA case with a bounded synthetic archive; do not imply both methods have the same geographic footprint. Contrast SSP245 on `climate_profile`, RCP8.5 on `morph`, an unsupported site/window and a gapped NOAA baseline. Offline synthetic fixtures provide deterministic acceptance; bounded live smoke follows the coordinated budget and never modifies `.env`.

**Stage 3a handoff adjustment (2026-09-25):** The executed Stage 3a actual-year
anchor verified 8,784 intervals and mapping with a deliberately sparse two-variable
synthetic provider. Its resulting EPW is a QC-limited negative baseline case. For
the positive fetched-artifact-ID path in this stage, run the same Stage 3a
plan → job → artifact flow with a complete annual synthetic provider at the study
location. This preserves the accepted Stage 3a result while testing the stricter
future preflight; do not treat 8,784 rows alone as sufficient baseline quality.

### Task 1: Baseline registration and scientific preflight

**Files:** Modify `artifacts/store.py`, `planning/future.py`, `models/__init__.py`; add `tests/unit/test_stage3b_baselines.py`.

- [ ] Write failing tests for user EPW upload and local-path registration, fetched weather artifact ID resolution, checksum mutation, mismatched source manifest link, duplicate registration, annual gap/critical-variable failure, an external EPW with unknown provider, and a Stage 3a NOAA sentinel output. Assert source coordinates and per-variable lineage from a fetched baseline are retained without replacing requested location.
- [ ] Implement a service-level resolver that uses artifact IDs for untrusted adapters and safely snapshots trusted local paths for Python/CLI. Pin input bytes/QC and linked fetched provenance in the future plan; verify all linked checksums again at execution. Preflight completeness/variables and return typed `INVALID_BASELINE` or `MISSING_CRITICAL_VARIABLE` with QC details instead of proceeding silently.
- [ ] Run focused tests plus `tests/unit/test_future.py`; commit `fix(future): register and validate baseline artifacts`.

### Task 2: Complete future plan semantics and stored references

**Files:** Modify `planning/future.py`, Stage 3a `planning/store.py`, `service.py`; add `tests/unit/test_stage3b_plans.py`.

- [ ] Write failing tests for equivalent local/fetched baseline identity, stored future plan retrieval by hash, old future plan replay, explicit reference/target windows, target-year shorthand, climate scenario and model/member selectors. Include a pinned allowed CMIP6 model license with an unverified climate window, missing/stale model-license evidence, and an original store term that differs from the effective registry license. Verify plan warnings and resource estimates survive serialization; unsupported combinations are rejected before job submission.
- [ ] Extend the Stage 3a plan store to future plans using the same `plan_hash` integrity rules. Keep registered baseline/signal snapshot IDs in executable plans, while output identity is based on stable input checksums and scientific choices. Record method-specific eligibility and uncertainty without promising the source archive contains complete hours merely because metadata lists it.
- [ ] Run focused tests plus `tests/unit/test_future.py tests/unit/test_hourly_future.py`; commit `fix(planning): persist inspectable future plans`.

### Task 3: Output-level durability, QC and provenance

**Files:** Modify `planning/future.py`, `jobs/worker.py`, `service.py` and any generator exposed by a failing case; add `tests/unit/test_stage3b_execution.py`.

- [ ] Write failing tests for both baseline paths and both methods, two-member morph ensemble with one invalid member, cancellation after a completed output, process restart, failed-output retry, corrupted artifact refusal, and source-fetch failure. Assert completed members remain inspectable where the source has produced them; an upstream source failure may fail all dependent outputs with explicit shared cause.
- [ ] Execute and persist member/profile outputs independently where the existing generator can produce coherent units without re-fetching. Keep output index/ID, method, model/member or source year, scenario/window, baseline artifact and input/output QC on every result. A generated EPW gets a weather artifact only after structural QC; a QC-limited result is never promoted to simulation ready. Preserve existing bundle/manifest keys.
- [ ] Run focused tests, the future/job regression tests and a full round-trip `read_epw` of each synthetic output; commit `fix(future): retain future output outcomes and lineage`.

### Task 4: Adapter parity and bounded offline acceptance

**Files:** Modify `api/app.py`, `cli/main.py`; add focused adapter tests; create `docs/validation/mcp-stage-3b-acceptance.md`; update `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/limitations.md`, `docs/methods/future-weather.md`.

- [ ] Write failing REST/CLI tests for uploading a bounded user EPW, registering a trusted local-path baseline, reusing a fetched artifact ID, planning by artifact ID, submitting a stored future plan, inspecting member-level job/QC/artifact results and refusing raw paths in remote requests. Check that sensitive paths/tokens and hourly arrays do not appear in ordinary JSON.
- [ ] Add thin adapter routing only. Run the anchor matrix with synthetic CMIP6 signals and WRF archive responses, including both baseline paths, method/scenario contrast and the NOAA gap; record which cases are offline versus opt-in live.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/unit -q`, Ruff, mypy and wheel/sdist build; document actual results and source-dependent limitations. Review the branch against this plan and fix material findings; commit `fix(docs): record Stage 3b acceptance`.

## Exit and Stage 4 handoff

Stage 3b exits when both baseline paths produce checksum-linked, QC-inspectable future artifacts through durable jobs; both distinct methods work on their own supported footprints; unsupported method/scenario/window/site and incomplete-baseline cases are explicit; old future plans remain usable; and Python/REST/CLI report the same IDs and limits. Stage 4 consumes these service contracts without rebuilding future logic.
