"""Offline contracts for the research-only NSRDB coverage map."""

import base64
import gzip
import hashlib
import io
import json
import re
from dataclasses import replace

import h5py
import numpy as np
import pytest

from scripts.mcp_availability_map.acquire_nsrdb_meta import acquire_meta, source_spec
from scripts.mcp_availability_map.acquire_nsrdb_meta import main as acquire_main
from scripts.mcp_availability_map.build import build_map
from scripts.mcp_availability_map.build import main as build_main
from scripts.mcp_availability_map.nsrdb_coverage import (
    AGGREGATE_ID,
    REVIEWED_OBJECT_KEY,
    TMY_ID,
    CoverageManifest,
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
                "source_file_id": REVIEWED_OBJECT_KEY,
                "source_version": "4.0.1",
                "selector_kind": kind,
                "selector": selector,
                "basis": "source_grid_sites",
                "retrieved_at": "2026-09-24T12:00:00Z",
                "source_modified_at": "2024-09-16T20:14:37Z",
                "object_etag": '"example-2"',
                "object_size": 123,
                "meta_sha256": hashlib.sha256(b"synthetic meta").hexdigest(),
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
    (tmp_path / "meta.bin").write_bytes(b"synthetic meta")
    return path


def test_actual_year_interval_separates_all_and_some_years(tmp_path):
    base = load_coverage_manifest(_manifest(
        tmp_path, [(TMY_ID, "published_name", "tdy-2023", [[1, 1]], False)]
    )).entries[0]
    manifest = CoverageManifest((
        replace(base, product_id=AGGREGATE_ID, selector_kind="actual_year", selector="2023",
                cells=frozenset({(1, 1), (2, 2)})),
        replace(base, product_id=AGGREGATE_ID, selector_kind="actual_year", selector="2024",
                cells=frozenset({(2, 2), (3, 3)})),
    ))
    result = classify_coverage(AGGREGATE_ID, ("2023", "2024"), manifest)
    assert result.selector_kind == "actual_year"
    assert result.confirmed_all == frozenset({(2, 2)})
    assert result.confirmed_some == frozenset({(1, 1), (3, 3)})
    assert result.unknown is False


def test_missing_year_does_not_shade_all_years(tmp_path):
    base = load_coverage_manifest(_manifest(
        tmp_path, [(TMY_ID, "published_name", "tdy-2023", [[1, 1]], False)]
    )).entries[0]
    manifest = CoverageManifest((replace(base, product_id=AGGREGATE_ID,
                                         selector_kind="actual_year", selector="2023"),))
    result = classify_coverage(AGGREGATE_ID, ("2023", "2024"), manifest)
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


def test_manifest_requires_reviewed_source_identity(tmp_path):
    path = _manifest(tmp_path, [(TMY_ID, "published_name", "tdy-2023", [[10, 20]], False)])
    document = json.loads(path.read_text(encoding="utf-8"))
    document["entries"][0]["source_file_id"] = "GOES/tmy/v4.0.0/nsrdb_tgy-2023.h5"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="source object"):
        load_coverage_manifest(path)
    document["entries"][0]["source_file_id"] = REVIEWED_OBJECT_KEY
    document["entries"][0]["source_version"] = "4.0.0"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="source object"):
        load_coverage_manifest(path)
    document["entries"][0]["source_version"] = "4.0.1"
    document["entries"][0]["selector"] = "tgy-2023"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="unreviewed"):
        load_coverage_manifest(path)


def test_build_map_requires_source_metadata_bytes(tmp_path):
    snapshot = _map_snapshot(tmp_path)
    footprint_root = tmp_path / "footprints" / TMY_ID / "tdy-2023"
    footprint_root.mkdir(parents=True)
    _manifest(footprint_root, [(TMY_ID, "published_name", "tdy-2023", [[529, 414]], False)])
    (footprint_root / "meta.bin").unlink()
    topology = tmp_path / "world.json"
    topology.write_text('{"type":"Topology","objects":{"countries":{}},"arcs":[]}',
                        encoding="utf-8")
    with pytest.raises(ValueError, match="source meta bytes missing"):
        build_map(snapshot, tmp_path / "output", footprint_root.parent.parent, topology)


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


class _RangeBody(io.BytesIO):
    status = 206


class _LocalTransport:
    def __init__(self, path):
        self.data = path.read_bytes()
        self.etag = '"source-1"'
        self.partial = False
        self.fail = False
        self.requests = []

    def head(self, url, if_none_match=None):
        if if_none_match == self.etag:
            return None
        return {"size": len(self.data), "etag": self.etag, "modified": "2024-09-16T20:14:37Z"}

    def open_range(self, url, start, end, etag):
        assert etag == self.etag
        self.requests.append((start, end))
        if self.fail:
            raise OSError("simulated source failure")
        data = self.data[start : end + 1]
        if self.partial and len(data) > 100:
            data = data[:-1]
        return _RangeBody(data)


