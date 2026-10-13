"""ERA5-Land coverage mask from ECMWF's published land-sea mask (2026-10-13 plan, E4).

Reads the saved GRIB 2 file (``era5land-lsm-r1`` in the research ledger: one field, a regular
0.1 degree grid, simple packing) without a GRIB library, and writes a coverage mask in the
service's footprint format: the grid points whose land fraction is at least 0.5, as row runs
indexed by cell centre. ERA5-Land masks the oceans; it has values over lakes and at some
coastal points with a smaller land fraction, so the coverage edge rule leaves those places
unknown rather than excluded. Offline; never fetches anything.

    python -m scripts.mcp_availability_map.era5land_mask <grib> <footprints root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SOURCE_URL = "https://confluence.ecmwf.int/download/attachments/140385202/lsm_1279l4_0.1x0.1.grb"
THRESHOLD = 0.5
GATES = ("cds:reanalysis-era5-land", "openmeteo:era5_land")
# Points that must decode as land or water, as a check of the decoding.
CHECKS = {"Ithaca": (42.44, -76.5, True), "Singapore": (1.35, 103.82, True), "London": (51.507, -0.128, True),
          "Nairobi": (-1.286, 36.817, True), "Mid-Pacific": (0.0, -150.0, False), "South Atlantic": (-30.0, -15.0, False)}


def _signed(raw: bytes) -> int:
    value = int.from_bytes(raw, "big")
    top = 1 << (8 * len(raw) - 1)
    return -(value & (top - 1)) if value & top else value


def decode(data: bytes) -> tuple[np.ndarray, dict]:
    """The single field of a GRIB 2 message on a regular lat/lon grid with simple packing."""
    if data[:4] != b"GRIB" or data[7] != 2 or data.count(b"GRIB") != 1:
        raise ValueError("expected one GRIB 2 message")
    total = int.from_bytes(data[8:16], "big")
    position, grid, packing, values = 16, None, None, None
    while position < total - 4:
        length, number = int.from_bytes(data[position:position + 4], "big"), data[position + 4]
        section = data[position:position + length]
        if number == 3:
            if int.from_bytes(section[12:14], "big") != 0:
                raise ValueError("expected a regular latitude/longitude grid")
            grid = {"ni": int.from_bytes(section[30:34], "big"), "nj": int.from_bytes(section[34:38], "big"),
                    "la1": _signed(section[46:50]) / 1e6, "lo1": _signed(section[50:54]) / 1e6,
                    "la2": _signed(section[55:59]) / 1e6, "lo2": _signed(section[59:63]) / 1e6,
                    "di": int.from_bytes(section[63:67], "big") / 1e6, "dj": int.from_bytes(section[67:71], "big") / 1e6,
                    "scan": section[71]}
        elif number == 5:
            if int.from_bytes(section[9:11], "big") != 0:
                raise ValueError("expected simple packing")
            packing = {"points": int.from_bytes(section[5:9], "big"), "R": struct.unpack(">f", section[11:15])[0],
                       "E": _signed(section[15:17]), "D": _signed(section[17:19]), "bits": section[19]}
        elif number == 6 and section[5] != 255:
            raise ValueError("bit-mapped fields are not supported")
        elif number == 7:
            values = section[5:]
        position += length
    if grid is None or packing is None or values is None or data[position:position + 4] != b"7777":
        raise ValueError("incomplete GRIB message")
    if packing["bits"] != 24 or packing["points"] != grid["ni"] * grid["nj"] or grid["scan"] != 0:
        raise ValueError("unexpected packing or scan order")
    raw = np.frombuffer(values[:packing["points"] * 3], dtype=np.uint8).reshape(-1, 3).astype(np.uint32)
    packed = (raw[:, 0] << 16) | (raw[:, 1] << 8) | raw[:, 2]
    field = (packing["R"] + packed * 2.0 ** packing["E"]) / 10 ** packing["D"]
    return field.reshape(grid["nj"], grid["ni"]), grid


def land_runs(field: np.ndarray, grid: dict) -> list[list[int]]:
    """[row, first column, last column + 1] of land points, rows and columns indexed by cell
    centre from (-90, -180) at the grid step."""
    step = grid["di"]
    if grid["dj"] != step or grid["la1"] != 90 or grid["lo1"] != 0 or round(360 / step) != grid["ni"]:
        raise ValueError("unexpected grid layout")
    shift = grid["ni"] // 2                                  # longitude 0 is column 1800 from -180
    runs = []
    for j in range(grid["nj"]):
        row = round((90 - j * step + 90) / step)
        land = np.roll(field[j] >= THRESHOLD, shift)
        edges = np.flatnonzero(np.diff(np.concatenate(([False], land, [False])).astype(np.int8)))
        runs += [[row, int(first), int(last)] for first, last in zip(edges[::2], edges[1::2])]
    return runs


def build(grib: Path, footprints: Path) -> Path:
    data = grib.read_bytes()
    field, grid = decode(data)
    if not (np.isfinite(field).all() and field.min() >= -1e-6 and field.max() <= 1 + 1e-6):
        raise ValueError("land fraction outside 0..1")
    for name, (lat, lon, land) in CHECKS.items():
        j, i = round((90 - lat) / grid["dj"]), round((lon % 360) / grid["di"]) % grid["ni"]
        if (field[j, i] >= THRESHOLD) != land:
            raise ValueError(f"decoding check failed at {name}")
    mask = {"step_degrees": grid["di"], "cell_origin": "center", "runs": land_runs(field, grid)}
    raw = json.dumps(mask, separators=(",", ":")).encode()
    folder = footprints / "cds" / "reanalysis-era5-land" / "lsm"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mask.json").write_bytes(raw)
    manifest = {"schema_version": 1, "entries": [{
        "product_id": "reanalysis-era5-land", "selector_kind": "land_sea_mask", "selector": "lsm",
        "basis": f"land_fraction_at_least_{THRESHOLD}", "source_file_id": SOURCE_URL,
        "source_sha256": hashlib.sha256(data).hexdigest(), "evidence_id": "era5land-lsm-r1",
        "built_at": datetime.now(timezone.utc).isoformat(), "native_crs": "EPSG:4326",
        "native_longitude_convention": "0_to_360", "grid_points": int(field.size),
        "land_points": int((field >= THRESHOLD).sum()), "step_degrees": grid["di"], "cell_origin": "center",
        "mask_path": "mask.json", "mask_sha256": hashlib.sha256(raw).hexdigest(), "stale": False,
        "gates": list(GATES)}]}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder / "manifest.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("grib", type=Path)
    parser.add_argument("footprints", type=Path)
    args = parser.parse_args()
    path = build(args.grib, args.footprints)
    entry = json.loads(path.read_text(encoding="utf-8"))["entries"][0]
    print(json.dumps({"manifest": str(path), "land_points": entry["land_points"],
                      "grid_points": entry["grid_points"], "mask_bytes": (path.parent / "mask.json").stat().st_size}))


if __name__ == "__main__":
    main()
