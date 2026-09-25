# MCP Stage 3a Weather Fetch, Batches and Artifacts Implementation Plan

Status: owner approved autonomous Stages 3a–6 implementation on 2026-09-25 by instructing "start now" after plan review. Work in the checked-out `feature/mcp` repository branch without routine stage gates; preserve the other contributor's separate worktree and branch.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task by task in the repository checkout, with failing tests before code and a whole-branch review at the end. Checkboxes track execution. Do not begin until the owner approves this plan.

**Goal:** Complete inspectable historical/published-weather planning and durable one-to-many batch execution, with an explicit compact export and a truthful result for every requested occurrence.

**Architecture:** The Python service remains canonical. A plan records one row per requested occurrence × selected dataset × requested period, including unsupported rows; only executable rows create fetch tasks and output specs. Exact verified source requests can share a task while requested outputs keep distinct identities. Durable plan references and jobs use the existing local filesystem/SQLite and artifact store; REST/CLI are thin consumers, and Stage 4 owns final MCP tools.

**Tech Stack:** Python 3.11+, Pydantic 2, standard-library SQLite/CSV/ZIP/filesystem, existing `WeatherService`, `JobRunner`, `ArtifactStore`, pytest, Ruff, mypy. No new mandatory service or provider SDK.

**Spec:** The owner-reviewed [program plan](../../plans/2026-09-24-production-mcp-program.md), [ADR 0003 batch semantics](../../decisions/0003-mcp-availability-and-batches.md), [Stage 2 acceptance](../../validation/mcp-stage-2-acceptance.md), and [earlier staged design](../specs/2026-09-23-mcp-stages.md). The program plan controls where the stages end; this document specifies Stage 3a only.

## Global constraints

- Stage 1 collection stays closed. Use the accepted local catalog if present; a missing catalog remains an explicit unknown. The merged NSRDB `tdy-2023` grid is map display evidence only and is not in the active catalog. Do not use its generalized cells to upgrade arbitrary-point or actual-year eligibility. Preserve accepted annotations and local snapshots; any optional source-grid import requires a separate selector-bound review and new catalog generation.
- A catalog `supported` outcome means eligible to try retrieval, never complete hourly weather or simulation readiness. Do not silently shorten periods, fill gaps, replace a failed source, or promote a syntax-valid EPW.
- Preserve actual-year dates, TMY reference meaning, fixed standard time, leap policy, source coordinates, per-variable lineage, QC, raw checksums and existing plan/artifact replay. Old `WeatherPlan` JSON and hashes must still validate.
- One input occurrence may yield zero, one or several output intents. Duplicate requested points remain separate; source task count, output-intent count and emitted EPW count are different numbers.
- Reuse a fetch only for the same verified native source/product, period, query point or station identity, variables and provider options. Exact OneBuilding product URL may share the native retrieval; accepted alternate-URL annotations and coordinate proximity alone may not. Do not infer Open-Meteo grid-cell equality before fetch.
- The default continues to emit a distinct EPW artifact for each successful requested output. Compact export is explicit and local; it does not establish redistribution rights. Never include full third-party inventories or weather fixtures in Git or the wheel.
- Preserve one-process-per-data-root job semantics and existing raw HTTP cache. A job-local shared-task memo is allowed; previous-run weather/QC reuse remains deferred.
- Use `fix(topic): concise description` commits with configured human authorship. No force push, destructive history rewrite, new worktree, or new approval gate after Stage 3a approval for routine choices.
- `.env` is read-only and may be loaded into process memory for an approved bounded live smoke; never modify or stage it. Keep cumulative billable API usage below US$10 across Stages 3a–6 and stop new calls at a US$8 projected total, as recorded in the coordinated plan. Offline acceptance does not use credentials.

## Review focus

