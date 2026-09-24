"""Accepted review annotations must never silently upgrade weather identity."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from mcp_research import reviews


def registry(status="reviewed_metadata_match"):
    return {
        "accepted_on": "2026-09-24",
        "source_checksums": {"index": "abc"},
        "reviews": [
            {
                "catalog_url": "https://example.org/a.zip",
                "published_url": "https://example.org/b.zip",
                "status": status,
                "evidence_ids": ["index"],
                "rationale": "Reviewed case",
                "lat": 42,
                "lon": -76,
            }
        ],
    }


def test_review_requires_pinned_evidence_and_preserves_automatic_record():
    row = {"url": "https://example.org/a.zip", "lat": None, "coordinate_basis": "unknown"}
    published = [
        {
            "url": "https://example.org/b.zip",
            "evidence_id": "index",
            "lat": 42,
            "lon": -76,
            "elevation_m": 10,
        }
    ]
    out = reviews.annotate([row], published, {"index": "abc"}, registry())[0]
    assert out["review"]["status"] == "reviewed_metadata_match"
    assert out["review"]["coordinates"] == {"lat": 42, "lon": -76, "elevation_m": 10}
    assert out["lat"] is None
    assert out["coordinate_basis"] == "unknown"
    assert "review" not in row
    assert (
        reviews.annotate([row], published, {"index": "changed"}, registry())[0]["review"]["status"]
        == "stale_evidence"
    )
    assert (
        reviews.annotate([row], [], {"index": "abc"}, registry())[0]["review"]["status"]
        == "unresolved_evidence"
    )


def test_locality_and_conflict_do_not_claim_exact_coordinates_or_station():
    row = {"url": "https://example.org/a.zip", "lat": None, "source_station_id": None}
    for status in ("approximate_locality", "name_code_conflict"):
        out = reviews.annotate([row], [], {"index": "abc"}, registry(status))[0]
        assert out["review"]["epw_coordinates_verified"] is False
        assert out["source_station_id"] is None
        assert out["lat"] is None
        assert "coordinates" not in out["review"]
        assert ("approximate_location" in out["review"]) == (status == "approximate_locality")


def test_conflicting_published_points_and_unreviewed_urls_are_not_accepted():
    row = {"url": "https://example.org/a.zip"}
    published = [
        dict(url="https://example.org/b.zip", evidence_id="index", lat=42, lon=-76, elevation_m=10),
        dict(url="https://example.org/b.zip", evidence_id="index", lat=43, lon=-76, elevation_m=10),
    ]
    out = reviews.annotate(
        [row, {"url": "https://example.org/c.zip"}], published, {"index": "abc"}, registry()
    )
    assert out[0]["review"]["status"] == "unresolved_evidence"
    assert "review" not in out[1]


def test_analysis_does_not_accept_failed_snapshot_checksums(tmp_path, monkeypatch):
    import json

    from mcp_research import analysis

    records = [
        dict(
            id="onebuilding-us",
            provider="onebuilding",
            url="https://example.org/catalog",
            outcome="saved",
            sha256="index",
        ),
        dict(
            id="noaa-history",
            provider="noaa",
            url="https://example.org/history",
            outcome="saved",
            sha256="broken",
        ),
    ]
    (tmp_path / "ledger.json").write_text(json.dumps({"records": records}))

    def snapshot(root, record):
        if record["id"] == "noaa-history":
            raise ValueError("Checksum mismatch")
        return b'<a href="https://example.org/a.zip">product</a>'

    monkeypatch.setattr(analysis, "read_snapshot", snapshot)
    accepted = registry("approximate_locality")
    accepted["source_checksums"] = {"onebuilding-us": "index", "noaa-history": "broken"}
    accepted["reviews"][0]["evidence_ids"] = ["onebuilding-us", "noaa-history"]
    monkeypatch.setattr(analysis, "load_registry", lambda: accepted)
    result = analysis.analyze(tmp_path)
    assert result["errors"]
    assert result["inventories"]["onebuilding-us"]["accepted_review_counts"] == {
        "stale_evidence": 1
    }
