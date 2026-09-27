"""Display layers for the browser map, built from the active Stage 1 catalog.

Every layer is documentary context. Station and site coordinates come from the
catalog's inventories; extents come from catalog footprints or reviewed
documentation. None of them asserts point eligibility, hourly completeness or
EPW fitness, and products without reviewed geometry stay unmapped.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import ActualScope, CatalogBundle, TMYReferenceScope

# Coarse lon/lat envelope traced against JRC's PVGIS 5.3 default irradiance-source
# figure (SARAH3 region); see docs/validation/mcp-stage-2/pvgis-map-evidence.md.
PVGIS_SARAH3_APPROX = [
    [-25, 63], [10, 63], [25, 63], [30, 60], [38, 55], [47, 48], [54, 40], [60, 30],
    [65, 20], [62, 10], [58, 0], [55, -15], [50, -30], [45, -36], [-57, -36], [-62, -28],
    [-65, -20], [-65, 20], [-55, 25], [-45, 40], [-35, 55],
]
PVGIS_SOURCE = ("https://joint-research-centre.ec.europa.eu/sites/default/files/2024-09/"
                "PVGIS_53_DB_Coverage.png")


def _years_with_reports(scope: ActualScope) -> list[int]:
    if not scope.month_counts:
        return sorted(scope.years)
    return sorted(year for year, months in scope.month_counts.items()
                  if any(count > 0 for count in months.values()))


def _ranges(years: list[int]) -> list[list[int]]:
    ranges: list[list[int]] = []
    for year in years:
        if ranges and year == ranges[-1][1] + 1:
            ranges[-1][1] = year
        else:
            ranges.append([year, year])
    return ranges


def _lon180(value: float, convention: str | None) -> float:
    return value - 360 if convention == "0_360" and value > 180 else value


def merge_cell_rows(cells: list[list[int]], step: float) -> list[list[float]]:
    """Join horizontally adjacent display cells into [west, south, east, north] boxes."""
    rects: list[list[float]] = []
    for row, column in sorted(map(tuple, cells)):
        south = -90 + row * step
        west = -180 + column * step
        last = rects[-1] if rects else None
        if last and last[1] == south and last[2] == west:
            last[2] = west + step
        else:
            rects.append([west, south, west + step, south + step])
    return rects


def _nsrdb_masks(footprints_root: Path) -> dict[tuple[str, str], dict]:
    """Load reviewed NSRDB source-grid masks; skip stale or checksum-mismatched ones."""
    masks: dict[tuple[str, str], dict] = {}
    for manifest_path in sorted((footprints_root / "nsrdb").glob("*/*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in manifest.get("entries", []):
            if entry.get("stale") or entry.get("selector_kind") != "published_name":
                continue
            mask_path = manifest_path.parent / entry.get("mask_path", "mask.json")
            try:
                raw = mask_path.read_bytes()
            except OSError:
                continue
            if hashlib.sha256(raw).hexdigest() != entry.get("mask_sha256"):
                continue
            mask = json.loads(raw)
            step = float(entry.get("step_degrees") or mask.get("step_degrees"))
            masks[(entry["product_id"], entry["selector"])] = {
                "rects": merge_cell_rows(mask.get("cells", []), step),
                "cell_count": len(mask.get("cells", [])),
                "step": step,
                "source": {key: entry.get(key) for key in (
                    "selector", "source_file_id", "source_version", "source_modified_at",
                    "retrieved_at", "coordinate_count", "meta_sha256", "mask_sha256")},
            }
    return masks


def catalog_map(bundle: CatalogBundle, footprints_root: Path) -> dict:
    products = {product.id: product for product in bundle.products
                if product.temporal_kind != "future_window"}  # Future-weather UI is suspended.
    evidence = {item.id: item for item in bundle.evidence}

    def dates(product_ids) -> list[str]:
        refs = {ref for pid in product_ids for ref in products[pid].evidence_ids if ref in evidence}
        return sorted({(evidence[ref].checked_at or evidence[ref].retrieved_at).date().isoformat()
                       for ref in refs})

    sites = {site.id: site for site in bundle.sites if site.product_id in products}
    layers: list[dict] = []
    mapped: set[tuple[str, str]] = set()

    noaa_points, missing, zero = [], 0, 0
    onebuilding_points, onebuilding_missing = [], 0
    for entry in bundle.entries:
        site = sites.get(entry.site_id or "")
        product = products.get(entry.product_id)
        if site is None or product is None:
            continue
        if product.provider == "noaa" and isinstance(entry.scope, ActualScope):
            if site.lat is None or site.lon is None:
                missing += 1
            elif site.lat == 0 and site.lon == 0:
                zero += 1  # Placeholder origin coordinates are not a station location.
            elif years := _years_with_reports(entry.scope):
                noaa_points.append([site.lon, site.lat, site.id, _ranges(years)])
        elif product.provider == "onebuilding" and isinstance(entry.scope, TMYReferenceScope):
            if site.lat is None or site.lon is None:
                onebuilding_missing += 1
                continue
            scope = entry.scope
            period = (f"{scope.start_year}-{scope.end_year}"
                      if scope.start_year and scope.end_year else None)
            onebuilding_points.append([site.lon, site.lat, scope.product_label, period,
                                       site.position_status])
    noaa_ids = [pid for pid, product in products.items() if product.provider == "noaa"]
    if noaa_points:
        mapped |= {(products[pid].provider, products[pid].dataset) for pid in noaa_ids}
        layers.append({
            "id": "noaa", "kind": "stations", "label": "NOAA ISD stations",
            "evidence_dates": dates(noaa_ids), "count": len(noaa_points),
            "omitted": {"no_coordinates": missing, "zero_origin": zero}, "points": noaa_points,
            "caveat": "Station coordinates with reports listed in the inventory for each year. "
                      "Report counts do not establish valid hours, variables or complete EPWs.",
        })
    onebuilding_ids = [pid for pid, product in products.items() if product.provider == "onebuilding"]
    if onebuilding_points:
        mapped |= {(products[pid].provider, products[pid].dataset) for pid in onebuilding_ids}
        layers.append({
            "id": "onebuilding", "kind": "sites", "label": "OneBuilding published EPWs",
            "evidence_dates": dates(onebuilding_ids), "count": len(onebuilding_points),
            "omitted": {"no_coordinates": onebuilding_missing}, "points": onebuilding_points,
            "caveat": "Published reference-period files at catalog coordinates; approximate "
                      "localities are rings. Metadata position, not EPW-header verification.",
        })

    masks = _nsrdb_masks(footprints_root)
    for pid, product in products.items():
        if product.provider != "nsrdb":
            continue
        found = [(selector, mask) for (dataset, selector), mask in masks.items()
                 if dataset == product.dataset]
        for selector, mask in found:
            mapped.add((product.provider, product.dataset))
            layers.append({
                "id": "nsrdb", "kind": "cells", "label": f"NSRDB {selector} source grid",
                "evidence_dates": [str(mask["source"]["retrieved_at"])[:10]],
                "count": mask["cell_count"], "step": mask["step"], "rects": mask["rects"],
                "source": mask["source"],
                "caveat": f"NLR source-grid sites summarized in {mask['step']}° cells for the "
                          f"published {selector} product. Not API eligibility, actual-year "
                          "coverage or weather completeness.",
            })

    pvgis = [pid for pid, product in products.items() if product.provider == "pvgis"]
    if pvgis:
        mapped |= {(products[pid].provider, products[pid].dataset) for pid in pvgis}
        probes = [[entry.probe_location.lon, entry.probe_location.lat] for entry in bundle.entries
                  if entry.product_id in pvgis and entry.probe_location is not None]
        layers.append({
            "id": "pvgis", "kind": "area", "label": "PVGIS TMY SARAH3 region",
            "evidence_dates": dates(pvgis), "count": len(probes),
            "polygon": [*PVGIS_SARAH3_APPROX, PVGIS_SARAH3_APPROX[0]], "probes": probes,
            "source_url": PVGIS_SOURCE,
            "caveat": "Approximate envelope traced from JRC's PVGIS 5.3 irradiance-source figure; "
                      "SARAH3 covers land only and the envelope is not clipped to coastlines. "
                      "Points are saved probes. Not TMY eligibility at arbitrary coordinates.",
        })

    for layer_id, land, label in (("era5", False, "ERA5 global reanalysis"),
                                  ("era5-land", True, "ERA5-Land reanalysis")):
        members = [pid for pid, product in products.items()
                   if product.spatial_kind == "grid" and product.provider in ("cds", "openmeteo")
                   and ("land" in product.dataset) == land]
        footprints = [products[pid] for pid in members if products[pid].footprint]
        if not footprints:
            continue  # Documentation-only members need a catalog footprint to be drawn.
        west, south, east, north = footprints[0].footprint
        convention = footprints[0].longitude_convention
        bounds = ([-180.0, float(south), 180.0, float(north)] if east - west >= 359.999
                  else [_lon180(west, convention), float(south), _lon180(east, convention), float(north)])
        mapped |= {(products[pid].provider, products[pid].dataset) for pid in members}
        layers.append({
            "id": layer_id, "kind": "extent", "label": label, "bounds": bounds,
            "members": sorted(f"{products[pid].provider}/{products[pid].dataset}" for pid in members),
            "evidence_dates": dates(members), "count": len(members),
            "caveat": ("Documented catalog extent; land grid cells only. " if land else
                       "Documented catalog extent. ") +
                      "Not a per-cell or per-hour completeness test.",
        })

    unmapped = sorted({(product.provider, product.dataset) for product in products.values()}
                      - mapped)
    return {
        "schema": "catalog-map-1",
        "layers": layers,
        "unmapped": [{"provider": provider, "dataset": dataset,
                      "reason": "No reviewed geometry in the active catalog."}
                     for provider, dataset in unmapped],
    }
