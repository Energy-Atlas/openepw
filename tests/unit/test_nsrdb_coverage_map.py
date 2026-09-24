"""Offline contracts for the research-only NSRDB coverage map."""

import hashlib
import json

import pytest

from scripts.mcp_availability_map.nsrdb_coverage import (
    AGGREGATE_ID,
    TMY_ID,
    classify_coverage,
    load_coverage_manifest,
    load_point_catalogs,
    occupied_cells,
)


def _manifest(tmp_path, specs):
    entries = []
    for index, (product, kind, selector, cells, stale) in enumerate(specs):
        raw = json.dumps({"cells": cells, "step_degrees": 0.25}, sort_keys=True).encode()
        name = f"mask-{index}.json"
        (tmp_path / name).write_bytes(raw)
        entries.append(
            {
                "product_id": product,
                "source_file_id": f"GOES/{'tmy' if product == TMY_ID else 'aggregated'}/v4.0.0/example.h5",
                "source_version": "4.0.1",
                "selector_kind": kind,
                "selector": selector,
                "basis": "source_grid_sites",
                "retrieved_at": "2026-09-24T12:00:00Z",
                "source_modified_at": "2024-09-16T20:14:37Z",
                "object_etag": '"example-2"',
                "meta_sha256": "a" * 64,
                "mask_sha256": hashlib.sha256(raw).hexdigest(),
                "mask_path": name,
                "coordinate_count": 100,
                "native_crs": "EPSG:4326",
                "native_longitude_convention": "-180_to_180",
                "stale": stale,
            }
        )
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": entries}), encoding="utf-8")
    return path


def test_actual_year_interval_separates_all_and_some_years(tmp_path):
    path = _manifest(
        tmp_path,
        [
            (AGGREGATE_ID, "actual_year", "2023", [[1, 1], [2, 2]], False),
            (AGGREGATE_ID, "actual_year", "2024", [[2, 2], [3, 3]], False),
        ],
    )
    result = classify_coverage(AGGREGATE_ID, ("2023", "2024"), load_coverage_manifest(path))
    assert result.selector_kind == "actual_year"
    assert result.confirmed_all == frozenset({(2, 2)})
    assert result.confirmed_some == frozenset({(1, 1), (3, 3)})
    assert result.unknown is False


def test_missing_year_does_not_shade_all_years(tmp_path):
    path = _manifest(
        tmp_path, [(AGGREGATE_ID, "actual_year", "2023", [[1, 1]], False)]
    )
    result = classify_coverage(AGGREGATE_ID, ("2023", "2024"), load_coverage_manifest(path))
    assert result.confirmed_all == frozenset()
    assert result.confirmed_some == frozenset({(1, 1)})
    assert result.unknown is True
    assert "missing_selector:2024" in result.reasons


def test_tdy_suffix_is_a_published_name_not_actual_year(tmp_path):
    path = _manifest(
        tmp_path, [(TMY_ID, "published_name", "tdy-2023", [[10, 20]], False)]
    )
    manifest = load_coverage_manifest(path)
    result = classify_coverage(TMY_ID, ("tdy-2023",), manifest)
    assert result.selector_kind == "published_name"
    assert result.confirmed_all == frozenset({(10, 20)})
    assert classify_coverage(AGGREGATE_ID, ("2023",), manifest).unknown is True


def test_stale_mask_does_not_support_coverage(tmp_path):
    path = _manifest(
        tmp_path, [(TMY_ID, "published_name", "tdy-2023", [[10, 20]], True)]
    )
    result = classify_coverage(TMY_ID, ("tdy-2023",), load_coverage_manifest(path))
    assert result.confirmed_all == frozenset()
    assert result.unknown is True
    assert "stale_selector:tdy-2023" in result.reasons


def test_mask_checksum_and_path_are_validated(tmp_path):
    path = _manifest(
        tmp_path, [(TMY_ID, "published_name", "tdy-2023", [[10, 20]], False)]
    )
    (tmp_path / "mask-0.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="mask checksum"):
        load_coverage_manifest(path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["entries"][0]["mask_path"] = "../outside.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="mask path"):
        load_coverage_manifest(path)


def test_occupied_cells_preserves_holes_and_dateline():
    cells = occupied_cells([(0.01, 179.99), (0.01, -179.99), (0.51, 0.51)], 0.25)
    assert cells == frozenset({(360, 1439), (360, 0), (362, 722)})
    assert (361, 720) not in cells


def test_point_catalogs_verify_original_raw_checksums(tmp_path):
    raw = b'{"outputs":[{"name":"nsrdb-GOES-tmy-v4-0-0","availableYears":["tdy-2023"]}]}'
    (tmp_path / "raw").mkdir()
    for ident in ("nsrdb-ithaca", "nsrdb-phoenix"):
        (tmp_path / "raw" / f"{ident}.body").write_bytes(raw)
    records = [
        {"id": ident, "snapshot": f"raw/{ident}.body", "sha256": hashlib.sha256(raw).hexdigest()}
        for ident in ("nsrdb-ithaca", "nsrdb-phoenix")
    ]
    (tmp_path / "ledger.json").write_text(json.dumps({"records": records}), encoding="utf-8")
    result = load_point_catalogs(tmp_path)
    assert result["nsrdb-ithaca"][TMY_ID] == ["tdy-2023"]
    (tmp_path / "raw" / "nsrdb-phoenix.body").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="raw checksum"):
        load_point_catalogs(tmp_path)
