# MCP Stage 2 Availability and Recommendation Implementation Plan

Status: approved for autonomous implementation by the owner on 2026-09-24 and implemented on the checked-out `feature/mcp` branch. The original task checkboxes below are retained as the reviewed execution plan; the [acceptance record](../../validation/mcp-stage-2-acceptance.md) and commit history record actual completion, review fixes and deviations.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task by task in the repository checkout on `feature/mcp`. Inline execution is the handoff's preferred approach; finish with one independent whole-branch review. Checkboxes track work. Implementation starts only after the owner reviews this plan.

**Goal:** Add a local, evidence-preserving availability catalog and purpose-based recommendations in the canonical Python service, with each requested occurrence assessed separately, without repeating MCP Stage 1 collection. Stage 4 will settle the final MCP tool contract.

**Architecture:** Immutable SQLite catalog generations and ignored raw metadata files feed source-specific importers. A pure eligibility evaluator and deterministic ranker return typed facts; `WeatherService` owns orchestration and current transport adapters serialize its results. Existing plan, output, artifact and cache identities stay compatible.

**Tech Stack:** Python 3.11+, Pydantic 2, SQLite standard library, httpx through existing `HttpClient`, pytest, Ruff, mypy. No new mandatory service, GIS or climate dependency.

**Spec:** [MCP Stage 2 design](../specs/2026-09-24-mcp-stage-2-availability-design.md). Also read [accepted ADR 0003](../../decisions/0003-mcp-availability-and-batches.md), [Stage 1 findings](../../validation/mcp-stage-1/README.md), [catalog proposal](../../validation/mcp-stage-1/catalog-contract.md), [accepted case review](../../validation/mcp-stage-1/onebuilding-manual-review.md) and [agent handoff](../../handoffs/2026-09-24-mcp-stage-2.md).

## Global constraints

- This MCP Stage 2 is distinct from the already completed v0.1 Stage 2. Record owner plan approval in this plan before implementation; no elapsed-time approval.
- Work on `feature/mcp` in the repository checkout, inspect status/recent commits before edits, preserve its ignored `.local/mcp-availability/`, and never run `collect` as part of this plan. Do not move/delete another agent's worktree or overwrite an active local catalog.
- Python service is canonical. No FastAPI/MCP/xarray imports in the availability scientific core. Keep REST/MCP as thin adapters.
- Preserve actual-year, TMY-reference and future-window semantics; source and adapter capabilities remain distinct. `supported` means eligible to attempt retrieval, not complete weather or simulation ready.
- Preserve the 56 reviewed OneBuilding metadata matches, three approximate localities, two name/code conflicts, original strict matches and all source checksum pins. Do not infer archive/EPW equivalence, source identity, elevation or redistribution rights.
- Treat stale/incomplete evidence as `unknown` unless a stable, independent adapter incompatibility excludes. Separate access/terms/health from scientific eligibility.
- No full third-party indexes or weather files in git/wheels without source-specific redistribution permission. Synthetic offline fixtures are the default.
- Use `fix(topic): concise description` commits with configured human authorship. No `codex/` branch, agent trailer, force push, destructive reset or published-history rewrite.
- Existing v0.1 request/plan hashes and artifact references must round-trip. Do not silently shorten requested periods, switch providers, or collapse output occurrences.
- Stage 2 reports possible shared station/source candidates for each input occurrence, including provisional identity. Stage 3a owns verified retrieval equivalence, complete batch/output mapping, and new execution-planning rules; Stage 3b owns future generation workflows.
- Another agent's NSRDB and availability follow-up on a separate branch is independent. Incorporate its evidence only after review as a new catalog generation; do not block on it or discard the accepted Stage 1 baseline.

## Review focus

