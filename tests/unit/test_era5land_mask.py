"""The ERA5-Land coverage mask decoder (research script, offline)."""

import json
import struct

import numpy as np

from openepw.availability.coverage import load_coverage
from scripts.mcp_availability_map.era5land_mask import decode, land_runs


def _grib(field: np.ndarray, step: float = 90.0) -> bytes:
    """A GRIB 2 message with one field on a regular grid, simple packing, 24-bit."""
    nj, ni = field.shape
    def section(number, body):
        return (len(body) + 5).to_bytes(4, "big") + bytes([number]) + body
    grid = bytearray(67)
    grid[7:9] = (0).to_bytes(2, "big")                          # template 3.0, at section byte 12
    grid[1:5] = (ni * nj).to_bytes(4, "big")
    grid[25:29], grid[29:33] = ni.to_bytes(4, "big"), nj.to_bytes(4, "big")
    grid[41:45], grid[45:49] = int(90e6).to_bytes(4, "big"), (0).to_bytes(4, "big")
    grid[50:54] = (int(90e6) | 0x80000000).to_bytes(4, "big")
    grid[54:58] = int((360 - step) * 1e6).to_bytes(4, "big")
    grid[58:62], grid[62:66] = int(step * 1e6).to_bytes(4, "big"), int(step * 1e6).to_bytes(4, "big")
    grid[66] = 0
    exponent = -23
    packed = np.round(field.ravel() / 2.0 ** exponent).astype(np.uint32)
    values = b"".join(int(value).to_bytes(3, "big") for value in packed)
    packing = (ni * nj).to_bytes(4, "big") + (0).to_bytes(2, "big") + struct.pack(">f", 0.0) \
        + (0x8000 | -exponent).to_bytes(2, "big") + (0).to_bytes(2, "big") + bytes([24, 0])
    body = section(1, bytes(16)) + section(3, bytes(grid)) + section(4, bytes(29)) \
        + section(5, packing) + section(6, bytes([255])) + section(7, values)
    total = 16 + len(body) + 4
    return b"GRIB" + bytes(3) + bytes([2]) + total.to_bytes(8, "big") + body + b"7777"


def test_the_land_fraction_decodes_and_becomes_centred_row_runs(tmp_path):
    # 3 rows (90 N, 0, 90 S) x 4 columns (0, 90 E, 180, 90 W); land at 0 N for 0 and 90 E.
    field = np.zeros((3, 4))
    field[1, 0], field[1, 1], field[1, 3] = 1.0, 0.75, 0.25
    decoded, grid = decode(_grib(field))
    assert np.allclose(decoded, field, atol=1e-6) and (grid["ni"], grid["nj"]) == (4, 3)
    runs = land_runs(decoded, grid)
    assert runs == [[1, 2, 4]]                       # row of 0 N; columns of 0 and 90 E from -180
    folder = tmp_path / "cds" / "reanalysis-era5-land" / "lsm"
    folder.mkdir(parents=True)
    raw = json.dumps({"step_degrees": 90.0, "cell_origin": "center", "runs": runs}).encode()
    (folder / "mask.json").write_bytes(raw)
    import hashlib
    entry = {"product_id": "reanalysis-era5-land", "selector": "lsm", "mask_path": "mask.json",
             "mask_sha256": hashlib.sha256(raw).hexdigest(), "step_degrees": 90.0, "cell_origin": "center",
             "gates": ["cds:reanalysis-era5-land", "openmeteo:era5_land"]}
    (folder / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    land = load_coverage(tmp_path)["openmeteo:era5_land"]
    assert land.where(10, 20) == "inside" and land.where(10, 80) == "inside"
    assert land.where(80, 20) == "edge"                  # at 90 degrees every cell neighbours land