def _h5_fixture(path, points, version="4.0.1"):
    dtype = np.dtype([("latitude", "<f4"), ("longitude", "<f4"), ("country", "S4")])
    rows = np.zeros(len(points), dtype=dtype)
    for index, (lat, lon) in enumerate(points):
        rows[index] = (lat, lon, b"USA")
    with h5py.File(path, "w") as file:
        file.attrs["version"] = version
        file.create_dataset("meta", data=rows)
        file.create_dataset("ghi", data=np.ones((2, len(points)), dtype="u2"))
    return path


def test_acquire_meta_reads_only_grid_metadata_and_pins_source(tmp_path):
    source = _h5_fixture(tmp_path / "source.h5", [(42.44, -76.5), (33.45, -112.07)])
    transport = _LocalTransport(source)
    spec = source_spec(TMY_ID, "tdy-2023")
    manifest_path = acquire_meta(
        spec, tmp_path / "output", transport,
        probes=((42.44, -76.5), (33.45, -112.07)), block_bytes=1024,
    )
    manifest = load_coverage_manifest(manifest_path)
    assert manifest.entries[0].source_version == "4.0.1"
    assert manifest.entries[0].coordinate_count == 2
    assert manifest.entries[0].selector == "tdy-2023"
    assert manifest.entries[0].cells == occupied_cells(
        [(42.44, -76.5), (33.45, -112.07)], 0.25
    )
    assert all((end - start + 1) < len(transport.data) for start, end in transport.requests)
    assert acquire_meta(spec, tmp_path / "output", transport,
                        probes=((42.44, -76.5), (33.45, -112.07)), block_bytes=1024) == manifest_path


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_acquire_meta_rejects_damaged_local_metadata_on_unchanged_source(tmp_path, damage):
    source = _h5_fixture(tmp_path / "source.h5", [(42.44, -76.5)])
    transport = _LocalTransport(source)
    spec = source_spec(TMY_ID, "tdy-2023")
    root = tmp_path / "output"
    manifest = acquire_meta(spec, root, transport, probes=((42.44, -76.5),),
                            block_bytes=1024)
    meta = manifest.parent / "meta.bin"
    if damage == "missing":
        meta.unlink()
    else:
        meta.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="local meta checksum"):
        acquire_meta(spec, root, transport, probes=((42.44, -76.5),),
                     block_bytes=1024)


def test_acquire_meta_rejects_partial_or_oversize_transfer(tmp_path):
    source = _h5_fixture(tmp_path / "source.h5", [(42.44, -76.5)])
    transport = _LocalTransport(source)
    spec = source_spec(TMY_ID, "tdy-2023")
    transport.partial = True
    with pytest.raises(ValueError, match="incomplete range"):
        acquire_meta(spec, tmp_path / "partial", transport, probes=((42.44, -76.5),),
                     block_bytes=1024)
    transport.partial = False
    with pytest.raises(ValueError, match="byte cap"):
        acquire_meta(spec, tmp_path / "oversize", transport, probes=((42.44, -76.5),),
                     max_bytes=64, block_bytes=1024)


def test_acquire_meta_stales_prior_mask_on_changed_object(tmp_path):
    source = _h5_fixture(tmp_path / "source.h5", [(42.44, -76.5)])
    transport = _LocalTransport(source)
    spec = source_spec(TMY_ID, "tdy-2023")
    path = acquire_meta(spec, tmp_path / "output", transport, probes=((42.44, -76.5),),
                        block_bytes=1024)
    transport.etag = '"source-2"'
    transport.fail = True
    with pytest.raises(OSError, match="source failure"):
        acquire_meta(spec, tmp_path / "output", transport, probes=((42.44, -76.5),),
                     block_bytes=1024)
    assert load_coverage_manifest(path).entries[0].stale is True


def test_acquire_meta_rejects_bad_source_or_coordinates(tmp_path):
    with pytest.raises(ValueError, match="selector"):
        source_spec(TMY_ID, "2023")
    with pytest.raises(ValueError, match="selector"):
        source_spec(AGGREGATE_ID, "../2023")
    with pytest.raises(ValueError, match="selector"):
        source_spec(AGGREGATE_ID, "2023")
    with pytest.raises(ValueError, match="selector"):
        source_spec(TMY_ID, "tgy-2023")
    for points, expected in [
        ([(42.44, -76.5), (42.44, -76.5)], "duplicate"),
        ([(float("nan"), -76.5)], "coordinate"),
    ]:
        source = _h5_fixture(tmp_path / "source.h5", points)
        with pytest.raises(ValueError, match=expected):
            acquire_meta(source_spec(TMY_ID, "tdy-2023"), tmp_path / "output",
                         _LocalTransport(source), probes=(), block_bytes=1024)


