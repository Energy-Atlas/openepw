"""Stage 1 snapshots import without recollection or review promotion."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from openepw.availability.stage1 import import_stage1
from openepw.availability.store import CatalogImportError, CatalogStore


def _snapshot(root: Path, *, changed_source: bool = False, changed_unrelated: bool = False):
    raw = root / "raw"
    raw.mkdir()
    bodies = {"noaa-history": b"history", "noaa-inventory-authorized": b"counts",
              "onebuilding-us": b"catalog", "onebuilding-au-coordinate-xlsx": b"index"}
    if changed_source:
        bodies["onebuilding-au-coordinate-xlsx"] = b"new index"
    if changed_unrelated:
        bodies["noaa-history"] = b"new history"
    records = []
    for source_id, body in bodies.items():
        (raw / f"{source_id}.body").write_bytes(body)
        records.append({"id": source_id, "provider": source_id.split("-")[0],
                        "outcome": "saved", "url": f"https://example.org/{source_id}",
                        "kind": "inventory", "sha256": hashlib.sha256(body).hexdigest(),
                        "snapshot": f"raw/{source_id}.body", "finished_at":
                        "2026-09-23T00:00:00+00:00"})
    (root / "ledger.json").write_text(json.dumps({"records": records}), encoding="utf-8")
    url = "https://example.org/product_TMYx.2009-2023.zip"
    match = {"url": url, "product": "TMYx.2009-2023", "period": "2009-2023",
             "lat": None, "lon": None, "position_status": "unknown",
             "reason": "strict_unmatched", "source_station_ids": ["A00002"],
             "station_identity_status": "ambiguous",
             "review": {"status": "reviewed_metadata_match",
                        "published_url": "https://example.org/alternate_TMYx.2009-2023.zip",
                        "coordinates": {"lat": 42.0, "lon": -76.0}}}
    analysis = {"inventories": {
        "noaa-history": {"sites": [{"id": "A00002", "lat": 42, "lon": -76,
                                      "start": "2001-01-01", "end": "2025-01-01"}]},
        "noaa-inventory-authorized": {"station_years": {"A00002":
                                         {"2001": [2] * 12, "2003": [4] * 12}}},
        "onebuilding-us": {"coordinate_matches": [match]},
    }, "providers": []}
    (root / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    registry = {"accepted_on": "2026-09-24", "source_checksums":
                {r["id"]: r["sha256"] for r in records},
                "reviews": [{"catalog_url": url, "status": "reviewed_metadata_match",
                             "published_url": "https://example.org/alternate_TMYx.2009-2023.zip",
                             "evidence_ids": ["onebuilding-us", "onebuilding-au-coordinate-xlsx"],
                             "rationale": "Reviewed metadata correspondence only"}]}
    if changed_source:
        registry["source_checksums"]["onebuilding-au-coordinate-xlsx"] = hashlib.sha256(
            b"index").hexdigest()
    if changed_unrelated:
        registry["source_checksums"]["noaa-history"] = hashlib.sha256(b"history").hexdigest()
    reviews_path = root / "reviews.json"
    reviews_path.write_text(json.dumps(registry), encoding="utf-8")
    return reviews_path


def test_missing_snapshots_fail_without_network(tmp_path):
    with pytest.raises(CatalogImportError, match="SNAPSHOT_MISSING"):
        import_stage1(tmp_path)


def test_noaa_sparse_years_and_reviewed_position_are_distinct(tmp_path):
    reviews = _snapshot(tmp_path)
    bundle = import_stage1(tmp_path, reviews_path=reviews)
    noaa = next(s for s in bundle.sites if s.id == "A00002")
    years = next(e.scope for e in bundle.entries if e.site_id == noaa.id)
    assert years.years == [2001, 2003]
    assert years.month_counts[2001][1] == 2
    reviewed = bundle.reviews[0]
    assert reviewed.status == "reviewed_metadata_match"
    assert reviewed.original_position_status == "unknown"
    assert reviewed.weather_equivalence_verified is False
    product_site = next(s for s in bundle.sites if s.product_id == reviewed.product_id)
    assert (product_site.lat, product_site.lon) == (42.0, -76.0)
    assert product_site.station_identity_status == "ambiguous"


def test_changed_source_invalidates_reviewed_coordinate_authority(tmp_path):
    reviews = _snapshot(tmp_path, changed_source=True)
    bundle = import_stage1(tmp_path, reviews_path=reviews)
    reviewed = bundle.reviews[0]
    assert reviewed.status == "stale_evidence"
    assert reviewed.coordinate_authority is None
    product_site = next(s for s in bundle.sites if s.product_id == reviewed.product_id)
    assert product_site.lat is None


def test_unrelated_source_change_does_not_invalidate_review(tmp_path):
    reviews = _snapshot(tmp_path, changed_unrelated=True)
    bundle = import_stage1(tmp_path, reviews_path=reviews)
    assert bundle.reviews[0].status == "reviewed_metadata_match"


def test_packaged_reviews_match_accepted_registry():
    packaged = Path(__file__).parents[2] / "src/openepw/availability/data/onebuilding_reviews.json"
    accepted = Path(__file__).parents[2] / "scripts/mcp_research/data/onebuilding_reviews.json"
    assert hashlib.sha256(packaged.read_bytes()).digest() == hashlib.sha256(accepted.read_bytes()).digest()


@pytest.mark.skipif(os.getenv("OPENEPW_TEST_STAGE1_SNAPSHOT") != "1",
                    reason="Original ignored Stage 1 snapshot import is opt-in")
def test_original_local_snapshot_counts(tmp_path):
    root = Path(__file__).parents[2] / ".local/mcp-availability"
    if not root.is_dir():
        pytest.skip("Original ignored Stage 1 snapshots unavailable")
    bundle = import_stage1(root)
    noaa_rows = sum(len(e.scope.years) for e in bundle.entries if e.product_id == "noaa:isd")
    assert noaa_rows == 154_841
    assert {status: sum(r.status == status for r in bundle.reviews) for status in
            ("reviewed_metadata_match", "approximate_locality", "name_code_conflict")} == {
                "reviewed_metadata_match": 56, "approximate_locality": 3,
                "name_code_conflict": 2,
            }
    assert sum(p.provider == "cmip6" for p in bundle.products) == 636
    assert sum(s.product_id == "oedi:rcp45" for s in bundle.sites) == 2368
    assert sum(s.product_id == "oedi:rcp85" for s in bundle.sites) == 2368
    assert sum(e.product_id == "oedi:rcp45" for e in bundle.entries) == 4736
    assert sum(e.product_id == "oedi:rcp85" for e in bundle.entries) == 4736
    catalog = CatalogStore(tmp_path)
    staged = catalog.stage(bundle)
    catalog.activate(staged.generation_id)
    assert len(catalog.active().bundle.reviews) == 61