1. Two identical input points, including duplicate `Location.id`, must have different occurrence rows and output IDs; a failed or unsupported one must not disappear behind the other's location key. Task 1 and Task 2 test this.
2. A provisional nearby grid cell or Hawaiian alternate product URL must not become a shared fetch; exact native OneBuilding URL and verified NOAA station identity may share under matching options. Task 2 tests this.
3. One NOAA hourly gap must remain an EPW sentinel plus QC warning with `missing_policy="warn"`; with `"error"`, that output has no EPW while unrelated batch outputs succeed. Task 4 tests this.
4. Restart after one completed output must keep its verified artifact and mapping; explicit retry must select only missing/failed output identities and preserve rejected occurrence rows. Task 5 tests this.
5. Compact export must map every occurrence, including failures, while containing one weather member per genuinely equivalent successful output. Task 6 tests this.

## Design choices and interface order

| File | Responsibility |
| --- | --- |
| `src/openepw/models/__init__.py` | Add optional occurrence-aware plan/discovery records without changing old serialized plan hashes. |
| `src/openepw/planning/batch.py` | Pure task-equivalence, row validation and final batch-summary rules. No server/MCP imports. |
| `src/openepw/planning/store.py` | Atomic, content-addressed local `WeatherPlan` persistence keyed by existing `plan_hash`. |
| `src/openepw/service.py` | Bind Stage 2 occurrence evidence to selections, generate executable tasks, preserve output/QC mapping and expose plan references. |
| `src/openepw/jobs/worker.py` | Run output items durably, share verified task results only within one active job, retain failure identity across restart/retry. |
| `src/openepw/artifacts/export.py`, `artifacts/store.py` | Stream an explicit compact ZIP and register it as a checksummed local artifact. |
| `src/openepw/api/app.py`, `src/openepw/cli/main.py` | Accept a stored plan hash and request compact export through the same service/job methods. MCP names and conversation flow wait for Stage 4. |

The new `BatchRow` records `occurrence_index`, `requested_location_id`, `dataset_selection`, inclusive `period_start`/`period_end` for actual weather (both null for a published product), `status` (`planned`, `unsupported` or `unresolved`), `candidate_id`, `task_ids`, `output_id`, and issue codes. A known exclusion is unsupported; missing/stale evidence or unsuccessful discovery is unresolved. There is one row for each requested combination. `WeatherPlan.batch_rows` and `DiscoveryResult.candidate_ids_by_occurrence` are optional, omitted when empty so legacy JSON keeps its hash. An output's new optional `occurrence_index` is similarly omitted in legacy plans. Execution adds `manifest.batch_rows` with final `succeeded`, `failed`, `unsupported`, `unresolved` or `cancelled` status; it retains existing `outputs` and `output_mapping` fields. Failed rows have no artifact ID. No source or request coordinates are substituted in output lineage.

`plan_hash` is also the durable plan reference. `PlanStore.put(plan: WeatherPlan) -> str` atomically saves JSON under `data_root/plans/<plan_hash>.json`; `get(plan_hash: str) -> WeatherPlan` validates the 64-hex identifier, file contents and recomputed hash. `WeatherService.plan` stores newly made weather plans; existing callers can still pass the full plan to execution. `JobRunner.submit` accepts either a validated plan or an existing hash. REST/CLI expose this without changing the meaning of existing inline-plan inputs.

`WeatherJob.total/completed/failed` continue counting executable output items. The manifest adds separate requested-occurrence, output-intent, shared-task, unsupported, unresolved and emitted-artifact counts. A job with successful executable outputs but any unsupported/unresolved intent is `partially_completed`; a plan with no executable output cannot be submitted as a job. This keeps job state truthful without mislabeling an unknown as a fetch failure.

The Stage 3a anchor matrix is fixed for acceptance: (A) a full actual-year 2024 Ithaca point with one selected dataset and an explicit alternative; (B) a published OneBuilding TMYx batch with two requested points resolving to the same exact product URL, a duplicate occurrence, and one unsupported point. Synthetic HTTP/provider responses make both anchors deterministic. An optional live smoke may fetch one bounded actual interval and one explicitly named published product if provider access/terms permit; it supplements, never replaces, offline acceptance. The sparse NOAA case is a separate deterministic variant of A and carries forward to Stages 4–6.

