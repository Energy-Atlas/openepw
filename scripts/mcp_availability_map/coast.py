"""Natural Earth land polygons on a fine grid, for coastal points of a coverage mask's edge band.

Availability follow-ups 2026-10-27 (item 6d, owner decision Q8). The 0.1 degree PVGIS mask leaves
coastal cells that are mostly water by ERA5-Land in its unknown band, although many of their points
are on land. Natural Earth's 1:10m land polygons (public domain) decide land per fine cell of
``FINE`` degrees; a fine cell counts as land only when it and its eight neighbours are land, about
one fine cell (1.4 km) inland, which absorbs small differences from PVGIS's own coastline. Sea
points stay unknown. Offline; reads the saved ``ne_10m_land.zip`` only.
"""

from __future__ import annotations

import io
import struct
import zipfile

import numpy as np

FINE = 0.0125                    # degrees; 8 fine cells per 0.1 degree cell, edges aligned with it
SHAPEFILE = "ne_10m_land.shp"


def polygon_edges(archive: bytes) -> np.ndarray:
    """Every ring edge of the shapefile's polygons as rows (lon0, lat0, lon1, lat1)."""
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        shp = zipped.read(SHAPEFILE)
    if struct.unpack(">i", shp[:4])[0] != 9994 or struct.unpack("<i", shp[32:36])[0] != 5:
        raise ValueError("not a polygon shapefile")
    edges = []
    offset = 100
    while offset < len(shp):
        length = struct.unpack(">i", shp[offset + 4:offset + 8])[0] * 2
        record = shp[offset + 8:offset + 8 + length]
        offset += 8 + length
        if struct.unpack("<i", record[:4])[0] != 5:
            continue                                     # null shapes
        parts, points = struct.unpack("<ii", record[36:44])
        starts = list(struct.unpack(f"<{parts}i", record[44:44 + 4 * parts])) + [points]
        xy = np.frombuffer(record, "<f8", count=2 * points, offset=44 + 4 * parts).reshape(points, 2)
        for first, last in zip(starts[:-1], starts[1:]):
            ring = xy[first:last]
            edges.append(np.hstack((ring[:-1], ring[1:])))
    return np.vstack(edges)


def land_rows(edges: np.ndarray, rows: range, step: float = FINE) -> np.ndarray:
    """Land (even-odd rule at each fine cell's centre) for the given fine rows, counted from 90 S."""
    columns = round(360 / step)
    centres_x = -180 + (np.arange(columns) + 0.5) * step
    y0, y1 = edges[:, 1], edges[:, 3]
    low, high = np.minimum(y0, y1), np.maximum(y0, y1)
    order = np.argsort(low)
    edges, low, high = edges[order], low[order], high[order]
    out = np.zeros((len(rows), columns), dtype=bool)
    for index, row in enumerate(rows):
        y = -90 + (row + 0.5) * step
        candidates = slice(0, int(np.searchsorted(low, y, side="right")))
        crossing = edges[candidates][(high[candidates] > y)]
        if not len(crossing):
            continue
        ax, ay, bx, by = crossing.T
        xs = np.sort(ax + (y - ay) * (bx - ax) / (by - ay))
        out[index] = np.searchsorted(xs, centres_x) % 2 == 1
    return out


def inland(land: np.ndarray) -> np.ndarray:
    """Cells that are land with all eight neighbours land (longitude wraps; outer rows are not)."""
    core = land.copy()
    core[0] = core[-1] = False
    for dr in (-1, 0, 1):
        shifted = np.roll(land, dr, axis=0)
        for dc in (-1, 0, 1):
            core &= np.roll(shifted, dc, axis=1)
    return core
