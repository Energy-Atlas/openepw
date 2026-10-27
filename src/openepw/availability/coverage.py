"""Reviewed source coverage masks, used to gate gridded products by place.

A mask lives at ``footprints/<provider>/<source product>/<selector>/`` as ``mask.json`` with a
``manifest.json`` that pins its SHA-256; only masks whose checksum matches are used. A mask
holds occupied grid cells (``cells``: ``[row, column]``) or row runs (``runs``:
``[row, first column, last column + 1]``) at ``step_degrees``; cells are counted from
(-90, -180), by their lower-left corner (``cell_origin: "corner"``, the default) or their
centre (``"center"``, for grids defined by their points, such as ERA5-Land).

Each manifest entry names the catalog products it gates (``gates``: ``"provider:dataset"``).
At a point a gated product is *inside* (the point's cell is occupied), *near the edge* (a
neighbouring cell is occupied) or *outside* (neither). A mask may instead list its unknown band
explicitly (``edge_runs``, same form as ``runs``): then a point is near the edge only in that
band, and outside elsewhere (PVGIS, 2026-10-13 gaps plan D2). A mask with an edge band may also
carry ``refine`` (``step_degrees``, ``cell_origin``, ``runs``): finer cells of the band that count
as inside (PVGIS's coastal points on Natural Earth land, 2026-10-27 follow-ups, item 6d). Owner decisions: the NSRDB GOES
``tdy-2023`` mask gates GOES actual-year and typical-year products (2026-10-12; its manifest
predates ``gates``); each further product gets its own mask (2026-10-13).
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Place = Literal["inside", "edge", "outside"]

# Manifests published before ``gates`` existed.
LEGACY_GATES = {
    "nsrdb-GOES-tmy-v4-0-0": ("nsrdb:nsrdb-GOES-tmy-v4-0-0", "nsrdb:nsrdb-GOES-aggregated-v4-0-0"),
}


def verified_masks(footprints_root: Path, provider: str = "*") -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """(manifest entry, mask) for each current mask whose checksum matches its manifest."""
    for manifest_path in sorted(Path(footprints_root).glob(f"{provider}/*/*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in manifest.get("entries", []):
            if entry.get("stale"):
                continue
            try:
                raw = (manifest_path.parent / entry.get("mask_path", "mask.json")).read_bytes()
            except OSError:
                continue
            if hashlib.sha256(raw).hexdigest() != entry.get("mask_sha256"):
                continue
            yield entry, json.loads(raw)


def verified_nsrdb_masks(footprints_root: Path) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    """The NSRDB published-file masks drawn on the map."""
    for entry, mask in verified_masks(footprints_root, "nsrdb"):
        if entry.get("selector_kind") == "published_name":
            yield entry, mask


def mask_runs(mask: dict[str, Any], key: str = "runs") -> list[tuple[int, int, int]]:
    """A mask's occupied cells (or, with ``key="edge_runs"``, its explicit edge band) as sorted,
    merged row runs."""
    runs = [(int(row), int(first), int(last)) for row, first, last in mask.get(key, [])]
    if key == "runs":
        runs += [(int(row), int(column), int(column) + 1) for row, column in mask.get("cells", [])]
    merged: list[tuple[int, int, int]] = []
    for row, first, last in sorted(runs):
        if merged and merged[-1][0] == row and first <= merged[-1][2]:
            merged[-1] = (row, merged[-1][1], max(merged[-1][2], last))
        else:
            merged.append((row, first, last))
    return merged


@dataclass(frozen=True)
class GridCoverage:
    step: float
    runs: dict[int, tuple[tuple[int, int], ...]]       # row -> sorted (first, last + 1) columns
    sources: tuple[str, ...]                           # "product/selector" of each mask used
    centred: bool = False
    _starts: dict[int, list[int]] = field(default_factory=dict, compare=False, repr=False)
    edges: dict[int, tuple[tuple[int, int], ...]] | None = None   # explicit edge band, if any
    _edge_starts: dict[int, list[int]] = field(default_factory=dict, compare=False, repr=False)
    refine: GridCoverage | None = None                 # finer inside cells within the edge band

    @staticmethod
    def _rows(runs: Iterable[tuple[int, int, int]]) -> dict[int, tuple[tuple[int, int], ...]]:
        rows: dict[int, list[tuple[int, int]]] = {}
        for row, first, last in mask_runs({"runs": list(runs)}):
            rows.setdefault(row, []).append((first, last))
        return {row: tuple(spans) for row, spans in rows.items()}

    @classmethod
    def from_runs(cls, step: float, runs: Iterable[tuple[int, int, int]], sources: tuple[str, ...],
                  centred: bool = False,
                  edge_runs: Iterable[tuple[int, int, int]] | None = None,
                  refine: GridCoverage | None = None) -> GridCoverage:
        frozen = cls._rows(runs)
        edges = cls._rows(edge_runs) if edge_runs is not None else None
        return cls(step, frozen, sources, centred, {row: [first for first, _ in spans] for row, spans in frozen.items()},
                   edges, {row: [first for first, _ in spans] for row, spans in (edges or {}).items()}, refine)

    @classmethod
    def from_cells(cls, step: float, cells: Iterable[tuple[int, int]], sources: tuple[str, ...] = ()) -> GridCoverage:
        return cls.from_runs(step, ((row, column, column + 1) for row, column in cells), sources)

    def _occupied(self, row: int, column: int, edge: bool = False) -> bool:
        spans = (self.edges or {}).get(row) if edge else self.runs.get(row)
        if not spans:
            return False
        starts = self._edge_starts[row] if edge else self._starts[row]
        index = bisect.bisect_right(starts, column) - 1
        return index >= 0 and column < spans[index][1]

    def where(self, lat: float, lon: float) -> Place:
        index = round if self.centred else math.floor
        columns = round(360 / self.step)
        row = int(index((lat + 90) / self.step))
        column = int(index((lon + 180) / self.step)) % columns
        if self._occupied(row, column):
            return "inside"
        if self.edges is not None:
            if not self._occupied(row, column, edge=True):
                return "outside"
            return "inside" if self.refine and self.refine.where(lat, lon) == "inside" else "edge"
        near = any(self._occupied(row + dr, (column + dc) % columns)
                   for dr in (-1, 0, 1) for dc in (-1, 0, 1))
        return "edge" if near else "outside"


def load_coverage(footprints_root: Path) -> dict[str, GridCoverage]:
    """One coverage per gated catalog product (``"provider:dataset"``)."""
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for entry, mask in verified_masks(footprints_root):
        gates: Iterable[str] = entry.get("gates") or LEGACY_GATES.get(str(entry.get("product_id"))) or ()
        for gate in gates:
            grouped.setdefault(gate, []).append((entry, mask))
    coverage = {}
    for gate, masks in grouped.items():
        step = float(masks[0][0].get("step_degrees") or masks[0][1].get("step_degrees") or 0)
        centred = (masks[0][0].get("cell_origin") or masks[0][1].get("cell_origin")) == "center"
        if step <= 0:
            continue
        runs: list[tuple[int, int, int]] = []
        edge_runs: list[tuple[int, int, int]] = []
        fine: list[tuple[int, int, int]] = []
        fine_step = 0.0
        explicit = True                                   # every mask lists its edge band
        sources = []
        for entry, mask in masks:
            if float(entry.get("step_degrees") or mask.get("step_degrees") or 0) != step:
                continue                                  # masks for one product share one grid
            runs += mask_runs(mask)
            explicit = explicit and "edge_runs" in mask
            edge_runs += mask_runs(mask, "edge_runs")
            layer = mask.get("refine") or {}
            layer_step = float(layer.get("step_degrees") or 0)
            if (layer.get("runs") and layer_step > 0 and layer.get("cell_origin", "corner") == "corner"
                    and fine_step in (0.0, layer_step)):
                fine_step = layer_step
                fine += mask_runs(layer)
            sources.append(f"{entry.get('product_id')}/{entry.get('selector')}")
        if runs:
            refine = GridCoverage.from_runs(fine_step, fine, tuple(sources)) if fine and explicit else None
            coverage[gate] = GridCoverage.from_runs(step, runs, tuple(sources), centred,
                                                    edge_runs if explicit else None, refine)
    return coverage


def nsrdb_coverage(footprints_root: Path) -> GridCoverage | None:
    """The GOES coverage map (kept for callers of the first version)."""
    return load_coverage(footprints_root).get("nsrdb:nsrdb-GOES-tmy-v4-0-0")