---

### Task 1: Occurrence-aware discovery and plan records

**Files:** Modify `src/openepw/models/__init__.py`, `src/openepw/service.py`; create `tests/unit/test_stage3a_occurrences.py`.

**Interfaces:** Add `BatchRow(Model)`, `Issue.occurrence_index: int | None`, `OutputSpec.occurrence_index: int | None`, `WeatherPlan.batch_rows: list[BatchRow]`, and `DiscoveryResult.candidate_ids_by_occurrence: list[list[str]]`. Optional fields use `exclude_if` for absent legacy values. `WeatherPlan.valid` checks that each planned row references exactly one output and that unsupported/unresolved rows reference no output. If distinct points share an explicit `Location.id`, disambiguate colliding new candidate IDs by occurrence while retaining each supplied ID as a label; do not reject a previously valid request. Preserve the current `plan_hash` algorithm for old JSON.

- [ ] **Step 1: Write failing model/discovery tests.** Use two equal `Location` values and, separately, two different coordinates carrying the same explicit `Location.id`. Assert discovery has indexed candidate lists for both occurrences, distinct candidate IDs where they would otherwise collide, old serialized plans round-trip with the same hash, and invalid duplicate/missing row-to-output references fail validation. For example:

  ```python
  points = [Location(lat=1, lon=0), Location(lat=1, lon=0)]
  request = WeatherRequest(locations=points, start="2024-01-01", end="2024-01-01")
  discovery = service.discover(request)
  assert len(discovery.candidate_ids_by_occurrence) == 2
  assert all(discovery.candidate_ids_by_occurrence)
  ```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_stage3a_occurrences.py -q`; confirm failures are missing occurrence fields/validation, not fixture errors.
- [ ] **Step 3: Add typed fields and populate the discovery map.** Build the map by enumeration during both catalog-backed and live discovery. Do not use `Location.key` as the occurrence identifier; use it only as the requested-location label. Keep candidate IDs stable when unique; add a deterministic occurrence suffix only for collisions.
- [ ] **Step 4: Run the focused test plus `tests/unit/test_models.py tests/unit/test_availability_service.py`; confirm old JSON/hash compatibility. Commit with `fix(planning): retain discovery occurrences`.

### Task 2: Partial planner and verified fetch equivalence

**Files:** Create `src/openepw/planning/batch.py`, `tests/unit/test_stage3a_planning.py`; modify `src/openepw/service.py`, `src/openepw/models/__init__.py` only where Task 1's records require it.

**Interfaces:** `fetch_task_key(source: SourceRef, parameters: dict[str, Any]) -> str` uses the existing digest format for legacy tasks; newly planned exact OneBuilding URL tasks omit irrelevant requested-location parameters, while point/grid tasks retain the exact query location and options. `WeatherService.plan(request, discovery=...) -> WeatherPlan` emits all planned/unsupported/unresolved rows and only executable `OutputSpec`s. An all-nonexecutable request returns an inspectable plan with zero tasks/outputs; execution and job submission reject it with `NO_EXECUTABLE_OUTPUTS` without a provider call.

- [ ] **Step 1: Write failing planning tests** for duplicate occurrence rows, one unsupported location alongside one success, a stale-evidence unresolved location, all nonexecutable, multiple datasets/years, exact OneBuilding URL reuse, NOAA same station with different fixed offsets, and provisional Open-Meteo near points. Assert no fallback provider or shortened period. Example:

  ```python
  plan = service.plan(request, discovery=discovery)
  assert [r.occurrence_index for r in plan.batch_rows] == [0, 1, 2]
  assert [r.status for r in plan.batch_rows] == ["planned", "planned", "unsupported"]
  assert len(plan.outputs) == 2
  assert len(plan.tasks) == 1  # same exact published URL, not a coordinate guess
  ```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_stage3a_planning.py -q`; confirm the row/reuse expectations fail on the current planner.
