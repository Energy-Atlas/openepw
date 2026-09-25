# NSRDB Geospatial Availability Implementation Plan

**Owner display revision, 2026-09-24:** The local map now presents only reviewed
published NSRDB grid evidence. The aggregate actual-year map option and the two
point markers/payload entries were removed at the owner's request. Tasks below
describe the original evidence acquisition and review; their point cross-checks
remain historical source validation, not current map layers. The Stage 1 snapshots
are unchanged. This historical map plan preceded completion of the shared Stage 2
service; the map evidence was not imported into that service.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task after owner review. Steps use checkbox (`- [ ]`) syntax for tracking. This is a focused local map deliverable before shared Stage 2 service implementation.

**Goal:** Show defensible NSRDB product-specific geographic evidence for selected actual years or native TMY/TDY/TGY names in the local availability map.

**Architecture:** Reuse ignored Stage 1 point catalogs without recollecting them. Add a separate, bounded, provider-sourced spatial-metadata manifest when an exact v4 product/file mapping can be established; derive a generalized local display layer from it, retaining its evidence level. A standalone offline map generator reads both sources and emits an ignored HTML/data artifact. Any future service import requires a separate selector-bound review and a new catalog generation; map graphics are not service evidence.

**Tech Stack:** Python 3.11+, stdlib JSON/hashlib/urllib; optional `h5py`/HSDS client only if the selected source requires it; existing local HTML/canvas/JavaScript map pattern; pytest and Ruff. No mandatory GIS server, weather download or new runtime package dependency.

**Spec:** [NSRDB geospatial availability design](../specs/2026-09-24-nsrdb-geospatial-availability-design.md). Related [Stage 2 shared-service design](../specs/2026-09-24-mcp-stage-2-availability-design.md) and [Stage 1 catalog proposal](../../validation/mcp-stage-1/catalog-contract.md).

## Global constraints

- Owner review of this plan precedes implementation. Stage 2 shared-service implementation remains unapproved until explicitly approved; record that approval in its plan if received.
- Read the copied `.local/mcp-availability/{analysis.json,ledger.json,raw/}` as immutable source evidence; preserve accepted OneBuilding annotations and every local snapshot. Do not rerun Stage 1 collection.
- Use exact NSRDB API product names. `actual_year` and `published_name` are distinct selectors; `tdy-2023` is a native published name, not actual 2023 or a known source period.
- A generalized map mask never becomes a positive point eligibility decision. Access, health, weather completeness and spatial evidence remain distinct.
- Write new raw spatial metadata and generated map only beneath ignored `.local/mcp-availability/` paths. No credentials, signed download URLs, full grid coordinates or weather arrays in Git.
- Use configured human authorship and `fix(topic): concise description` commits; do not change branches or other contributors' work.

## Review focus

1. Published product has a suffix that looks like a year: test that `tdy-2023` is handled as a name, never as an actual-year interval.
2. Metadata for 2024 is missing while 2023 exists: test that a 2023–2024 interval is unknown for all-years coverage, not drawn as 2023 coverage.
3. Grid file or object version changes after acquisition: test that its mask is rejected or stale, not silently reused as fresh.
4. Disconnected islands/holes and longitude wrap: test that coarse rendering preserves gaps and the antimeridian.
5. The map's point catalog disagrees with a proposed file mapping: test that the discrepancy is exposed and the region is not promoted to exact coverage.

## File map and interface order

| Path | Responsibility |
| --- | --- |
| `docs/validation/mcp-stage-2/nsrdb-footprint-source-review.md` | Provider-controlled source and v4 API-product/file identity decision, byte/request budget and terms; includes a documented no-match outcome. |
| `scripts/mcp_availability_map/nsrdb_coverage.py` | Offline typed manifest parser, identity checks, sparse temporal set logic and display-mask derivation. |
| `scripts/mcp_availability_map/acquire_nsrdb_meta.py` | Opt-in, bounded spatial metadata acquisition after source identity is established; no weather arrays or bulk point sweep. |
| `scripts/mcp_availability_map/build.py`, `scripts/mcp_availability_map/map.html` | Read accepted local snapshots and optional footprint manifest; emit ignored interactive map with evidence-aware legend. |
| `tests/unit/test_nsrdb_coverage_map.py` | Synthetic source matching, temporal, spatial and fallback cases. |
| `docs/validation/mcp-stage-2/nsrdb-footprint-acceptance.md` | Exact commands/results, snapshot hashes, output location, known gaps and source attribution. |
| `docs/superpowers/specs/2026-09-24-mcp-stage-2-availability-design.md`, `docs/superpowers/plans/2026-09-24-mcp-stage-2-availability.md` | Add the approved per-selector footprint contract and later shared-service import/evaluation task. |

