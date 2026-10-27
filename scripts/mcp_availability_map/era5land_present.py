"""ERA5-Land coverage mask from the points where ERA5-Land has values (2026-10-13 availability-gaps
plan, item 4, owner decision D5).

Reads one global ERA5-Land field saved from CDS (C1: ``2m_temperature``, 2020-01-01 00:00, GRIB
edition 1, a regular 0.1 degree grid with a bit map) without a GRIB library, and writes a mask in
the footprint format: the grid points with a value, as row runs indexed by cell centre. It
replaces the land-fraction mask (``era5land_mask.py``, land fraction >= 0.5) as the ERA5-Land gate,
so lakes and low-fraction coasts with values are inside. Offline; never fetches anything.

    python -m scripts.mcp_availability_map.era5land_present <grib> <footprints root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.mcp_availability_map.era5land_mask import CHECKS, GATES, _signed, land_runs

SOURCE = "CDS reanalysis-era5-land, 2m_temperature, 2020-01-01 00:00, GRIB (request C1)"
KELVIN = (180.0, 340.0)               # plausible 2 m temperatures, as a decoding check


def _ibm(raw: bytes) -> float:
    """An IBM System/360 single-precision float, as GRIB 1 stores its reference value."""
    sign = -1.0 if raw[0] & 0x80 else 1.0
    return sign * int.from_bytes(raw[1:4], "big") / 2 ** 24 * 16.0 ** ((raw[0] & 0x7F) - 64)


def decode_grib1(data: bytes) -> tuple[np.ndarray, np.ndarray, dict]:
    """(present, values, grid) of a single GRIB 1 message on a regular lat/lon grid with a bit
    map and simple packing; ``values`` is NaN where the bit map has no value."""
    if data[:4] != b"GRIB" or data[7] != 1 or data.count(b"GRIB") != 1:
        raise ValueError("expected one GRIB 1 message")
    total = int.from_bytes(data[4:7], "big")
    if data[total - 4:total] != b"7777":
        raise ValueError("incomplete GRIB message")
    pds = data[8:]
    position = 8 + int.from_bytes(pds[0:3], "big")
    if pds[7] & 0xC0 != 0xC0:
        raise ValueError("expected a grid description and a bit map")
    decimal = _signed(pds[26:28])
    gds = data[position:]
    if gds[5] != 0:
        raise ValueError("expected a regular latitude/longitude grid")
    grid = {"ni": int.from_bytes(gds[6:8], "big"), "nj": int.from_bytes(gds[8:10], "big"),
            "la1": _signed(gds[10:13]) / 1e3, "lo1": _signed(gds[13:16]) / 1e3,
            "la2": _signed(gds[17:20]) / 1e3, "lo2": _signed(gds[20:23]) / 1e3,
            "di": int.from_bytes(gds[23:25], "big") / 1e3, "dj": int.from_bytes(gds[25:27], "big") / 1e3,
            "scan": gds[27]}
    position += int.from_bytes(gds[0:3], "big")
    bms = data[position:]
    if int.from_bytes(bms[4:6], "big") != 0 or grid["scan"] != 0:
        raise ValueError("expected an explicit bit map and the default scan order")
    points = grid["ni"] * grid["nj"]
    present = np.unpackbits(np.frombuffer(bms[6:int.from_bytes(bms[0:3], "big")], dtype=np.uint8))[:points].astype(bool)
    position += int.from_bytes(bms[0:3], "big")
    bds = data[position:]
    if bds[3] >> 4 != 0 or bds[10] != 16:
        raise ValueError("expected simple packing of 16-bit grid-point values")
    scale, reference = _signed(bds[4:6]), _ibm(bds[6:10])
    count = int(present.sum())
    packed = np.frombuffer(bds[11:11 + 2 * count], dtype=">u2").astype(np.float64)
    if len(packed) != count:
        raise ValueError("fewer packed values than the bit map lists")
    values = np.full(points, np.nan)
    values[present] = (reference + packed * 2.0 ** scale) / 10 ** decimal
    return present.reshape(grid["nj"], grid["ni"]), values.reshape(grid["nj"], grid["ni"]), grid


def build(grib: Path, footprints: Path) -> Path:
    data = grib.read_bytes()
    present, values, grid = decode_grib1(data)
    found = values[present]
    if not (found.min() >= KELVIN[0] and found.max() <= KELVIN[1]):
        raise ValueError("2 m temperatures outside a plausible range")
    for name, (lat, lon, land) in CHECKS.items():
        j, i = round((90 - lat) / grid["dj"]), round((lon % 360) / grid["di"]) % grid["ni"]
        if bool(present[j, i]) != land:
            raise ValueError(f"decoding check failed at {name}")
    mask = {"step_degrees": grid["di"], "cell_origin": "center",
            "runs": land_runs(present.astype(np.float64), grid)}
    raw = json.dumps(mask, separators=(",", ":")).encode()
    folder = footprints / "cds" / "reanalysis-era5-land" / "present-t2m"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mask.json").write_bytes(raw)
    manifest = {"schema_version": 1, "entries": [{
        "product_id": "reanalysis-era5-land", "selector_kind": "values_present", "selector": "present-t2m",
        "basis": "grid points with a 2m_temperature value", "source_file_id": SOURCE,
        "source_sha256": hashlib.sha256(data).hexdigest(), "evidence_id": "c1-era5land-t2m-2020010100",
        "built_at": datetime.now(timezone.utc).isoformat(), "native_crs": "EPSG:4326",
        "native_longitude_convention": "0_to_360", "grid_points": int(present.size),
        "land_points": int(present.sum()), "step_degrees": grid["di"], "cell_origin": "center",
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
    print(json.dumps({"manifest": str(path), "points_with_values": entry["land_points"],
                      "grid_points": entry["grid_points"], "mask_bytes": (path.parent / "mask.json").stat().st_size}))


if __name__ == "__main__":
    main()