- [ ] **Step 3: Implement the bounded planner changes.** Iterate `enumerate(discovery.locations)` and requested selections/periods; use Task 1's occurrence candidate list, classify no-candidate rows from Stage 2 evidence as excluded versus unknown, attach an `Issue` with the same index, and continue. Keep `OutputSpec.id` based on occurrence, source tasks, period and transforms. Preserve current fetch-key validation when replaying old plans; validate the new published-product task shape without inventing a dummy location.
- [ ] **Step 4: Run the focused test plus `tests/unit/test_batch.py tests/unit/test_service.py`; commit with `fix(planning): complete partial weather batches`.

### Task 3: Durable, tamper-checked plan references

**Files:** Create `src/openepw/planning/store.py`, `tests/unit/test_stage3a_plan_store.py`; modify `src/openepw/service.py`, `src/openepw/jobs/worker.py`, `src/openepw/api/app.py`.

**Interfaces:** `PlanStore(root: Path).put(plan: WeatherPlan) -> str` and `.get(plan_hash: str) -> WeatherPlan`. `WeatherService.plan` saves the returned weather plan. `JobRunner.submit(plan: WeatherPlan | str, idempotency_key=None, retry_of=None)` resolves a hash via this store before calling existing `JobStore.submit`; a stored hash is accepted for weather plans only, while existing inline future-plan submission remains unchanged. REST `JobSubmission` accepts exactly one of `plan` or `plan_hash`; `/v1/weather/plan` still returns a `WeatherPlan` whose `plan_hash` is now resolvable. `/v1/future/jobs` continues to require an inline future plan. Do not extend stored references to future plans until Stage 3b.

- [ ] **Step 1: Write failing tests** for put/get across service restart, malformed/unknown hash, tampered stored JSON, REST submission by hash, rejection of an all-nonexecutable plan, and inline-plan backward compatibility. Example:

  ```python
  plan = first.plan(request)
  restored = WeatherService(RuntimeConfig(data_root=tmp_path)).plan_store.get(plan.plan_hash)
  assert restored.plan_hash == plan.plan_hash
  assert restored.model_dump(mode="json") == plan.model_dump(mode="json")
  ```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_stage3a_plan_store.py -q`; confirm missing store/reference behavior fails.
- [ ] **Step 3: Implement atomic storage and resolution.** Reject IDs outside `[0-9a-f]{64}`; revalidate `WeatherPlan` and its hash on read; return `PLAN_NOT_FOUND` or `PLAN_STALE` without echoing file content. Store only the plan JSON under the configured local data root. Keep the existing 5 MB REST request cap and idempotency conflict behavior.
- [ ] **Step 4: Run focused tests plus `tests/unit/test_api.py tests/unit/test_jobs.py`; commit with `fix(planning): persist executable plan references`.

### Task 4: Complete execution manifest, QC and failure mapping

**Files:** Create `tests/unit/test_stage3a_execution.py`; modify `src/openepw/planning/batch.py`, `src/openepw/service.py`, `src/openepw/jobs/worker.py`, and extend `tests/unit/test_noaa_gap_output.py`.

**Interfaces:** `finalize_batch_rows(plan: WeatherPlan, manifest_outputs: list[dict], issues: list[Issue], cancelled: bool) -> list[dict]` produces one final row per `BatchRow`; `WeatherService._bundle` writes it to `manifest.batch_rows` while retaining existing manifest keys. A successful row links output and artifact IDs, task IDs, native source coordinates, lineage/QC references; failed/unsupported/unresolved/cancelled rows link issues and carry no weather artifact. Legacy plans without `batch_rows` continue using the old manifest shape. `JobRunner.subplan` retains only selected planned rows; the final job bundle uses the original plan to restore all unsupported and unresolved rows.

- [ ] **Step 1: Write failing tests** for mixed success/unsupported/unresolved/fetch failure, duplicated locations, nonidentical source vs requested coordinates, and the NOAA sparse-report variant. Under `warn`, check sentinel EPW, `MISSING_CRITICAL_VARIABLE`, `simulation_ready=false` and a succeeded but QC-limited row. Under `error`, check no EPW for that row while another location succeeds. Example:

  ```python
  manifest = json.loads((tmp_path / bundle.manifest.path).read_text())
  assert len(manifest["batch_rows"]) == len(plan.batch_rows)
  assert {r["status"] for r in manifest["batch_rows"]} == {"succeeded", "failed", "unsupported", "unresolved"}
  assert manifest["simulation_ready"] is False
  ```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_stage3a_execution.py tests/unit/test_noaa_gap_output.py -q`; confirm absence of complete mapping is the failure.
