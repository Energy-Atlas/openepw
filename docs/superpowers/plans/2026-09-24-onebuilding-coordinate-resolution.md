# OneBuilding Coordinate Resolution Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Keep the existing inline execution approach with one final independent review. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve OneBuilding coordinate discovery using auditable offline matching and three bounded published-index requests, without manufacturing station identity or weather availability.

**Architecture:** Extend only the standalone Stage 1 research modules. Separate product identity, geographic position, elevation and source-station identity; agreement on one does not resolve the others. Prefer exact product links from published indexes and preserve competing NOAA evidence.

**Tech Stack:** Existing Python environment, standard library, httpx/truststore collector, pytest and Ruff. No new dependencies, accounts or geocoder services.

**Spec:** [Accepted Stage 1 follow-up decisions](2026-09-23-mcp-stage-1.md#accepted-onebuilding-follow-up-plan--2026-09-23), [availability and batch ADR](../../decisions/0003-mcp-availability-and-batches.md), and [current findings](../../validation/mcp-stage-1/README.md). This plan further specifies the owner's accepted direction after inspecting unresolved products.

**Status:** Proposed for review, not executed. Approval of this full plan must explicitly include the network extension below; offline tasks can proceed independently if only those are approved. MCP Stage 2 remains outside scope.

## Global Constraints

- Execute on `feature/mcp`, preserve other contributors' work, and use the existing Python dependencies.
- Do not change production discovery, recommendations, MCP tools, or batch execution in this stage.
- Previous weather runs/QC summaries are excluded; advanced reuse stays future work.
- No weather ZIP downloads, EPW-header reads, archive members, geocoding API calls or exhaustive crawling.
- Store raw and complete normalized third-party indexes only under ignored `.local/mcp-availability/`.
- Preserve all prior requests and byte charges. Overall limits remain 60 metadata attempts, 12 probes and 200,000,000 application response bytes.
- Ordinary responses remain bounded to 5,000,000 bytes; serial calls, at least two seconds same-host spacing, 30-second operation timeout, 60-second total deadline, no automatic retries.
- Count redirects and failed attempts. Stop on rate limiting or budget exhaustion and document unknowns.
- No extra OEDI requests or changes to its approved allowances.
- Commit using `fix(topic): concise description`, normal configured authorship, no push or merge.
- Eligibility and evidence basis remain separate; no new public API or production ranking claims.

## Baseline and problem statement

Baseline commit: `e402b0e` (preceded by tooling `39d917b`). Verify this exists in history and inspect current status before execution; do not reset to it.

Current selected catalogs contain 21,653 products, not distinct sites:

| Catalog | Products | Published-index coordinates | NOAA inference | Unknown |
| --- | ---: | ---: | ---: | ---: |
| U.S. | 16,470 | 13,355 | 1,543 | 1,572 |
| U.K. | 1,451 | 1,451 | 0 | 0 |
| Australia | 3,732 | 0 | 3,505 | 227 |

Unknowns by currently observed cause:

| Cause | U.S. products | Australian products |
| --- | ---: | ---: |
| Multiple NOAA candidates | 1,316 | 0 |
| Name not corroborated | 135 | 75 |
| No coordinate-bearing NOAA identifier | 115 | 0 |
| Country disagreement/missing normalization | 6 | 152 |

The U.S. products comprise 934 Normals, 588 TMY3, 45 TMYx and 5 older TMY/TMY2 files. The Australian products are 227 TMYx period variants for 49 catalog identifiers. The U.S. unknown set contains 959 catalog identifiers; category counts of identifiers must not be added because a single identifier can occur across categories/products.

197 ambiguous U.S. products have identical candidate latitude/longitude; only 10 also have identical elevation. Coordinate agreement can therefore reduce geographic unknowns without resolving the NOAA record identity.

Important correction to our earlier description: do not globally describe the snapshot's country column as reliably FIPS-only. `AS` and `AU` occur on geographically Australian records. In FIPS, `AU` is not Australia; globally mapping `AU` to Australia would be unsafe. Preserve raw values and corroborate individual product links through the source's index. The current name tokenizer also drops `Hay` because it requires four letters.

## Proposed network extension

OneBuilding's current 12-attempt allowance is exhausted. Recommend increasing it to **15 cumulative HTTP attempts**, only to inspect these three exact source-linked spreadsheet URLs. This is a proposal requiring approval of this plan's network scope, not authorization inferred from general interest.

| Request ID | URL | Purpose |
| --- | --- | --- |
| `onebuilding-au-coordinate-xlsx` | https://climate.onebuilding.org/sources/Region5_Southwest_Pacific_TMYx_EPW_Processing_locations.xlsx | Exact-product coordinates for Australian TMYx, avoiding country-code guesses |
| `onebuilding-normals-coordinate-xlsx` | https://climate.onebuilding.org/sources/Normals_EPW_Processing_locations.xlsx | Resolve the largest unresolved U.S. product family |
| `onebuilding-tmy3-coordinate-xlsx` | https://climate.onebuilding.org/sources/TMY3a_EPW_Processing_locations.xlsx | Check exact TMY3 catalog links; do not assume TMY3a and TMY3 products are identical |

All three URLs are already in the saved `onebuilding-sources` link inventory. Each gets one attempt, maximum 5 MB. The provider extension is at most three HTTP attempts including redirects; redirects can consume capacity needed for another file. No revised attempt, alternate oversized KML or replacement URL is automatically authorized. Global remaining capacity before this work: 22 metadata attempts and 61,086,659 bytes. This extension can consume at most 15 MB of response bodies and does not change the global ceilings. No probe is needed.

If the extension is not approved, complete Tasks 1–3 and 5–6 offline and retain Task 4 as unexecuted. Failure to obtain an index is not dataset exclusion. Broad place geocoding remains deferred.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `scripts/mcp_research/coordinates.py` | Existing workbook parser; name evidence, country checks, position/elevation consensus and exact-product matching |
| `scripts/mcp_research/analysis.py` | Local joins, reason/transition summaries and sanitized example selection |
| `scripts/mcp_research/collector.py` | Narrow approved OneBuilding request extension; preserve all existing budgets |
| `scripts/probe_mcp_availability.py` | Expose the approved limit/scope in offline `plan` output |
| `tests/unit/test_mcp_availability_coordinates.py` (new) | Synthetic focused coordinate and report-contract tests; do not move historical tests unnecessarily |
| `tests/unit/test_mcp_availability_research.py` | Collector extension, resume and offline CLI safeguards |
| `docs/validation/mcp-stage-1/{README.md,evidence.json,requests.json,sources.md,catalog-contract.md}` | Findings, sanitized ledger, proposed catalog semantics and metadata terms |
| `scripts/mcp_research/README.md`, `ROADMAP.md`, this plan | Reproduction instructions, status and execution decisions |

All research tests import modules using the existing `scripts` path setup. For the new test module, use `sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))` before research imports.

## Research record contract

Keep existing `url`, `period`, `lat`, `lon`, `elevation_m`, `coordinate_basis`, `epw_coordinates_verified`, `evidence_ids`, `noaa_candidates`, `published_candidates`, `coordinate_disagreement` and `reason` fields. Add:

```python
# Per-product local research record; not a public API.
position_status: str       # published | inferred | consensus | unknown
station_identity_status: str  # unique_candidate | ambiguous | unknown
source_station_id: str | None
source_station_ids: list[str]  # all qualifying NOAA identities
country_evidence: dict    # raw_codes, expected_code, status; no global AU alias
name_match_method: str    # token_overlap | exact_short_name | none
unresolved_reasons: list[str]  # sorted; empty only when the position is resolved
```

`source_station_id` is non-null only for one qualifying candidate. `consensus` is a coordinate state, not a claim of shared weather or identical station identities. Published coordinates remain preferred even when NOAA disagrees, but competing candidates/flags remain visible. Country ambiguity may remain a caveat on NOAA candidates even when an exact published product link resolves the position. Elevation stays null if candidates disagree or any candidate omits it. Do not average, round, choose the newest record, or select a WBAN suffix to force agreement.

Keep the existing `mcp-research-1` format for additive fields and document additions. No consumer currently uses this as a stable public API. Existing `supported` semantics must not expand based solely on a match.

## Review Focus

1. Mixed country-code conventions and cross-border identifier reuse: `AU` must not silently become an Australian match; pin in Task 2.
2. Equal horizontal coordinates with unequal/missing elevations or several WBAN IDs: preserve identity/elevation ambiguity; pin in Task 3.
3. Short/renamed/generic airport names: admit exact distinctive short names, never fuzzy city-only or generic facility matches; pin in Task 2.
4. Index snapshots disagree, formulas hide URLs or TMY3a links differ from TMY3: preserve conflicts and require exact product URL; pin in Task 4.
5. Repeated analysis, partial index acquisition or resumed exhausted budgets: deterministic output and no unplanned provider call; pin in Tasks 4–5.

## Task 1: Make the unresolved inventory reproducible

**Files:** Modify `analysis.py`; create `tests/unit/test_mcp_availability_coordinates.py`.

**Interfaces:** Consume `coordinate_matches(urls, history, published) -> list[dict]` and normalized `noaa-history` sites. Produce `coordinate_diagnostics(matches: list[dict], history: list[dict]) -> dict` in `analysis.py`, with `product_count`, `coordinate_counts`, `unresolved_reason_counts`, `product_family_counts` and `unresolved_products` (local-only rows).

- [ ] Write the failing tests using synthetic matches and NOAA sites:

```python
def test_diagnostics_count_products_not_period_ranges():
    matches = [
        dict(url='a', station_id='001234', product='TMYx.2004-2018',
             country='USA', coordinate_basis='unknown', noaa_candidates=[]),
        dict(url='b', station_id='001234', product='TMYx.2011-2025',
             country='USA', coordinate_basis='unknown', noaa_candidates=[]),
    ]
    result = coordinate_diagnostics(matches, [])
    assert result['product_count'] == 2
    assert result['unresolved_reason_counts'] == {'no_coordinate_bearing_identifier': 2}
    assert result['product_family_counts'] == {'TMYx': 2}
```

Add this second test for ambiguity versus failed name corroboration:

```python
def test_diagnostics_distinguish_identity_from_name():
    history = [dict(id='00123400001', country='US', name='EXAMPLE AIRPORT'),
               dict(id='00123499999', country='US', name='EXAMPLE')]
    base = dict(station_id='001234', country='USA', product='TMY3',
                coordinate_basis='unknown')
    matches = [dict(base, url='a', noaa_candidates=history),
               dict(base, url='b', noaa_candidates=[])]
    counts = coordinate_diagnostics(matches, history)['unresolved_reason_counts']
    assert counts == {'ambiguous_station_identity': 1, 'name_not_corroborated': 1}
```

- [ ] Run `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_availability_coordinates.py -q`; expect failure because `coordinate_diagnostics` is absent.
- [ ] Implement explicit reasons, preserving all qualifying candidate identities:

```python
# Classifier precedence for unknown positions:
# unrecognized_product_identifier -> no_coordinate_bearing_identifier ->
# country_code_ambiguous_or_conflicting -> name_not_corroborated ->
# ambiguous_station_identity -> conflicting_published_coordinates.
# Give conflicting published coordinates precedence whenever present.
# Family uses product prefix: US.Normals, TMY3, TMYx, TMY2, TMY, otherwise exact label.
# Counts are per product URL; all additional reasons may be listed separately.
```

Expose a mutually exclusive `primary_reason` for additive totals plus a separate list of all unresolved reasons. Include rejected raw country/name candidates in local diagnostics, not just the already-filtered `noaa_candidates`.

- [ ] Run the new tests and existing 35 research tests; expect all pass. Generate the current diagnostics offline and verify 1,572 U.S. + 227 Australian unknown products before changing match behavior. Snapshot the baseline under `.local/mcp-availability/coordinate-baseline.json`, with source checksums and matcher version `1`; do not use a previous weather run.
- [ ] Commit `fix(research): classify unresolved OneBuilding coordinate evidence`.

## Task 2: Improve names without guessing country codes or aliases

**Files:** Modify `coordinates.py`; test `test_mcp_availability_coordinates.py`.

**Interfaces:** Add `name_evidence(product_name: str, station_name: str) -> str`, returning `token_overlap`, `exact_short_name` or `none`; add `country_evidence(country: str, raw_codes: list[str]) -> dict` with keys `raw_codes`, `expected_code`, `status` (`consistent`, `ambiguous`, `conflicting`). Keep `name_tokens` available for existing callers.

- [ ] Add parameterized tests:

```python
@pytest.mark.parametrize('left,right,expected', [
    ('Hay.AP', 'HAY AIRPORT AWS', 'exact_short_name'),
    ('Hay.AP', 'RAY AIRPORT AWS', 'none'),
    ('Regional.AP', 'REGIONAL AIRPORT', 'none'),
    ('Ithaca.Tompkins.Rgnl.AP', 'ITHACA TOMPKINS REGIONAL AIRPORT', 'token_overlap'),
    ('Unalaska-Madsen.AP', 'DUTCH HARBOR AIRPORT', 'none'),
])
def test_name_evidence(left, right, expected):
    assert name_evidence(left, right) == expected

def test_au_code_is_not_globally_reinterpreted():
    assert country_evidence('AUS', ['AS'])['status'] == 'consistent'
    assert country_evidence('AUS', ['AU'])['status'] == 'ambiguous'
    assert country_evidence('USA', ['CA'])['status'] == 'conflicting'
```

- [ ] Run the new test module; expect missing helpers/incorrect short-name behavior.
- [ ] Normalize punctuation/diacritics using the existing method. Remove explicit generic tokens `AP`, `AIRPORT`, `AWS`, `INTL`, `INTERNATIONAL`, `STATION`, `MUNI`, `MUNICIPAL`, `RGNL`, `REGIONAL`, `COUNTY`, `FIELD`, `FLD`. First retain existing distinctive token overlap of length >=4. Otherwise require equal nonempty distinctive token sequences, all tokens length >=3, for `exact_short_name`. No edit-distance matching, spelling correction, inferred aliases or substring matches.

```python
# Country decision remains deliberately conservative:
expected = {'USA': 'US', 'GBR': 'UK', 'AUS': 'AS'}.get(country)
# raw AU on an AUS product => ambiguous, never consistent solely from a bounding box.
# All raw codes equal expected => consistent; unknown expected/missing codes => ambiguous.
# Other codes => conflicting. Preserve raw codes verbatim in the record.
```

Integrate these helpers into NOAA candidate filtering. An ambiguous country record cannot resolve position via NOAA fallback; an exact published OneBuilding URL can resolve it independently. Do not claim the 152 country-ambiguous Australian products are fixed before obtaining that evidence.

- [ ] Run both research test modules; expect pass, including cross-country and generic-name negatives. Inspect the Hay example offline and retain genuine mismatches such as Finley versus Frankston.
- [ ] Commit `fix(research): corroborate short station names conservatively`.

## Task 3: Separate geographic consensus from station identity

**Files:** Modify `coordinates.py`, `analysis.py`; test `test_mcp_availability_coordinates.py`.

**Interfaces:** Add `coordinate_consensus(candidates: list[dict]) -> dict`, returning `lat`, `lon`, `elevation_m`, `position_status`, `station_identity_status`, `source_station_id`, `source_station_ids`. Input candidates have already passed identifier, country and name checks.

- [ ] Write these failing tests:

```python
def test_shared_position_does_not_merge_station_identity():
    candidates = [
        dict(id='00123400001', lat=42.0, lon=-76.0, elevation_m=100),
        dict(id='00123499999', lat=42.0, lon=-76.0, elevation_m=110),
    ]
    out = coordinate_consensus(candidates)
    assert (out['lat'], out['lon']) == (42.0, -76.0)
    assert out['elevation_m'] is None
    assert out['position_status'] == 'consensus'
    assert out['station_identity_status'] == 'ambiguous'
    assert out['source_station_id'] is None
    assert out['source_station_ids'] == ['00123400001', '00123499999']

def test_nearby_is_not_identical():
    out = coordinate_consensus([
        dict(id='a', lat=42, lon=-76, elevation_m=100),
        dict(id='b', lat=42.0001, lon=-76, elevation_m=100),
    ])
    assert out['lat'] is None
    assert out['position_status'] == 'unknown'
```

Add tests for missing elevation, zero elevation, one candidate, no candidates and reversed input ordering. Preserve all candidate IDs even when position is unknown.

- [ ] Run the tests; expect missing helper failures.
- [ ] Implement exact finite-coordinate agreement, no tolerances or averaging:

```python
positions = {(c['lat'], c['lon']) for c in candidates}
# Resolve a position only when there is exactly one valid pair.
# One candidate => inferred/unique_candidate; several => consensus/ambiguous.
# Elevation resolves only if every candidate supplies the same finite value.
# Output IDs are sorted and unique; duplicate identical rows are not new identities.
# Conflicting rows for the same ID remain separate evidence and block consensus.
```

Integrate after filtering, and add `coordinate_basis='station_coordinate_consensus'`. Do not set a fabricated single `source_station_id`. If published points conflict, retain that conflict rather than fall through to a convenient NOAA consensus. Preserve published-vs-NOAA differences.

- [ ] Update analysis aggregation to include the new basis explicitly. Run both research modules; expect pass. Report actual changes from the saved baseline; 197 is a baseline observation, not a required recovery target.
- [ ] Commit `fix(research): retain station ambiguity with coordinate consensus`.

## Task 4: Acquire the three source indexes under the approved extension

**Files:** Modify `collector.py`, CLI plan output, `requests.json` and collector tests; use existing `spreadsheet_rows` parser in `coordinates.py`.

**Interfaces:** Collector accepts the three exact request IDs/URLs in the network table, kind `inventory`, provider `onebuilding`, `parent='onebuilding-sources'`, `depth=1`, `limit=5_000_000`. After approval, original OneBuilding requests retain their 12-attempt ceiling; only these exact additional ID/URL pairs may use attempts 13–15. Redirects count in the same aggregate. Expose this exception in `plan` output.

- [ ] Confirm explicit approval includes the network extension. If absent, mark this task unexecuted and continue offline publication; do not ask again during execution if approval already covers it.
- [ ] Write a synthetic collector test seeded with 12 prior OneBuilding HTTP hops: an exact approved request saves, an unrelated URL is blocked, and a resumed collector at 15 blocks every further call. Add a redirect consuming the final attempt and assert its destination is never requested after the cap.

```python
from mcp_research.collector import Collector, Request
import httpx

def test_only_approved_indexes_use_extension_and_resume(tmp_path):
    visits = []
    def respond(request):
        visits.append(str(request.url))
        return httpx.Response(200, content=b'index')
    transport = httpx.MockTransport(respond)
    files = [
        ('onebuilding-au-coordinate-xlsx', 'Region5_Southwest_Pacific_TMYx'),
        ('onebuilding-normals-coordinate-xlsx', 'Normals'),
        ('onebuilding-tmy3-coordinate-xlsx', 'TMY3a'),
    ]
    with Collector(tmp_path, transport=transport, spacing=0) as collector:
        for i in range(12):
            request = Request(f'prior-{i}', 'onebuilding',
                              f'https://climate.onebuilding.org/prior-{i}',
                              'metadata', 'Synthetic prior attempt')
            assert collector.collect(request)['outcome'] == 'saved'
        unrelated = Request('unrelated', 'onebuilding',
                            'https://climate.onebuilding.org/unrelated',
                            'inventory', 'No extension for other URLs')
        assert collector.collect(unrelated)['outcome'] == 'provider_limit'
        for key, filename in files:
            request = Request(key, 'onebuilding',
                f'https://climate.onebuilding.org/sources/{filename}_EPW_Processing_locations.xlsx',
                'inventory', 'Approved source index', limit=5_000_000)
            assert collector.collect(request)['outcome'] == 'saved'
    visited = len(visits)
    with Collector(tmp_path, transport=transport, spacing=0) as collector:
        assert collector.ledger['counts']['metadata'] == 15
        assert collector.collect(Request('beyond-cap', 'onebuilding',
            'https://climate.onebuilding.org/extra', 'metadata',
            'Synthetic exhaustion'))['outcome'] == 'provider_limit'
        assert len(visits) == visited
```

For the redirect case, use the same setup with 12 prior calls and two approved
index successes. Return HTTP 302 on the third approved URL with a same-host
`Location: /redirected-index.xlsx`. Assert the result is `provider_limit`, total
metadata count is 15 and `/redirected-index.xlsx` never appears in `visits`.
The original approved request retains its authorization through a redirect, but
its redirects do not gain extra request capacity.

- [ ] Run the collector tests; expect the approved thirteenth attempt to fail under the old ceiling. Implement one `onebuilding_request_limit(request)` helper used in both initial validation and redirect loop, matching exact IDs and URLs; never overwrite ledger counts.
- [ ] Add parser/matching tests with synthetic workbook rows: one missing coordinate, a formula URL, conflicting duplicate points, and an index URL ending `_TMY3a.zip` versus requested `_TMY3.zip`. The latter must remain unmatched unless the exact requested URL is also listed. Preserve country/identifier discrepancies as diagnostics; no family-name URL rewriting.
- [ ] Run focused tests; expect pass before live work. Append the three requests to the existing local follow-up manifest and publish their sanitized definitions. Run:

```powershell
.venv/Scripts/python.exe scripts/probe_mcp_availability.py plan --manifest .local/mcp-availability/followups.json --only onebuilding-au-coordinate-xlsx onebuilding-normals-coordinate-xlsx onebuilding-tmy3-coordinate-xlsx
.venv/Scripts/python.exe scripts/probe_mcp_availability.py collect --manifest .local/mcp-availability/followups.json --only onebuilding-au-coordinate-xlsx onebuilding-normals-coordinate-xlsx onebuilding-tmy3-coordinate-xlsx
```

Expected: at most three additional HTTP attempts, at most 15 MB bodies, no weather. Saved or precisely documented blocked outcomes are acceptable. Never change manifests for already-used IDs. Existing cached successful responses should require zero new calls on rerun.

- [ ] Parse saved indexes offline, joining exact URLs only. If source columns differ, write a synthetic failing parser fixture before a narrowly scoped schema adaptation; do not loosen URL/coordinate validation. Keep new metadata terms/source dates and whole workbooks local.
- [ ] Commit tooling/manifest changes with `fix(research): inspect bounded OneBuilding product indexes`.

## Task 5: Publish a deterministic before/after accounting

**Files:** Modify `analysis.py`, new coordinate tests, `evidence.json`, report/source register and catalog contract.

**Interfaces:** Add `coordinate_transitions(before: list[dict], after: list[dict]) -> dict` in `analysis.py`, keyed by exact product URL. Return aggregate `counts` keyed `old_basis -> new_basis` and local-only `changes` with product URL, previous/current basis and reasons. Do not count a retained unknown as a recovery. Preserve product periods/IDs exactly.

- [ ] Write tests with one recovered product, one unchanged unknown, one change from NOAA to published evidence and one deliberately removed URL. Removed/added products must be reported separately, not disguised as coordinate improvements:

```python
before = [dict(url='a', coordinate_basis='unknown'),
          dict(url='b', coordinate_basis='station_identifier_and_name')]
after = [dict(url='a', coordinate_basis='station_coordinate_consensus'),
         dict(url='b', coordinate_basis='published_product_index')]
assert coordinate_transitions(before, after)['counts'] == {
    'unknown -> station_coordinate_consensus': 1,
    'station_identifier_and_name -> published_product_index': 1,
}
```

- [ ] Run tests; expect missing transition function. Implement a stable sorted URL join. Enforce duplicate URL handling explicitly: identical records deduplicate; differing records raise sanitized analysis failure rather than last-write-wins.
- [ ] Extend report filtering to omit `unresolved_products` and transition `changes`, just as it excludes full coordinate matches and inventories today. Add tests that report generation makes no HTTP requests and excludes raw index/candidate dumps while retaining aggregate reasons, checksums and bounded selected examples.
- [ ] Run offline analyze/report twice; expect equal JSON bytes, unchanged request/byte counters and no analysis errors. Generate a local full unresolved list and publish aggregate counts by country/product family/reason. Publish at most two illustrative examples per reason, never the full index.
- [ ] Update the handoff: distinguish resolved position, ambiguous station identity, unknown elevation, cross-source disagreement and EPW-header verification. No record may imply that candidate coordinate agreement authorizes weather-request deduplication.
- [ ] Commit `fix(docs): explain remaining OneBuilding coordinate uncertainty`.

## Task 6: Verify, review and finish the research follow-up

**Files:** This plan, research README, ROADMAP and final findings.

- [ ] Run:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_availability_coordinates.py tests/unit/test_mcp_availability_research.py -q
.venv/Scripts/python.exe -m ruff check scripts/mcp_research scripts/probe_mcp_availability.py tests/unit/test_mcp_availability_coordinates.py tests/unit/test_mcp_availability_research.py
.venv/Scripts/python.exe -m pytest -q
git diff --check
```

Expected: focused suite and lint pass; full suite passes with opt-in live tests skipped. Record actual totals rather than copying the baseline 136 passed/14 skipped.

- [ ] Validate all relative documentation links, report totals (resolved + unknown = unchanged catalog product count), missing-coordinate records, candidate lists and ledger arithmetic. Confirm no production files, raw third-party indexes or credentials are staged.
- [ ] Obtain one fresh read-only review of the full follow-up diff against this plan and its five Review Focus items. Reproduce and fix material findings with failing tests, then rerun appropriate checks. Record any deliberately deferred minor findings.
- [ ] Update this plan's execution ledger with approvals, exact outcomes, limits used, chosen rules, review decisions and remaining unknowns. Update ROADMAP to link the findings; retain previous-run/QC reuse as future work.
- [ ] Commit final findings with `fix(docs): record OneBuilding follow-up validation`. Leave `feature/mcp` clean and unpushed; provide commit IDs and the report link.

## Completion criteria

- Every selected product remains represented with its reference period and evidence; no arbitrary recovery quota.
- Short-name improvements and horizontal coordinate consensus are covered by meaningful positive/negative tests.
- Country ambiguity is corroborated through exact source-product evidence or remains explicit; no global AU alias.
- Station identity and elevation uncertainty survive coordinate resolution.
- All network work, if approved, stays inside the narrow three-attempt extension and original global ceilings.
- Analysis is reproducible from saved metadata, reports contain reasoned before/after totals, and unresolved cases remain usable Stage 2 inputs.
- General geocoding, native EPW coordinate validation, shipping third-party inventories, production discovery and later MCP stages remain outside this work.

## Plan self-review

Coverage: Tasks 1/5 account for unresolved products; Task 2 handles short names and country ambiguity; Task 3 handles shared coordinates; Task 4 tests source indexes under explicit limits; Task 6 verifies and publishes. All five Review Focus inputs have an owning task and test requirement. No implementation or provider request was made while drafting this plan.