The offline module exposes:

```python
def load_point_catalogs(snapshot_root: Path) -> dict[str, object]: ...
def load_coverage_manifest(path: Path) -> CoverageManifest: ...
def classify_coverage(product_id: str, selectors: tuple[str, ...],
                      manifest: CoverageManifest | None) -> CoverageView: ...
def build_map(snapshot_root: Path, output_root: Path) -> Path: ...
```

`CoverageManifest` entries carry `product_id`, `source_file_id`, `source_version`, `selector_kind`, `selector`, `basis`, `retrieved_at`, `source_modified_at`, `sha256`, native CRS/longitude convention, coordinate count, display resolution and local mask path. `CoverageView` carries `confirmed_all`, `confirmed_some`, `unknown`, `point_confirmations`, reasons and evidence IDs. The shape is a local research contract; Stage 2 production types may encode it differently while preserving its meaning.

---

### Task 1: Establish exact source identity and bounded acquisition path

**Files:** Create `docs/validation/mcp-stage-2/nsrdb-footprint-source-review.md`; optional local metadata under `.local/mcp-availability/nsrdb-footprints/`.

**Interfaces:** Produces an auditable mapping from each target API product (`nsrdb-GOES-aggregated-v4-0-0`, `nsrdb-GOES-tmy-v4-0-0`) and requested selector to a provider-controlled spatial metadata source, or an explicit `no verified mapping` result.

- [ ] Confirm the copied Stage 1 `ledger.json` raw SHA-256 values, accepted `analysis.json`, and the two NSRDB response product IDs. Record counts and hashes only; do not copy raw bodies into docs.
- [ ] Inspect NLR product docs, public OEDI bucket listings and file metadata/headers for a sidecar region or `meta` coordinate table. Record exact URL/object identity without keys or signed query strings, product/version relationship, last-modified/ETag/checksum, license and estimated metadata bytes. Do not substitute `conus/`, `full_disc/` or v3 for aggregate/TMY v4.
- [ ] Select the least expensive authoritative metadata route: published sidecar first, bounded HSDS/coordinate-only access second, bounded HDF5 `meta` access third. Cap this task at 12 metadata requests and 256 MiB transferred per chosen selector; stop that route on a higher known content length. No weather dataset reads or point-grid sweeps.
- [ ] Cross-check two Stage 1 points against the proposed source for the same exact product/selector. Treat a mismatch or ambiguous version as `no verified mapping`; record the observed conflict.
- [ ] Commit the source-review memo as `fix(docs): identify bounded NSRDB footprint source`. If no verified mapping exists, the implementation path remains the documented-region/point fallback in Tasks 2–4; exact-region acceptance is explicitly unresolved.

### Task 2: Define honest spatial and temporal evidence operations

**Files:** Create `scripts/mcp_availability_map/nsrdb_coverage.py`; test `tests/unit/test_nsrdb_coverage_map.py`.

**Interfaces:** Produces `CoverageManifest`, `CoverageView`, `load_point_catalogs`, `load_coverage_manifest` and `classify_coverage`. Consumes Stage 1 local files and optional Task 3 manifest; never performs HTTP.