1. A NOAA station's `BEGIN`/`END` spans a requested year but the sparse count inventory lacks it: report `unknown`, never fabricate every intervening year. Task 5 pins this.
2. A valid OneBuilding reviewed Hawaii URL has changed source bytes: original strict match remains, accepted coordinates become stale/unresolved. Task 3 pins this.
3. CDS says “global” but its bbox stops at ±89°, and ERA5-Land has no land mask: polar/land boundary requests remain `unknown`. Tasks 4 and 5 pin this.
4. A cached OEDI directory has a new ETag: previously listed members/offsets cannot support the new archive. Tasks 2 and 4 pin this.
5. Fresh local metadata for 100 points: source-wide refresh runs at most once, and provider weather discovery is not called for known decisions. Tasks 2 and 6 pin this.

## File map and interface order

| File | Responsibility |
| --- | --- |
| `src/openepw/availability/models.py` | Tagged catalog, evidence, query, per-occurrence assessment, eligibility and recommendation wire records. |
| `src/openepw/availability/store.py` | SQLite schema, immutable generation staging/activation and pinned read views. |
| `src/openepw/availability/stage1.py`, `availability/data/onebuilding_reviews.json` | Strict local import of Stage 1 `analysis.json`, ledger/raw checksums and a packaged exact copy of the accepted review registry; no network. |
| `src/openepw/availability/importers/{noaa,onebuilding,climate,contracts}.py` | Source-specific normalization and validation of later snapshots, keeping native semantics. |
| `src/openepw/availability/refresh.py` | Bounded, conditional, decision-relevant source refresh and stale fallback. |
| `src/openepw/availability/evaluate.py` | Pure three-valued geographic/temporal/variable/future evaluation. |
| `src/openepw/availability/recommend.py` | Study-purpose variable priorities and explained deterministic ordering. |
| `src/openepw/service.py`, `src/openepw/models/__init__.py`, provider `discover` methods | Narrow shared-service discovery integration and compatibility. |
| `src/openepw/api/app.py`, `src/openepw/mcp/server.py`, `src/openepw/cli/main.py` | Existing discovery adapters consume shared results; direct REST/CLI availability access and local CLI catalog setup remain thin. Final MCP tool contract remains Stage 4. |

Core signatures, fixed here to prevent task drift:

```python
def import_stage1(root: Path) -> CatalogBundle: ...             # offline, verifies raw/ledger
def normalize_source(source: str, raw: bytes, evidence: EvidenceRef) -> CatalogBundle: ...
def evaluate(query: AvailabilityQuery, view: CatalogView) -> AvailabilityResult: ...
def rank(result: AvailabilityResult, query: AvailabilityQuery) -> AvailabilityResult: ...
def refresh_if_relevant(query: AvailabilityQuery, store: CatalogStore,
                        http: HttpClient, source_ids: set[str],
                        normalizer: Callable[[str, bytes, EvidenceRef], CatalogBundle]
                        ) -> list[Issue]: ...
class CatalogStore:
    def stage(self, bundle: CatalogBundle) -> CatalogSnapshotRef: ...
    def activate(self, generation_id: str) -> CatalogSnapshotRef: ...
    def active(self) -> CatalogView: ...
class WeatherService:
    def assess_availability(self, query: AvailabilityQuery) -> AvailabilityResult: ...
```

`CatalogBundle` has `schema_version: Literal["1"]`, `evidence: list[EvidenceRef]`, `products: list[ProductRecord]`, `sites: list[SiteRecord]`, `entries: list[AvailabilityEntry]` and `reviews: list[ReviewAnnotation]`. `CatalogView` is a read-only transaction pinned to one active generation; it closes after the assessment. The `AvailabilityResult` has `locations: list[LocationAssessment]`, `options: list[SuitabilityOption]`, `issues: list[Issue]` and `snapshots: list[CatalogSnapshotRef]`. A `LocationAssessment` holds one input occurrence index, its requested location, ranked and recommended option IDs, and unresolved mapping facts. Each `SuitabilityOption` has a query-local ID including the occurrence index and links back to a catalog product/site ID; sharing a site remains provisional unless native source identity is verified. Exact enum values and semantic rules are in the spec. Make the type names importable from `openepw.availability` and expose only `assess_availability` at the top-level Python convenience API. The repository checkout currently has `.venv/Scripts/python.exe` and the original ignored Stage 1 snapshots; verify both before execution and preserve the snapshots.

