"""Offline NSRDB spatial evidence for a local research map.

Display occupancy is a summary of source grid coordinates, not a weather or API
eligibility assertion. The production availability service is deliberately separate.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

AGGREGATE_ID = "nsrdb-GOES-aggregated-v4-0-0"
TMY_ID = "nsrdb-GOES-tmy-v4-0-0"
REVIEWED_SOURCE = (TMY_ID, "published_name", "tdy-2023")
REVIEWED_OBJECT_KEY = "GOES/tmy/v4.0.0/nsrdb_tdy-2023.h5"
REVIEWED_MODEL_VERSION = "4.0.1"


@dataclass(frozen=True)
class CoverageEntry:
    product_id: str
    source_file_id: str
    source_version: str
    selector_kind: str
    selector: str
    basis: str
    retrieved_at: str
    source_modified_at: str
    object_etag: str
    object_size: int
    meta_sha256: str
    mask_sha256: str
    coordinate_count: int
    native_crs: str
    native_longitude_convention: str
    step_degrees: float
    cells: frozenset[tuple[int, int]]
    stale: bool


@dataclass(frozen=True)
class CoverageManifest:
    entries: tuple[CoverageEntry, ...]


@dataclass(frozen=True)
class CoverageView:
    product_id: str
    selector_kind: str
    selectors: tuple[str, ...]
    confirmed_all: frozenset[tuple[int, int]]
    confirmed_some: frozenset[tuple[int, int]]
    unknown: bool
    reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    step_degrees: float | None


def occupied_cells(
    coordinates: list[tuple[float, float]], step_degrees: float
) -> frozenset[tuple[int, int]]:
    """Map coordinate centers to an occupancy grid without filling any gaps."""
    if not math.isfinite(step_degrees) or step_degrees <= 0 or 180 / step_degrees % 1:
        raise ValueError("invalid display resolution")
    cells = set()
    for latitude, longitude in coordinates:
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            raise ValueError("non-finite coordinate")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("coordinate out of range")
        wrapped = -180 if longitude == 180 else longitude
        row = min(int(math.floor((latitude + 90) / step_degrees)), int(180 / step_degrees) - 1)
        column = int(math.floor((wrapped + 180) / step_degrees))
        cells.add((row, column))
    return frozenset(cells)


def load_coverage_manifest(path: Path) -> CoverageManifest:
    """Read locally generated masks with strict checksums and selector tags."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1 or not isinstance(document.get("entries"), list):
        raise ValueError("unsupported coverage manifest schema")
    result = []
    identities = set()
    for row in document["entries"]:
        mask_path = row.get("mask_path")
        if not isinstance(mask_path, str) or not mask_path or Path(mask_path).name != mask_path:
            raise ValueError("invalid mask path")
        raw = (path.parent / mask_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row.get("mask_sha256"):
            raise ValueError("mask checksum mismatch")
        mask = json.loads(raw)
        step = mask.get("step_degrees")
        if not isinstance(step, (int, float)) or step <= 0 or 180 / step % 1:
            raise ValueError("invalid display resolution")
        cells = mask.get("cells")
        if not isinstance(cells, list) or any(
            not isinstance(cell, list)
            or len(cell) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) for value in cell)
            or not (0 <= cell[0] < int(180 / step))
            or not (0 <= cell[1] < int(360 / step))
            for cell in cells
        ):
            raise ValueError("invalid mask cells")
        product = row.get("product_id")
        kind = row.get("selector_kind")
        selector = row.get("selector")
        if (product, kind, selector) != REVIEWED_SOURCE:
            raise ValueError("unreviewed product selector")
        if (row.get("source_file_id") != REVIEWED_OBJECT_KEY
                or row.get("source_version") != REVIEWED_MODEL_VERSION):
            raise ValueError("source object disagrees with reviewed selector")
        if not isinstance(row.get("object_etag"), str) or not row["object_etag"]:
            raise ValueError("missing source ETag")
        if not isinstance(row.get("object_size"), int) or row["object_size"] <= 0:
            raise ValueError("invalid source object size")
        identity = (product, kind, selector)
        if identity in identities:
            raise ValueError("duplicate product selector")
        identities.add(identity)
        if row.get("basis") != "source_grid_sites" or row.get("native_crs") != "EPSG:4326":
            raise ValueError("unsupported grid evidence")
        for field in ("meta_sha256", "mask_sha256"):
            if not isinstance(row.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", row[field]):
                raise ValueError("invalid checksum")
        result.append(
            CoverageEntry(
                product_id=product,
                source_file_id=row["source_file_id"],
                source_version=row["source_version"],
                selector_kind=kind,
                selector=selector,
                basis=row["basis"],
                retrieved_at=row["retrieved_at"],
                source_modified_at=row["source_modified_at"],
                object_etag=row["object_etag"],
                object_size=row["object_size"],
                meta_sha256=row["meta_sha256"],
                mask_sha256=row["mask_sha256"],
                coordinate_count=row["coordinate_count"],
                native_crs=row["native_crs"],
                native_longitude_convention=row["native_longitude_convention"],
                step_degrees=float(step),
                cells=frozenset(tuple(cell) for cell in cells),
                stale=bool(row.get("stale", False)),
            )
        )
    return CoverageManifest(tuple(result))


def classify_coverage(
    product_id: str, selectors: tuple[str, ...], manifest: CoverageManifest | None
) -> CoverageView:
    """Separate common occupancy, partial occupancy and missing evidence."""
    kind = "actual_year" if product_id == AGGREGATE_ID else "published_name"
    if product_id not in (AGGREGATE_ID, TMY_ID) or not selectors:
        return CoverageView(product_id, kind, selectors, frozenset(), frozenset(), True,
                            ("unsupported_product_or_selector",), (), None)
    lookup = {
        (entry.product_id, entry.selector_kind, entry.selector): entry
        for entry in manifest.entries
    } if manifest else {}
    seen = []
    reasons = []
    for selector in selectors:
        entry = lookup.get((product_id, kind, selector))
        if entry is None:
            reasons.append(f"missing_selector:{selector}")
        elif entry.stale:
            reasons.append(f"stale_selector:{selector}")
        else:
            seen.append(entry)
    steps = {entry.step_degrees for entry in seen}
    if len(steps) > 1:
        return CoverageView(product_id, kind, selectors, frozenset(), frozenset(), True,
                            ("incompatible_display_resolutions",), (), None)
    union = set().union(*(entry.cells for entry in seen)) if seen else set()
    all_cells = set.intersection(*(set(entry.cells) for entry in seen)) if seen and not reasons else set()
    some = union - all_cells
    return CoverageView(
        product_id=product_id,
        selector_kind=kind,
        selectors=selectors,
        confirmed_all=frozenset(all_cells),
        confirmed_some=frozenset(some),
        unknown=bool(reasons),
        reasons=tuple(reasons),
        evidence_ids=tuple(entry.meta_sha256 for entry in seen),
        step_degrees=next(iter(steps)) if steps else None,
    )


def load_point_catalogs(snapshot_root: Path) -> dict[str, dict[str, list[str]]]:
    """Read the two accepted point probes after verifying their ledger pins."""
    ledger = json.loads((snapshot_root / "ledger.json").read_text(encoding="utf-8"))
    records = {row["id"]: row for row in ledger["records"]}
    result = {}
    for ident in ("nsrdb-ithaca", "nsrdb-phoenix"):
        row = records[ident]
        relative = Path(row["snapshot"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid raw path")
        raw = (snapshot_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("raw checksum mismatch")
        document = json.loads(raw)
        result[ident] = {
            product["name"]: [str(name) for name in product.get("availableYears", [])]
            for product in document["outputs"]
            if product.get("name") in (AGGREGATE_ID, TMY_ID)
        }
    return result