- [ ] Write failing synthetic tests for selector distinction, multi-year intersection/partial union, one missing year, stale/checksum mismatch, unknown product/version, disconnected occupancy, holes and antimeridian. Example: `classify_coverage(AGGREGATE_ID, ("2023", "2024"), one_year_manifest).unknown is True`; `classify_coverage(TMY_ID, ("tdy-2023",), manifest).selector_kind == "published_name"`.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/unit/test_nsrdb_coverage_map.py -q`; expect import failures. Create a worktree-local environment from project extras if needed; never read secrets into fixtures.
- [ ] Implement strict schema/version/checksum validation and exact product/selector matching. Compute all-years intersection only when each requested actual-year mask exists and is current; compute some-years union with `unknown` retained for missing selectors. An unsuffixed alias requires a resolved concrete name from a current exact-point catalog, or remains unknown.
- [ ] Derive display occupancy at recorded resolution without a convex hull. Preserve disconnected components, gaps, CRS and longitude provenance. Keep the original point confirmations separate from the grid mask.
- [ ] Run focused pytest and Ruff. Commit `fix(availability): model NSRDB spatial evidence and time selectors`.

### Task 3: Acquire and validate optional version-matched grid metadata

**Files:** Create `scripts/mcp_availability_map/acquire_nsrdb_meta.py`; extend `tests/unit/test_nsrdb_coverage_map.py` with mocked transport/metadata readers.

**Interfaces:** Consumes Task 1 source decision; emits a local versioned manifest and compressed display mask in `.local/mcp-availability/nsrdb-footprints/`. `load_coverage_manifest` from Task 2 validates it. If Task 1 found no exact mapping, emit no grid mask and a machine-readable `unknown_source_mapping` reason.

- [ ] Write failing tests for an accepted coordinate-only transfer, partial transfer, mismatched API/native version, changed ETag, oversized source, missing selector, illegal path, duplicate/invalid coordinates and source-site disagreement with Ithaca/Phoenix. Mock responses; no live calls in unit tests.
- [ ] Run focused tests; expect failures. Implement a single selected access route from Task 1 with hard byte/request caps, conditional requests, atomic local writes, SHA-256 and source identity checks. Read `meta` coordinates only; reject attempts to fetch time-series arrays. Use an opt-in live command; never run automatically in offline pytest or `build_map`.
- [ ] For each selected actual year or published name, write separate records. Do not reuse a year's footprint for another year or a TMY/TDY/TGY variant without provider evidence proving identity. No exact file mapping means the task records the limitation and leaves the map in honest fallback mode.
- [ ] Run focused tests, Ruff and a single opt-in metadata acquisition only for the owner's selected selector if a verified source exists. Record actual request and byte totals and local SHA-256 in the acceptance memo. Commit `fix(availability): acquire bounded NSRDB spatial metadata` without staging local outputs.

### Task 4: Render the local NSRDB map and publish an evidence audit

**Files:** Create `scripts/mcp_availability_map/{build.py,map.html}` and `docs/validation/mcp-stage-2/nsrdb-footprint-acceptance.md`; extend `tests/unit/test_nsrdb_coverage_map.py`.

**Interfaces:** `build_map(snapshot_root, output_root) -> Path` writes ignored local HTML/data. The map consumes Task 2's `CoverageView`; it never directly calls NLR or converts a display mask into a service eligibility answer.

- [ ] Write failing tests for aggregate actual interval control, published name control, explicit `unknown` state, two point overlay, source/version/date/basis text, map output ignored by Git, and absence of credentials/signed URLs. Include a 2023–2024 missing-year case that does not shade all-years coverage.
- [ ] Run focused pytest; expect failures. Implement the local map with distinguishable all-years, some-years, point-confirmed and documented-context layers. Label generalized display resolution; hover/selection states expose native product name and evidence IDs. A source-mapping failure shows the documented NLR description plus the two point probes and an exact-footprint-unresolved notice.
- [ ] Build against the copied snapshots read-only. Verify Stage 1 ledger hashes again, inspect the generated map/data counts, run JavaScript syntax validation and focused pytest/Ruff. The generated HTML/data and full inventory remain ignored.
- [ ] Record the artifact's local path, selector, actual source dates/checksums, quality limits, source citations and exact commands/results in the acceptance memo. Commit `fix(map): show evidence-qualified NSRDB coverage` and `fix(docs): record NSRDB footprint evidence`.

### Task 5: Carry the contract into the Stage 2 shared-service plan

**Files:** Modify `docs/superpowers/specs/2026-09-24-mcp-stage-2-availability-design.md`, `docs/superpowers/plans/2026-09-24-mcp-stage-2-availability.md`, `docs/validation/mcp-stage-1/catalog-contract.md` only to cross-reference the outcome.

**Interfaces:** Stage 2 importer consumes the Task 3 manifest when present, preserving `product_id`, selector, evidence level, snapshot identity and unknown state. The availability evaluator performs exact point checks for support decisions; the map mask supplies context and bounded negative decisions only when exhaustive coverage is proven.

- [ ] Update the shared catalog spec and Task 4 importer to include per-selector footprint records, source identity validation and the fallback; update evaluation tests to reject positive eligibility inferred solely from a generalized mask. Preserve the existing point cache policy and other provider rules.
- [ ] Review docs for conflicts with the accepted Stage 1 record. Update the catalog proposal's prioritized gap item with a link to the acceptance outcome, not a retroactive claim that Stage 1 had a polygon.
- [ ] Run `git diff --check`, focused plan/spec cross-reference checks and `git status --short`; ensure no ignored source body is staged. Commit `fix(docs): connect NSRDB map evidence to Stage 2 catalog`.

## Completion review

Compare the output with the spec's evidence ladder. An exact shaded grid layer is accepted only with a documented product/version/selector match and bounded metadata extraction. If this prerequisite is unavailable, ship the improved point and documented-context map with explicit unknown exact extent, and report the provider mapping as the remaining blocker. Keep Stage 2 implementation unstarted until owner approval of the shared-service plan.