---

### Task 1: Typed catalog and query contracts

**Files:** Create `src/openepw/availability/{__init__,models}.py`; test `tests/unit/test_availability_models.py`.

**Interfaces:** Produces the exact models named in the file map, including `LocationAssessment`; consumes existing `Location`, `WeatherRequest`, `Model` and `Issue`. `WeatherAvailabilityQuery` and `FutureAvailabilityQuery` use a discriminated `kind` field; `AvailabilityQuery` is their union. A `TemporalScope` union has `actual`, `tmy_reference` and `future_window` tags. Purpose is optional; omitted purpose has no study-specific preference. Assessment defaults to `refresh="never"`.

- [ ] Write failing model tests for distinct temporal tags, sparse year representation, exact future windows, string station IDs, no fabricated `0` elevation, per-occurrence option references, enum validation and JSON round-trip. Example:

  ```python
  def test_tmy_reference_is_not_actual_years():
      scope = TMYReferenceScope(kind="tmy_reference", start_year=2009, end_year=2023,
                                product_label="TMYx 2009-2023")
      assert scope.kind == "tmy_reference"
      assert "years" not in scope.model_dump()
      with pytest.raises(ValidationError):
          ActualScope.model_validate(scope.model_dump())
  ```

- [ ] Verify the existing repository environment with `.venv/Scripts/python.exe --version` and `.venv/Scripts/python.exe -m pip show openepw`; if missing, create it with `py -3.11 -m venv .venv` and `.venv/Scripts/python.exe -m pip install -e '.[dev,api,mcp,climate,cds]'`. Keep `.venv` ignored.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/unit/test_availability_models.py -q`; expect import/model failures.
- [ ] Implement records with field bounds, `extra="forbid"`, discriminators, exact stable product/site IDs, source/adapter variable separation, `retrieved_at` separate from `published_at`, checksum syntax and explicit nullable coordinates/elevation. `EligibilityDecision` must carry access and health independently. The new catalog schema version starts at `1`; do not change `WeatherRequest.schema_version="0.1"`.
- [ ] Run the focused tests, `ruff check src/openepw/availability tests/unit/test_availability_models.py`, and `mypy src/openepw/availability`; expect pass. Commit `fix(availability): define typed evidence and eligibility contracts`.

### Task 2: Immutable local store and refresh transaction

**Files:** Create `src/openepw/availability/{store,refresh}.py`; modify `src/openepw/config.py` only for optional catalog root/refresh settings; test `tests/unit/test_availability_store.py`.

**Interfaces:** Consumes Task 1 models; produces `CatalogStore.stage(bundle)`, `.activate(generation_id)`, `.active()`, and `refresh_if_relevant(query, store, http, source_ids, normalizer)`. The normalizer is injected until source importers exist in Tasks 3–4. The active manifest identifies per-source checksums, importer versions and freshness; no source body is placed in the SQLite rows.

- [ ] Write failing synthetic tests for atomic activation, failed staging, previous-generation fallback, concurrent reader pinning, source-specific staleness, missing root and changed OEDI ETag. Example:

  ```python
  def test_failed_stage_keeps_active_generation(tmp_path, minimal_bundle):
      store = CatalogStore(tmp_path)
      first = store.stage(minimal_bundle)
      store.activate(first.generation_id)
      bad = minimal_bundle.model_copy(update={"entries": [minimal_bundle.entries[0],
                                                minimal_bundle.entries[0]]})
      with pytest.raises(CatalogImportError):
          store.stage(bad)
      assert store.active().snapshot.generation_id == first.generation_id
  ```

- [ ] Run focused pytest; expect failures. Implement schema creation/migration check, staging database and same-volume atomic replacement or transactional active-pointer update, foreign keys, WAL/busy timeout and a lock per source. Reject duplicate IDs, dangling evidence and path traversal. Keep raw files in ignored local storage and reference them by SHA-256. Use a single active read view for all points in one request.
- [ ] Implement `refresh_if_relevant`: `never` performs zero HTTP; `if_needed` refreshes only a source whose staleness/unknown could alter the current decision, at most once per request, using existing bounded `HttpClient`, conditional headers, and per-source cadences from the catalog proposal. 304 retains checksum and updates checked-at; non-200, malformed, oversized or changed archive ETag does not activate a partial generation. A failed refresh returns stale data plus an issue, never an empty catalog.
- [ ] Re-run tests and static checks. Commit `fix(availability): add atomic catalog generations and bounded refresh`.

### Task 3: Offline Stage 1 import and reviewed OneBuilding evidence

**Files:** Create `src/openepw/availability/stage1.py`, `src/openepw/availability/data/onebuilding_reviews.json`, `src/openepw/availability/importers/{__init__,noaa,onebuilding}.py`; test `tests/unit/test_availability_import.py`. Read `scripts/mcp_research/{analysis,coordinates,reviews}.py` and registry, but do not make the installed package import the research script.

**Interfaces:** Produces `import_stage1(root: Path) -> CatalogBundle` and `normalize_source(...)` dispatch for NOAA/OneBuilding. Input root has `ledger.json`, `analysis.json`, and `raw/<evidence-id>.body`; the importer verifies every referenced saved raw SHA-256 before trusting normalized analysis. If raw/ledger exist but `analysis.json` does not, run the existing offline `analyze` command once and then import. An absent root raises `CatalogImportError("SNAPSHOT_MISSING")` without network access.

- [ ] Write failing synthetic tests for NOAA alphanumeric/zero-padded IDs, sparse station/year/month counts and unmatched coordinate IDs; OneBuilding exact product URLs, independent index versions, horizontal/elevation disagreement and 56/3/2 review categories. Use a small generated raw/ledger/analysis tree; do not copy source inventories into fixtures. Example:

  ```python
  def test_review_checksum_change_removes_coordinate_authority(stage1_tree):
      bundle = import_stage1(stage1_tree.root)
      reviewed = next(r for r in bundle.reviews if r.status == "reviewed_metadata_match")
      assert reviewed.coordinate_authority == "reviewed_metadata"
      stage1_tree.change_checksum(reviewed.evidence_ids[0])
      stale = import_stage1(stage1_tree.root)
      reviewed = next(r for r in stale.reviews if r.product_id == reviewed.product_id)
      assert reviewed.status == "stale_evidence"
      assert reviewed.coordinate_authority is None
  ```

- [ ] Run focused pytest; expect failures. Copy the tracked accepted registry byte-for-byte into package data and add a test comparing its SHA-256 to `scripts/mcp_research/data/onebuilding_reviews.json`. Implement source validation and import from the accepted local normalized analysis, retaining strict automatic matches beside explicit registry decisions. Compare all `source_checksums` pins in the registry; require the indexed row to parse and agree before exposing reviewed coordinates. Do not normalize region paths generically, assign approximate points as exact or resolve name/code conflicts by choosing one ID. Store original and alternate URLs; retain unknown elevation.
- [ ] Add an opt-in test marker for importing the actual ignored snapshots if present. It verifies ledger checksums and known Stage 1 counts (NOAA 154,841 station/year rows; OEDI indexes handled in Task 4; OneBuilding 56/3/2) without printing or committing rows. When absent, skip with a clear reason. No `collect` invocation.
- [ ] Run tests/static checks and `git status --short` to verify no raw/normalized inventory is tracked. Commit `fix(availability): import local NOAA and reviewed product metadata`.

### Task 4: Remaining source contracts and future inventories

**Files:** Create `src/openepw/availability/importers/{contracts,climate}.py`; extend `stage1.py`; test `tests/unit/test_availability_sources.py`.

**Interfaces:** Consumes Task 1 records; normalizes source contract metadata for Open-Meteo, PVGIS, NSRDB, CDS, CMIP6 and OEDI. `normalize_source(source, raw, evidence)` remains the only source-specific dispatch. Reuse source URLs/attribution from `docs/validation/mcp-stage-1/sources.md`, not invented metadata.

- [ ] Write failing tests for Open-Meteo ERA5 versus limited ERA5-Land adapter variables; London-only PVGIS 2005–2023/selected months; NSRDB Ithaca/Phoenix point scope and actual versus TMY IDs; CDS native 0–360 bbox with polar uncertainty; CMIP6 seven-variable coherent combinations with unknown time-window/license; OEDI exact RCP/site/year membership and ETag invalidation. Example:

  ```python
  def test_oedi_membership_is_not_weather_quality(oedi_bundle):
      entry = next(e for e in oedi_bundle.entries if e.scope.kind == "future_window")
      assert entry.scope.scenario == "rcp45"
      assert (entry.scope.start_year, entry.scope.end_year) in ((2045, 2054), (2085, 2094))
      assert entry.evidence_basis == "inventory"
      assert entry.weather_complete is None
  ```

- [ ] Run focused pytest; expect failures. Implement imports retaining raw source values, native longitude convention, precise applicability of probes and source licenses. OEDI directory membership requires matching archive ETag and does not assert the baseline archive. CMIP6 intersection does not promote all 636 combinations to license/window-supported; preserve original and effective WCRP license evidence independently.
- [ ] Extend the opt-in local import check to OEDI 2,368 sites × 20 listed future years per scenario and CMIP6 636 coherent combinations, without requiring weather chunks or a new network request. Run focused tests/static checks and commit `fix(availability): import source contracts and future membership`.

### Task 5: Three-valued eligibility and explained recommendations

**Files:** Create `src/openepw/availability/{evaluate,recommend}.py`; test `tests/unit/test_availability_evaluate.py`, `tests/unit/test_availability_recommend.py`.

**Interfaces:** `evaluate(query, view) -> AvailabilityResult` is pure and never performs I/O; `rank(result, query) -> AvailabilityResult` is pure and stable. `WeatherService` calls them in that order. A `supported` option represents local eligibility only; no universal quality score.

- [ ] Write failing table-driven tests for actual-year sparse gaps, dates crossing years, TMY reference periods, missing required variables, provider limits, known/unknown site coordinates, distance/elevation constraints, stale source, access/health independence, CDS polar/land uncertainty, future SSP/RCP/window mismatch and source point-scope. Example:

  ```python
  def test_sparse_noaa_year_is_unknown(catalog_view, ithaca_request):
      result = evaluate(WeatherAvailabilityQuery(request=ithaca_request,
                        purpose="building_energy", refresh="never"), catalog_view)
      noaa = next(o for o in result.options if o.product.provider == "noaa")
      assert noaa.eligibility.status == "unknown"
      assert "YEAR_NOT_LISTED_IN_DATED_INVENTORY" in noaa.eligibility.unknowns
  ```

- [ ] Run focused pytest; expect failures. Implement rule functions by temporal tag and spatial kind. A fresh, applicable positive catalog membership can support an attempt; stale or incomplete absence is unknown; adapter incompatibility is excluded independently of catalog freshness. Do not infer station-hour completeness from counts or native weather coordinates from a reviewed index. Include evidence IDs and reason codes in every decision.
- [ ] Write failing ranking tests for neutral purpose and the three initial named purposes, explicit variables/limits, user provider order, deterministic ties, per-occurrence recommendations, no recommendation when all options for an occurrence are unknown/excluded, and unknown alternatives retained. Test that absent purpose-preferred variables are explained gaps while absent explicitly required variables affect eligibility. Example:

  ```python
  def test_solar_purpose_explains_radiation_gap(availability_result, solar_query):
      ranked = rank(availability_result, solar_query)
      nsrdb = next(o for o in ranked.options if o.product.provider == "nsrdb")
      assert ranked.locations[0].recommended_option_ids == [nsrdb.id]
      noaa = next(o for o in ranked.options if o.product.provider == "noaa")
      assert {"ghi", "dni", "dhi"} <= set(noaa.missing_preferred_variables)
      assert "MISSING_PREFERRED_RADIATION" in noaa.reasons
  ```

- [ ] Implement lexicographic ordering and per-option explanation fields as specified; leave caller-overridden variable/limit choices visible. Run focused tests, Ruff and mypy; commit `fix(availability): evaluate eligibility and explain recommendations`.

### Task 6: Shared service and existing discovery integration

**Files:** Modify `src/openepw/{service.py,__init__.py,models/__init__.py}` and provider `discover` methods only where they currently repeat catalog lookup; test `tests/unit/test_availability_service.py`, `tests/unit/test_service.py`, `tests/unit/test_future.py`.

**Interfaces:** Add `WeatherService.assess_availability(query) -> AvailabilityResult`. Add optional `DiscoveryResult.availability` with `exclude_if` when empty, preserving existing fields and old request/plan hashes. `discover()` obtains a pinned catalog view, evaluates/ranks once for all locations, maps actionable options to existing `Candidate` identities and keeps unknown/excluded alternatives in structured availability. Every input occurrence has its own assessment, even when existing discovery uses the same location key for repeated coordinates. When a bounded live discovery can resolve an actionable unknown, call it once per source/unique query, never per duplicate point. Future-method capability assessment remains independent of a baseline file and exposes only confirmed method constraints. Do not add a new `plan()` or `plan_future()` validation gate or change execution acceptance here; Stage 3a/3b consume the evidence for their complete preflight workflows.

- [ ] Write failing tests showing 100 duplicate/nearby requests use one snapshot, retain 100 occurrence assessments, and make no provider call for known metadata; an unknown NSRDB point triggers at most one bounded point catalog lookup; no fallback source is silently selected after a provider error; old serialized `WeatherPlan` still validates with its original hash. Several occurrences may show the same provisional station/site candidate without authorizing one retrieval or collapsing output identity. Example:

  ```python
  def test_fresh_catalog_avoids_noaa_inventory_http(service, noaa_request):
      service.http = HttpThatFailsOnNetwork()
      result = service.discover(noaa_request)
      assert result.availability
      assert any(c.source.provider == "noaa" for c in result.candidates)
  ```

- [ ] Run focused tests; expect failures. Wire catalog service behind dependency injection (`catalog_store` and clock/refresh policy) so offline tests do not require `.local` snapshots. Retain existing provider `fetch` paths, raw-response cache, candidate IDs, output IDs and warnings. Do not silently convert unknown into excluded or treat a catalog-supported option as a completed plan. Keep future capability check independent of baseline file access.
- [ ] Re-run focused and full offline tests, Ruff and mypy. Commit `fix(service): share catalog assessments with discovery`.

### Task 7: Thin adapters, documentation and acceptance

**Files:** Modify `src/openepw/api/app.py`, `src/openepw/mcp/server.py`, `src/openepw/cli/main.py` only for chosen thin access, plus `ARCHITECTURE.md`, `FEATURES.md`, `ROADMAP.md`, `docs/providers/{README,noaa,onebuilding,nsrdb,pvgis,era5}.md`, `docs/limitations.md`, `docs/decisions/0003-mcp-availability-and-batches.md`; create `docs/validation/mcp-stage-2-acceptance.md`; test `tests/unit/test_availability_adapters.py`.

**Interfaces:** Keep existing `/v1/weather/discover` and `weather_discover` behavior compatible while exposing the shared assessment. Add thin `POST /v1/availability` and `openepw availability <query.json>` access to the canonical service, including future-capability queries. Add local-only `openepw catalog status` and `openepw catalog import --from <snapshot-root>` for explicit snapshot setup. Stage 4 owns the final MCP tool list, names, descriptions and interaction; Stage 2 adds no new MCP tool. No full inventory rows or hourly data enter ordinary tool output.

- [ ] Write failing parity tests with one injected service and synthetic catalog. Compare Python, new REST and CLI decisions/reasons/snapshot IDs; existing REST/MCP discovery must serialize the same shared facts without its own ranking. Check invalid temporal kind and path fields produce bounded structured errors; check secrets and full source rows are absent from outputs. Example:

  ```python
  def test_weather_discover_parity(service, request, rest_client, mcp_tool):
      expected = service.discover(request).model_dump(mode="json")
      assert rest_client.post("/v1/weather/discover", json=request.model_dump(mode="json")).json() == expected
      assert mcp_tool("weather_discover", request.model_dump(mode="json")) == expected
  ```

- [ ] Run focused pytest; expect failures. Add the named REST/CLI entry points, validation and compact limits for option lists. CLI accepts a local query file; server/MCP accept data only and no server-side snapshot path. `catalog import` verifies and imports the already captured snapshots without network access, while `catalog status` reports loaded/missing/stale sources. Update API/usage and provider limitations, showing evidence dates, access needs, exact temporal meaning, 56/3/2 accepted judgments and unresolved redistributability. Mark this plan's approved date only after owner approval.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/unit -q`, `.venv/Scripts/python.exe -m ruff check src tests scripts/mcp_research`, `.venv/Scripts/python.exe -m mypy src/openepw`, and `.venv/Scripts/python.exe -m build`. Record exact results and skipped opt-in snapshot/live tests in `docs/validation/mcp-stage-2-acceptance.md`. Use an opt-in local import only if the original snapshots are present; do not run Stage 1 collection. Commit `fix(interfaces): expose shared availability evidence` and `fix(docs): record MCP Stage 2 acceptance` at the respective boundaries.