- [ ] **Step 3: Implement finalization and bind issues to output/occurrence IDs.** A task fetch failure maps through dependent output task IDs; an unexpected job exception records its output ID. Retain raw `outputs`, `output_mapping`, source metadata, variable lineage and QC artifacts. Do not write `None`/`NaN` text into EPWs or mark any output simulation-ready.
- [ ] **Step 4: Run focused tests plus `tests/unit/test_batch.py tests/unit/test_jobs.py`; commit with `fix(artifacts): record every batch outcome`.

### Task 5: Job-local shared fetch and durable partial recovery

**Files:** Create `tests/unit/test_stage3a_jobs.py`; modify `src/openepw/service.py`, `src/openepw/jobs/worker.py`, `src/openepw/jobs/store.py` only if persistence gaps are demonstrated by the failing tests.

**Interfaces:** `WeatherService.execute(..., task_results: dict[str, ProviderResult] | None = None)` accepts an optional job-local cache; direct callers retain current behavior. `JobRunner.run` creates the cache per job, stores a result only for tasks needed by multiple pending outputs, and evicts it after the final dependent output. It never treats a provisional candidate as a shared task and never persists normalized weather as a cross-run availability source. Existing raw HTTP caching and verified artifact restart behavior remain.

- [ ] **Step 1: Write failing tests** showing two outputs sharing one verified task invoke the provider fetch once within a job; different transform/output semantics still produce two artifacts; a job with successful outputs plus unsupported/unresolved rows is `partially_completed`; a worker restart keeps an already verified artifact; a corrupted artifact is retried; a strict missing-data failure is mapped and `retry_failed` selects only failed output IDs. Example:

  ```python
  runner.run(job.id)
  final = store.get(job.id)
  assert provider.calls == 1
  assert final.completed == 2
  assert len({ref.id for ref in final.bundle.weather}) == 2
  ```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_stage3a_jobs.py -q`; confirm the job currently refetches a shared task or loses an outcome.
- [ ] **Step 3: Add job-local reuse and recovery accounting.** Never mutate a cached `ProviderResult` when applying leap/hybrid/output transforms; copy the dataset where needed. On restart, skip only checksum-verified completed artifacts. Preserve failed item identity and issue codes; do not automatically substitute a new provider or revive a cancelled output.
- [ ] **Step 4: Run focused tests plus the full `tests/unit/test_jobs.py`; commit with `fix(jobs): reuse verified tasks within a batch`.

### Task 6: Explicit compact export

**Files:** Create `src/openepw/artifacts/export.py`, `tests/unit/test_stage3a_export.py`; modify `src/openepw/artifacts/store.py`, `src/openepw/jobs/worker.py`, `src/openepw/api/app.py`, `src/openepw/cli/main.py`.

**Interfaces:** `JobRunner.export_compact(job_id: str) -> ArtifactRef` accepts a finished weather job and registers a local `application/zip` artifact. The ZIP contains `mapping.csv`, `manifest.json`, `qc.json`, and one normalized `.epw` per successful equivalence group. Each mapping row has occurrence index, requested location, dataset/product, period, final status, output ID, source task IDs, original artifact ID, compact member name or blank, and issue codes. Group only when task IDs, transform/missing/leap semantics, source lineage and output SHA-256 agree; never group by proximity or filename alone. Use streaming ZIP creation to a temporary file and atomic registration; no full-archive in-memory buffer. Native ZIPs/raw responses are excluded.

- [ ] **Step 1: Write failing export tests** for the published batch anchor, a failed row, differing transforms, malicious/long member names, repeat export, and corrupted artifact refusal. Example:

  ```python
  ref = runner.export_compact(job.id)
  _, path = service.artifacts.resolve(ref.id)
  with zipfile.ZipFile(path) as archive:
      assert archive.namelist().count("mapping.csv") == 1
      assert len([n for n in archive.namelist() if n.endswith(".epw")]) == 1
      assert len(list(csv.DictReader(archive.read("mapping.csv").decode().splitlines()))) == 4
  ```

- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/unit/test_stage3a_export.py -q`; confirm compact export is unavailable.
- [ ] **Step 3: Implement local ZIP/export registration.** Resolve each input artifact by its checksum before adding it, derive safe member names from output IDs, write mapping/provenance without credentials, keep failed rows blank, and report `EXPORT_UNAVAILABLE` for unfinished/future jobs. Repeating export must not change scientific mapping or append duplicate references. Expose a thin REST export action and CLI `export <job-id>`; leave the final MCP tool contract to Stage 4.
- [ ] **Step 4: Run focused tests plus `tests/unit/test_security.py tests/unit/test_api.py`; commit with `fix(artifacts): add explicit compact weather export`.

