"""Reviewed source-grid coverage masks, used to gate gridded products by place.

Owner decision 2026-10-12: the reviewed NSRDB GOES v4 coverage mask (the map layer, built
from the published ``tdy-2023`` file's grid sites) gates NSRDB GOES products. A point whose
mask cell and neighbouring cells hold no grid site is outside coverage; a point in an
occupied cell is inside, so the probed year and product lists apply there; a point next to
occupied cells is near the edge and stays unknown. The mask is a 0.25 degree summary of
grid sites, not a weather-completeness claim. Only masks whose checksum matches their
manifest are used.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Place = Literal["inside", "edge", "outside"]


def verified_nsrdb_masks(footprints_root: Path) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """(manifest entry, mask) for each current NSRDB mask whose checksum matches."""
    for manifest_path in sorted((Path(footprints_root) / "nsrdb").glob("*/*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in manifest.get("entries", []):
            if entry.get("stale") or entry.get("selector_kind") != "published_name":
                continue
            try:
                raw = (manifest_path.parent / entry.get("mask_path", "mask.json")).read_bytes()
            except OSError:
                continue
            if hashlib.sha256(raw).hexdigest() != entry.get("mask_sha256"):
                continue
            yield entry, json.loads(raw)


@dataclass(frozen=True)
class GridCoverage:
    step: float
    cells: frozenset[tuple[int, int]]
    sources: tuple[str, ...]          # "product/selector" of each mask used

    def where(self, lat: float, lon: float) -> Place:
        columns = round(360 / self.step)
        row = math.floor((lat + 90) / self.step)
        column = math.floor((lon + 180) / self.step) % columns
        if (row, column) in self.cells:
            return "inside"
        near = any((row + dr, (column + dc) % columns) in self.cells
                   for dr in (-1, 0, 1) for dc in (-1, 0, 1))
        return "edge" if near else "outside"


def nsrdb_coverage(footprints_root: Path) -> GridCoverage | None:
    """The union of the reviewed NSRDB masks sharing the first mask's step, or None."""
    step: float | None = None
    cells: set[tuple[int, int]] = set()
    sources = []
    for entry, mask in verified_nsrdb_masks(footprints_root):
        mask_step = float(entry.get("step_degrees") or mask.get("step_degrees") or 0)
        if mask_step <= 0:
            continue
        if step is not None and mask_step != step:
            continue
        step = mask_step
        cells.update((int(row), int(column)) for row, column in mask.get("cells", []))
        sources.append(f"{entry['product_id']}/{entry['selector']}")
    if step is None or not cells:
        return None
    return GridCoverage(step, frozenset(cells), tuple(sources))
