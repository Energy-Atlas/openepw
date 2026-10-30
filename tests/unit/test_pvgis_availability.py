"""PVGIS 5.3 TMY availability (2026-10-13 availability-gaps plan, item 1): one product whose
radiation is SARAH3 or ERA5 by location (D1), gated by a domain mask with an explicit unknown
band (D2). Synthetic data only."""

import hashlib
import json
from datetime import datetime, timezone

import numpy as np

from openepw.availability import (
    CatalogSnapshotRef,
    EvidenceRef,
    WeatherAvailabilityQuery,
)
from openepw.availability.coverage import GridCoverage, load_coverage
from openepw.availability.evaluate import evaluate
from openepw.availability.importers import normalize_analysis
from openepw.availability.map_layers import catalog_map
from openepw.availability.store import CatalogView
from openepw.models import Location, WeatherRequest
from scripts.mcp_availability_map.pvgis_mask import classes, station_points

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
LONDON = (51.507, -0.128)


def _write(root, mask):
    folder = root / "pvgis" / "tmy-v5_3" / "domain"
    folder.mkdir(parents=True)
    raw = json.dumps(mask).encode()
    (folder / "mask.json").write_bytes(raw)
    entry = {"product_id": "pvgis-tmy-v5_3", "selector": "domain", "selector_kind": "documented_domain",
             "mask_path": "mask.json", "mask_sha256": hashlib.sha256(raw).hexdigest(),
             "step_degrees": mask["step_degrees"], "cell_origin": "center", "gates": ["pvgis:PVGIS TMY"]}
    (folder / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")


# 1-degree centred cells: inside at 50-52 N, 2 W-1 E; edge band one cell around it.
MASK = {"step_degrees": 1.0, "cell_origin": "center",
        "runs": [[row, 178, 182] for row in range(140, 143)],
        "edge_runs": [[139, 177, 183], [143, 177, 183], *[[row, 177, 178] for row in range(140, 143)],
                      *[[row, 182, 183] for row in range(140, 143)]]}


def test_an_explicit_edge_band_replaces_the_neighbour_rule(tmp_path):
    _write(tmp_path, MASK)
    coverage = load_coverage(tmp_path)["pvgis:PVGIS TMY"]
    assert coverage.where(*LONDON) == "inside"
    assert coverage.where(53.0, 0.0) == "edge"                 # listed band
    assert coverage.where(54.0, 0.0) == "outside"              # next to the band, not listed
    plain = GridCoverage.from_runs(1.0, MASK["runs"], ("x",), centred=True)
    assert plain.where(53.0, 0.0) == "edge" and plain.where(54.0, 0.0) == "outside"


def _bundle(probes=("pvgis-london",)):
    evidence = [EvidenceRef(id=name, sha256="a" * 64, retrieved_at=NOW, basis="targeted_probe")
                for name in probes]
    points = {"pvgis-london": LONDON, "pvgis-ithaca": (42.44, -76.5), "pvgis-lake-victoria": (-1.0, 33.0)}
    sources = {"pvgis-ithaca": "PVGIS-ERA5"}
    inventories = {name: {"location": {"latitude": points[name][0], "longitude": points[name][1]},
                          "meteo_data": {"radiation_db": sources.get(name, "PVGIS-SARAH3"),
                                         "year_min": 2005, "year_max": 2023},
                          "months_selected": [{"month": 1, "year": 2016 if name == "pvgis-london" else 2015}]}
                   for name in probes}
    return normalize_analysis(inventories, evidence)


def test_each_probe_keeps_its_own_months_and_the_domain_has_none():
    bundle = _bundle(("pvgis-london", "pvgis-ithaca", "pvgis-lake-victoria"))
    [product] = [p for p in bundle.products if p.provider == "pvgis"]
    assert product.evidence_ids == ["pvgis-ithaca", "pvgis-lake-victoria", "pvgis-london"]
    entries = {e.id: e for e in bundle.entries if e.product_id == "pvgis:tmy:v5_3"}
    assert set(entries) == {"pvgis:tmy:v5_3:london-probe", "pvgis:tmy:v5_3:ithaca-probe",
                            "pvgis:tmy:v5_3:lake-victoria-probe", "pvgis:tmy:v5_3:documented-domain"}
    assert entries["pvgis:tmy:v5_3:london-probe"].scope.selected_month_years == {1: 2016}
    assert entries["pvgis:tmy:v5_3:london-probe"].scope.product_label == "PVGIS TMY v5_3 London"
    assert entries["pvgis:tmy:v5_3:lake-victoria-probe"].scope.product_label == "PVGIS TMY v5_3 Lake Victoria"
    domain = entries["pvgis:tmy:v5_3:documented-domain"]
    assert (domain.scope.start_year, domain.scope.end_year) == (2005, 2023)
    assert domain.scope.selected_month_years == {} and domain.probe_location is None
    assert domain.evidence_basis == "documentation"


def _decision(bundle, lat, lon, coverage):
    request = WeatherRequest(locations=Location(lat=lat, lon=lon), product="tmy")
    view = CatalogView(CatalogSnapshotRef(generation_id="synthetic", created_at=NOW), bundle)
    [option] = [option for option in evaluate(WeatherAvailabilityQuery(request=request), view, coverage).options
                if option.product.provider == "pvgis"]
    return option.eligibility


def test_the_domain_mask_gates_pvgis(tmp_path):
    _write(tmp_path, MASK)
    coverage = load_coverage(tmp_path)
    bundle = _bundle(("pvgis-london", "pvgis-ithaca"))
    inside = _decision(bundle, 50.2, 1.4, coverage)                  # not a probe point
    assert inside.status == "supported" and "INSIDE_SOURCE_COVERAGE" in inside.reasons
    assert inside.evidence_bases == ["documentation"]                # never London's months
    at_probe = _decision(bundle, *LONDON, coverage)
    assert at_probe.status == "supported" and at_probe.evidence_bases == ["targeted_probe"]
    edge = _decision(bundle, 53.0, 0.0, coverage)
    assert edge.status == "unknown" and "NEAR_SOURCE_COVERAGE_EDGE" in edge.unknowns
    outside = _decision(bundle, 40.0, -40.0, coverage)
    assert outside.status == "excluded" and "OUTSIDE_SOURCE_COVERAGE" in outside.reasons
    no_mask = _decision(bundle, 50.2, 1.4, {})
    assert no_mask.status == "unknown" and "TARGETED_PROBE_ONLY" in no_mask.unknowns


def test_the_map_draws_the_domain_mask_when_installed(tmp_path):
    bundle = _bundle()
    fallback = next(layer for layer in catalog_map(bundle, tmp_path)["layers"] if layer["id"] == "pvgis")
    assert fallback["kind"] == "area"
    # 0.1-degree centred cells at 51.5 N from 0.5 W to 0.4 E: one 0.5-degree display row.
    _write(tmp_path, {"step_degrees": 0.1, "cell_origin": "center", "runs": [[1415, 1795, 1805]],
                      "edge_runs": []})
    layer = next(layer for layer in catalog_map(bundle, tmp_path)["layers"] if layer["id"] == "pvgis")
    assert layer["kind"] == "cells" and layer["step"] == 0.5 and layer["count"] == 2
    assert layer["rects"] == [[-0.5, 51.5, 0.5, 52.0]]


def _grid(step=1.0):
    """A synthetic 1-degree world: open ocean, one continent with a lake, an atoll."""
    lats = -90 + step * np.arange(round(180 / step) + 1)
    field = np.zeros((len(lats), round(360 / step)))
    field[120:160, 170:200] = 1.0              # land 30-69 N, 10 W-19 E
    field[135:140, 180:185] = 0.0              # an enclosed lake at 45-49 N, 0-4 E
    field[150:154, 165:170] = 0.3              # a coastal sliver with some land fraction, 60-63 N
    field[165:167, 175:180] = 1.0              # land at 75 and 76 N
    return field, lats


def test_mask_rule_on_a_synthetic_world():
    field, lats = _grid()
    inside, edge = classes(field, lats, 1.0)

    def place(lat, lon):
        row, column = round(lat + 90), round(lon + 180) % 360
        return "inside" if inside[row, column] else "edge" if edge[row, column] else "outside"

    assert place(40, 5) == "inside"
    assert place(47, 2) == "edge"              # enclosed lake: not the sea, not land
    assert place(61, -13) == "edge"            # some land fraction, below 0.5
    assert place(69, -11) == "edge"            # one degree of longitude is 40 km at 69 N
    assert place(40, -11) == "outside"         # 85 km at 40 N
    assert place(0, -150) == "outside"
    assert place(75, -3) == "edge" and place(76, -3) == "outside"       # the grid's 75 N limit
    assert place(-70, 5) == "outside"
    # An atoll the land fraction misses is protected by a published station position.
    assert place(10, -100) == "outside"
    inside, edge = classes(field, lats, 1.0, [(10.0, -100.0)])
    assert not inside[100, 80] and edge[100, 80]


def test_station_points_skip_placeholders_and_take_workbook_rows():
    analysis = {"inventories": {
        "noaa-history": {"sites": [{"lat": 0.0, "lon": 0.0}, {"lat": 4.19, "lon": 73.53}]},
        "onebuilding-region2-xlsx": {"rows": [{"lat": -8.52, "lon": 179.2}, {"lat": None, "lon": 1}]},
        "pvgis-london": {"meteo_data": {}}}}
    points, sources = station_points(analysis)
    assert points == [(4.19, 73.53), (-8.52, 179.2)]
    assert sources == ["noaa-history", "onebuilding-region2-xlsx"]


def test_a_refine_layer_turns_listed_fine_cells_of_the_band_inside(tmp_path):
    # Fine 0.25-degree cells (corner origin) at 53.00-53.25 N, 0.00-0.25 E inside the band cell 53 N.
    row, column = int((53.0 + 90) / 0.25), int((0.0 + 180) / 0.25)
    _write(tmp_path, {**MASK, "refine": {"step_degrees": 0.25, "cell_origin": "corner",
                                         "runs": [[row, column, column + 1]]}})
    coverage = load_coverage(tmp_path)["pvgis:PVGIS TMY"]
    assert coverage.where(53.1, 0.1) == "inside"               # listed fine cell
    assert coverage.where(53.1, -0.1) == "edge"                # same band cell, fine cell not listed
    assert coverage.where(54.1, 0.1) == "outside"              # never outside the band
    assert coverage.where(*LONDON) == "inside"


def test_coast_rasterises_polygons_and_keeps_an_inland_margin():
    import io
    import struct
    import zipfile

    from scripts.mcp_availability_map.coast import inland, land_rows, polygon_edges

    ring = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]       # a 1-degree square
    content = struct.pack("<i", 5) + struct.pack("<4d", 0, 0, 1, 1) + struct.pack("<ii", 1, len(ring))
    content += struct.pack("<i", 0) + b"".join(struct.pack("<2d", *point) for point in ring)
    record = struct.pack(">ii", 1, len(content) // 2) + content
    header = struct.pack(">i", 9994) + b"\0" * 20 + struct.pack(">i", (100 + len(record)) // 2)
    header += struct.pack("<ii", 1000, 5) + struct.pack("<8d", 0, 0, 1, 1, 0, 0, 0, 0)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ne_10m_land.shp", header + record)
    edges = polygon_edges(buf.getvalue())
    step = 0.25
    rows = range(int(89.0 / step), int(92.0 / step))                         # 1 S to 2 N
    land = land_rows(edges, rows, step)
    columns = [int((lon + 180) / step) for lon in (0.125, 0.875, 1.125)]
    first = int(90.0 / step) - rows.start                                    # the row at 0.0-0.25 N
    assert land[first, columns].tolist() == [True, True, False]
    core = inland(land)
    assert core[first + 1, int(180.375 / step)] and not core[first, int(180.125 / step)]