def test_acquire_meta_rejects_grid_that_disagrees_with_point_catalog(tmp_path):
    source = _h5_fixture(tmp_path / "source.h5", [(42.44, -76.5)])
    with pytest.raises(ValueError, match="point probe"):
        acquire_meta(source_spec(TMY_ID, "tdy-2023"), tmp_path / "output",
                     _LocalTransport(source), probes=((0.0, 0.0),), block_bytes=1024)


def _map_snapshot(tmp_path):
    root = tmp_path / "snapshots"
    (root / "raw").mkdir(parents=True)
    records = []
    for ident, lon, lat in (("nsrdb-ithaca", -76.5, 42.44),
                            ("nsrdb-phoenix", -112.07, 33.45)):
        raw = json.dumps({
            "inputs": {"query": {"wkt": f"POINT({lon} {lat})"}},
            "outputs": [
                {"name": AGGREGATE_ID, "availableYears": [2023, 2024]},
                {"name": TMY_ID, "availableYears": ["tdy-2023"],
                 "links": [{"url": "https://example.invalid/?api_key=SECRET"}]},
            ],
        }).encode()
        (root / "raw" / f"{ident}.body").write_bytes(raw)
        records.append({"id": ident, "snapshot": f"raw/{ident}.body",
                        "sha256": hashlib.sha256(raw).hexdigest()})
    (root / "ledger.json").write_text(json.dumps({"records": records}), encoding="utf-8")
    (root / "analysis.json").write_text(json.dumps({"inventories": {
        "noaa-history": {"sites": []},
        "noaa-inventory-authorized": {"station_years": {},
                                      "stations_without_history_coordinates": 0},
        "onebuilding-us": {"coordinate_matches": [], "product_count": 0},
        "onebuilding-uk": {"coordinate_matches": [], "product_count": 0},
        "onebuilding-au": {"coordinate_matches": [], "product_count": 0},
        "oedi-sites": {"sites": []},
    }}), encoding="utf-8")
    return root


def test_build_map_uses_published_nsrdb_grid_without_point_probes(tmp_path):
    snapshot = _map_snapshot(tmp_path)
    footprint_root = tmp_path / "footprints" / TMY_ID / "tdy-2023"
    footprint_root.mkdir(parents=True)
    _manifest(footprint_root, [(TMY_ID, "published_name", "tdy-2023", [[529, 414]], False)])
    topology = tmp_path / "world.json"
    topology.write_text(json.dumps({"type": "Topology", "objects": {"countries": {
        "type": "GeometryCollection", "geometries": []}}, "arcs": []}), encoding="utf-8")
    html_path = build_map(snapshot, tmp_path / "output", footprint_root.parent.parent, topology)
    html = html_path.read_text(encoding="utf-8")
    encoded = re.search(r'<script type="text/plain" id="oepw-payload">([^<]+)</script>', html)
    assert encoded
    assert int.from_bytes(base64.b64decode(encoded.group(1))[4:8], "little") == 0
    payload = json.loads(gzip.decompress(base64.b64decode(encoded.group(1))))
    assert payload["schema"] == "stage2-map-2"
    assert "points" not in payload["nsrdb"]
    assert list(payload["nsrdb"]["masks"]) == ["published:tdy-2023"]
    assert payload["nsrdb"]["masks"]["published:tdy-2023"]["cells"] == [[529, 414]]
    assert payload["nsrdb"]["masks"]["published:tdy-2023"]["basis"] == "source_grid_sites"
    assert 'value="nsrdb-actual"' not in html
    assert "nsrdbPoints" not in html
    assert "Ithaca" not in html and "Phoenix" not in html
    assert "source grid sites" in html.lower()
    assert "td y" not in html.lower()
    assert "https://developer.nlr.gov/docs/solar/nsrdb/" in html
    assert "CC BY 3.0 US" in html
    assert "SECRET" not in html
    assert "api_key=" not in html


