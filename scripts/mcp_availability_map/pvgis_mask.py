"""PVGIS 5.3 TMY domain mask (2026-10-13 availability-gaps plan, item 1, decision D2).

Built offline from ECMWF's ERA5-Land land-sea mask already held (``era5land-lsm-r1``), on its
0.1 degree grid indexed by cell centre. JRC documents the PVGIS 5.3 domain as land plus a 25 km
sea zone between 60 S and 75 N, with its own coastline (report JRC139355). The rule:

- inside: a land fraction of at least 0.5, with a cell centre between 59.9 S and 74.9 N;
- outside: beyond 60.5 S or 75.5 N, or water connected to the open ocean whose cell centre is
  more than 50 km from every point with any land fraction and from every published station
  position in the research analysis (NOAA ISD sites, OneBuilding workbook rows). The stations
  keep atolls that ERA5-Land does not resolve, such as Male and Funafuti, from being excluded;
- the rest is an explicit edge band (unknown): PVGIS's own coastline, its sea zone, small
  islands, lakes and the grid's latitude limits.

The probes of plan P1 check it: London, Ithaca and Lake Victoria returned a TMY, while the
open Atlantic, the North Sea about 19 km off the coast, and Svalbard did not. Offline; never
fetches anything.

    python -m scripts.mcp_availability_map.pvgis_mask <grib> <footprints root> [<analysis.json>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.mcp_availability_map.era5land_mask import SOURCE_URL, decode

GATES = ("pvgis:PVGIS TMY",)
LAND = 0.5
SEA_KM = 50.0
EARTH_KM_PER_DEGREE = 111.195
INNER = (-59.9, 74.9)            # cell centres inside the PVGIS grid (60 S to 75 N)
OUTER = (-60.5, 75.5)            # beyond these, nothing is served
OCEAN_SEED = (0.0, -150.0)       # mid-Pacific
# Plan P1 results and decoding checks: (lat, lon, expected place).
CHECKS = {
    "London": (51.507, -0.128, "inside"), "Ithaca": (42.44, -76.50, "inside"),
    "Lake Victoria": (-1.0, 33.0, "edge"), "Atlantic": (40.0, -40.0, "outside"),
    "North Sea": (52.30, 4.20, "edge"), "Svalbard": (78.22, 15.65, "outside"),
    "Antarctica": (-75.0, 0.0, "outside"), "Mid-Pacific": (0.0, -150.0, "outside"),
}
# Checked only when station positions are given: atolls ERA5-Land does not resolve.
ATOLLS = {"Male": (4.175, 73.509), "Funafuti": (-8.52, 179.2)}


def station_points(analysis: dict) -> tuple[list[tuple[float, float]], list[str]]:
    """Published station positions from the research analysis, without placeholder (0, 0)."""
    points, sources = [], []
    for key, inventory in sorted(analysis.get("inventories", {}).items()):
        rows = inventory.get("sites") if key == "noaa-history" else inventory.get("rows")
        if not isinstance(inventory, dict) or not isinstance(rows, list):
            continue
        found = [(float(r["lat"]), float(r["lon"])) for r in rows
                 if isinstance(r, dict) and isinstance(r.get("lat"), (int, float)) and isinstance(r.get("lon"), (int, float))
                 and (r["lat"], r["lon"]) != (0, 0) and -90 <= r["lat"] <= 90 and -180 <= r["lon"] <= 180]
        if found:
            points += found
            sources.append(key)
    return points, sources


def centred_field(field: np.ndarray, grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """The field with rows from 90 S to 90 N and columns from 180 W, and the rows' latitudes."""
    step = grid["di"]
    if grid["dj"] != step or grid["la1"] != 90 or grid["lo1"] != 0 or round(360 / step) != grid["ni"]:
        raise ValueError("unexpected grid layout")
    shifted = np.roll(field, grid["ni"] // 2, axis=1)[::-1]
    lats = -90 + step * np.arange(grid["nj"])
    return shifted, lats


def ocean(water: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """Water cells connected to the seed through edge-sharing water cells (longitude wraps)."""
    reached = np.zeros_like(water)
    reached[seed] = water[seed]
    while True:
        before = int(reached.sum())
        # Fill whole water runs along each row that already touch a reached cell.
        for row in np.flatnonzero(reached.any(axis=1)):
            line = water[row]
            if line.all():
                reached[row] = True
                continue
            # Rotate so the row starts on land, then runs do not wrap.
            start = int(np.flatnonzero(~line)[0])
            w, r = np.roll(line, -start), np.roll(reached[row], -start)
            ids = np.cumsum(np.concatenate(([0], (w[1:] & ~w[:-1]).astype(np.int64))))
            hit = np.zeros(ids[-1] + 1, dtype=bool)
            hit[ids[r & w]] = True
            reached[row] = np.roll(w & hit[ids], start)
        grown = reached.copy()
        grown[1:] |= reached[:-1]
        grown[:-1] |= reached[1:]
        reached = grown & water
        if int(reached.sum()) == before:
            return reached


def near(land: np.ndarray, lats: np.ndarray, step: float, km: float) -> np.ndarray:
    """Cells whose centre is within ``km`` of a land cell's centre (generous at high latitude:
    the column reach uses the larger of the two rows' latitudes)."""
    rows, columns = land.shape
    reach = int(math.ceil(km / (EARTH_KM_PER_DEGREE * step)))
    out = np.zeros_like(land)
    for offset in range(-reach, reach + 1):
        dy = abs(offset) * step * EARTH_KM_PER_DEGREE
        if dy > km:
            continue
        for row in range(max(0, -offset), min(rows, rows - offset)):
            source = land[row]
            if not source.any():
                continue
            cos = min(math.cos(math.radians(lats[row])), math.cos(math.radians(lats[row + offset])))
            width = columns if cos <= 1e-9 else int(math.sqrt(km * km - dy * dy) / (EARTH_KM_PER_DEGREE * step * cos))
            if width * 2 + 1 >= columns:
                out[row + offset] = True
                continue
            padded = np.concatenate((source[-width:], source, source[:width])) if width else source
            total = np.concatenate(([0], np.cumsum(padded, dtype=np.int64)))
            out[row + offset] |= (total[2 * width + 1:] - total[:columns]) > 0
    return out


def classes(field: np.ndarray, lats: np.ndarray, step: float,
            stations: list[tuple[float, float]] = ()) -> tuple[np.ndarray, np.ndarray]:
    """(inside, edge) boolean grids; everything else is outside."""
    rows = field.shape[0]
    land_evidence = field > 0
    for lat, lon in stations:
        land_evidence[round((lat + 90) / step), round((lon + 180) / step) % field.shape[1]] = True
    lat = np.broadcast_to(lats[:, None], field.shape)
    land = field >= LAND
    seed = (int(round((OCEAN_SEED[0] + 90) / step)), int(round((OCEAN_SEED[1] + 180) / step)))
    if land[seed] or rows != len(lats):
        raise ValueError("the ocean seed is not water")
    sea = ocean(field < LAND, seed)
    far = sea & ~near(land_evidence, lats, step, SEA_KM)
    inside = land & (lat >= INNER[0] - 1e-9) & (lat <= INNER[1] + 1e-9)
    outside = (lat < OUTER[0] - 1e-9) | (lat > OUTER[1] + 1e-9) | far
    return inside, ~inside & ~outside


def runs_of(cells: np.ndarray) -> list[list[int]]:
    runs = []
    for row in np.flatnonzero(cells.any(axis=1)):
        edges = np.flatnonzero(np.diff(np.concatenate(([False], cells[row], [False])).astype(np.int8)))
        runs += [[int(row), int(first), int(last)] for first, last in zip(edges[::2], edges[1::2])]
    return runs


def place(inside: np.ndarray, edge: np.ndarray, lat: float, lon: float, step: float) -> str:
    row, column = round((lat + 90) / step), round((lon + 180) / step) % inside.shape[1]
    return "inside" if inside[row, column] else "edge" if edge[row, column] else "outside"


def build(grib: Path, footprints: Path, analysis: Path | None = None) -> Path:
    data = grib.read_bytes()
    field, grid = decode(data)
    step = grid["di"]
    field, lats = centred_field(field, grid)
    stations, station_sources = station_points(json.loads(analysis.read_text(encoding="utf-8"))) if analysis else ([], [])
    inside, edge = classes(field, lats, step, stations)
    checks = {**CHECKS, **{name: (*point, "edge") for name, point in ATOLLS.items()}} if stations else CHECKS
    for name, (lat, lon, expected) in checks.items():
        if (found := place(inside, edge, lat, lon, step)) != expected:
            raise ValueError(f"check failed at {name}: {found}, expected {expected}")
    mask = {"step_degrees": step, "cell_origin": "center", "runs": runs_of(inside), "edge_runs": runs_of(edge)}
    raw = json.dumps(mask, separators=(",", ":")).encode()
    folder = footprints / "pvgis" / "tmy-v5_3" / "domain"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mask.json").write_bytes(raw)
    manifest = {"schema_version": 1, "entries": [{
        "product_id": "pvgis-tmy-v5_3", "selector_kind": "documented_domain", "selector": "domain",
        "basis": (f"ERA5-Land land fraction >= {LAND} between {INNER[0]} and {INNER[1]} (inside); "
                  f"ocean-connected water > {SEA_KM:g} km from any land fraction, or beyond "
                  f"{OUTER[0]} / {OUTER[1]} (outside); edge_runs between"),
        "source_file_id": SOURCE_URL, "source_sha256": hashlib.sha256(data).hexdigest(),
        "evidence_id": "era5land-lsm-r1",
        "station_evidence": {"sources": station_sources, "points": len(stations),
                             "analysis_sha256": hashlib.sha256(analysis.read_bytes()).hexdigest() if analysis else None},
        "documentation": "JRC139355, PVGIS 5.3 Dataset Update (2024), Table 1 and sections 3.1-3.2",
        "checked_by": ["pvgis-london", "pvgis-ithaca", "pvgis-atlantic", "pvgis-northsea-r1",
                       "pvgis-svalbard", "pvgis-lake-victoria"],
        "built_at": datetime.now(timezone.utc).isoformat(), "native_crs": "EPSG:4326",
        "native_longitude_convention": "0_to_360", "grid_points": int(field.size),
        "inside_points": int(inside.sum()), "edge_points": int(edge.sum()),
        "step_degrees": step, "cell_origin": "center", "mask_path": "mask.json",
        "mask_sha256": hashlib.sha256(raw).hexdigest(), "stale": False, "gates": list(GATES)}]}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder / "manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grib", type=Path)
    parser.add_argument("footprints", type=Path)
    parser.add_argument("analysis", type=Path, nargs="?", help="research analysis.json with station positions")
    args = parser.parse_args()
    path = build(args.grib, args.footprints, args.analysis)
    entry = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
    print(json.dumps({"manifest": str(path), "inside_points": entry["inside_points"],
                      "edge_points": entry["edge_points"], "grid_points": entry["grid_points"],
                      "mask_bytes": (path.parent / "mask.json").stat().st_size}))


if __name__ == "__main__":
    main()