### Task 7: Cross-surface acceptance and documentation

**Files:** Create `docs/validation/mcp-stage-3a-acceptance.md`; modify `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/limitations.md`, `docs/decisions/0003-mcp-availability-and-batches.md`, and relevant provider notes under `docs/providers/`; add focused REST/CLI tests in the existing adapter test files.

**Interfaces:** Python, REST and CLI refer to the same plan hash, batch statuses, artifact IDs and compact export. The current MCP adapter may keep its v0.1 full-plan inputs until Stage 4; do not add protocol-specific weather logic here.

- [ ] **Step 1: Write failing adapter tests** for plan-by-hash submission, inspection of partial rows, compact ZIP artifact retrieval and a CLI execution by stored hash. Verify no EPW hourly table appears in ordinary JSON responses and no credential appears in errors or manifests.
- [ ] **Step 2: Run the focused adapter tests and confirm the missing surface behavior.** Then make only thin routing/serialization changes needed by these tests.
- [ ] **Step 3: Run** `.venv/Scripts/python.exe -m pytest tests/unit -q`, `.venv/Scripts/python.exe -m ruff check src tests`, `.venv/Scripts/python.exe -m mypy src/openepw`, and `.venv/Scripts/python.exe -m build`. Run the two offline anchors and NOAA gap case through plan → job → artifact inspection → optional compact export. Record actual counts, QC, limitations and any skipped live checks in the acceptance document. Opt-in live runs are bounded and tagged; credential-gated providers are not claimed live accepted without credentials.
- [ ] **Step 4: Review the whole branch against this plan and ADR 0003, fix material findings with focused regression tests, then commit documentation with `fix(docs): record Stage 3a acceptance`. Do not mark the stage complete until every acceptance claim has a corresponding executed check.**

## Exit criteria and next handoff

Stage 3a is complete when the two offline anchors and sparse NOAA case produce a row for every requested occurrence/selection/period; shared native requests are fetched once within a job where verified; unsupported, unresolved and failed outputs are distinct; old plans/artifacts still replay; restart and retry preserve successful artifacts; compact export has a complete mapping and safe unique weather members; and Python/REST/CLI agree on plan and artifact identities. Report source access and QC limits honestly. Stage 3b then consumes these fetched EPWs as baseline artifacts; Stage 4 chooses the final MCP tool contract.