def test_build_map_summarizes_pinned_cmip6_licenses_by_scenario(tmp_path):
    snapshot = _map_snapshot(tmp_path)
    analysis = json.loads((snapshot / "analysis.json").read_text(encoding="utf-8"))
    analysis["inventories"]["cmip6-catalog"] = {"combinations": [
        {"model": "M1", "scenario": "ssp126", "stores": {"historical/tas": "gs://secret-a"}},
        {"model": "M1", "scenario": "ssp245", "stores": {"historical/tas": "gs://secret-b"}},
        {"model": "M2", "scenario": "ssp245", "stores": {"historical/tas": "gs://secret-c"}},
        {"model": "M3", "scenario": "ssp585", "stores": {"historical/tas": "gs://secret-d"}},
    ]}
    (snapshot / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    registry = {"source_id": {
        "M1": {"license_info": {"id": "CC BY 4.0"}},
        "M2": {"license_info": {"id": "CC0 1.0"}},
    }}
    raw = json.dumps(registry).encode()
    (snapshot / "raw" / "cmip6-license.body").write_bytes(raw)
    catalog_raw = b"pinned catalog"
    (snapshot / "raw" / "cmip6-catalog.body").write_bytes(catalog_raw)
    ledger = json.loads((snapshot / "ledger.json").read_text(encoding="utf-8"))
    for ident, body in (("cmip6-catalog", catalog_raw), ("cmip6-license", raw)):
        ledger["records"].append({"id": ident, "snapshot": f"raw/{ident}.body",
                                  "sha256": hashlib.sha256(body).hexdigest()})
    (snapshot / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    topology = tmp_path / "world.json"
    topology.write_text(json.dumps({"type": "Topology", "objects": {"countries": {
        "type": "GeometryCollection", "geometries": []}}, "arcs": []}), encoding="utf-8")

    html = build_map(snapshot, tmp_path / "output", tmp_path / "footprints", topology).read_text(
        encoding="utf-8"
    )
    encoded = re.search(r'<script type="text/plain" id="oepw-payload">([^<]+)</script>', html)
    payload = json.loads(gzip.decompress(base64.b64decode(encoded.group(1))))
    cmip6 = payload["cmip6"]
    assert cmip6["total"] == 4
    assert cmip6["models"] == 3
    assert cmip6["license_counts"] == {"CC BY 4.0": 2, "CC0 1.0": 1, "unknown": 1}
    assert cmip6["scenarios"]["ssp245"] == {
        "total": 2, "models": 2, "license_counts": {"CC BY 4.0": 1, "CC0 1.0": 1}
    }
    assert "gs://secret-" not in html


def test_build_map_does_not_claim_cmip6_license_without_registry(tmp_path):
    snapshot = _map_snapshot(tmp_path)
    analysis = json.loads((snapshot / "analysis.json").read_text(encoding="utf-8"))
    analysis["inventories"]["cmip6-catalog"] = {"combinations": [
        {"model": "M1", "scenario": "ssp245"}
    ]}
    (snapshot / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    catalog_raw = b"pinned catalog"
    (snapshot / "raw" / "cmip6-catalog.body").write_bytes(catalog_raw)
    ledger = json.loads((snapshot / "ledger.json").read_text(encoding="utf-8"))
    ledger["records"].append({"id": "cmip6-catalog", "snapshot": "raw/cmip6-catalog.body",
                              "sha256": hashlib.sha256(catalog_raw).hexdigest()})
    (snapshot / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
    topology = tmp_path / "world.json"
    topology.write_text(json.dumps({"type": "Topology", "objects": {"countries": {
        "type": "GeometryCollection", "geometries": []}}, "arcs": []}), encoding="utf-8")

    html = build_map(snapshot, tmp_path / "output", tmp_path / "footprints", topology).read_text(
        encoding="utf-8"
    )
    encoded = re.search(r'<script type="text/plain" id="oepw-payload">([^<]+)</script>', html)
    payload = json.loads(gzip.decompress(base64.b64decode(encoded.group(1))))
    assert payload["cmip6"]["license_counts"] == {"unknown": 1}


def test_build_map_rejects_mismatched_stage1_snapshot(tmp_path):
    snapshot = _map_snapshot(tmp_path)
    (snapshot / "raw" / "nsrdb-phoenix.body").write_text("{}", encoding="utf-8")
    topology = tmp_path / "world.json"
    topology.write_text('{"type":"Topology","objects":{"countries":{}},"arcs":[]}',
                        encoding="utf-8")
    with pytest.raises(ValueError, match="raw checksum"):
        build_map(snapshot, tmp_path / "output", tmp_path / "footprints", topology)


def test_map_cli_rejects_output_outside_ignored_local_tree(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "map", "--snapshot-root", str(tmp_path), "--topology", str(tmp_path / "world.json"),
        "--output-root", str(tmp_path / "tracked-docs"),
    ])
    with pytest.raises(ValueError, match="ignored .local"):
        build_main()


def test_acquisition_cli_rejects_output_outside_ignored_local_tree(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", [
        "acquire", TMY_ID, "tdy-2023", "--output-root", str(tmp_path / "tracked-docs"),
    ])
    with pytest.raises(ValueError, match="ignored .local"):
        acquire_main()