## Completion review

- Check every spec contract against a task and test: all providers/methods, 61 annotation states, stale refresh, actual/TMY/future semantics, access/health separation, ranking reasons and adapter parity.
- Check `git status` for ignored snapshot leakage; review the diff for secrets, signed URLs, full inventory rows, accidental API breakage and changed v0.1 plan hashes.
- Request one independent whole-branch review after implementation and resolve material findings. The owner's plan review is the implementation gate; the task checkpoints above are engineering verification, not new permission gates.
- Link the final acceptance record and distinguish offline synthetic verification, optional local-snapshot import, live metadata checks and weather/QC validation. A syntactically valid EPW is never labeled simulation ready by this feature.

## Implementation record — 2026-09-24

Tasks 1–7 were implemented in boundary commits on `feature/mcp`. The independent
whole-branch review found five material issues; follow-up commits added bundled
documented-contract fallback, live discovery for actionable unknowns, future
selector checks, partial-refresh rejection, age-based staleness and schema version
checks. The final offline suite, opt-in original-snapshot import, Ruff, mypy and
wheel/sdist build passed; exact commands and limits are in the acceptance record.

Two implementation choices differ from the original file map. NOAA and
OneBuilding local analysis normalization are contained in `stage1.py` instead of
thin single-purpose modules. Import requires an existing `analysis.json`; an
installed package does not invoke checkout-only research analysis automatically.
If only raw/ledger are present, run the offline Stage 1 analyzer explicitly before
`catalog import`. Automatic refresh accepts supported JSON metadata only and
rejects incomplete or multi-source replacements, keeping the last good generation
and marking the source stale. These choices keep the accepted snapshots and 61
review annotations intact without running Stage 1 collection.
