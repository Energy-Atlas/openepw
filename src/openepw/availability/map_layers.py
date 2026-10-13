"""Display layers for the browser map, built from the active Stage 1 catalog.

Every layer is documentary context. Station and site coordinates come from the
catalog's inventories; extents come from catalog footprints or reviewed
documentation. None of them asserts point eligibility, hourly completeness or
EPW fitness, and products without reviewed geometry stay unmapped.
"""

from __future__ import annotations

import re
from pathlib import Path

from .coverage import LEGACY_GATES, mask_runs, verified_masks
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


def onebuilding_station_name(url: str | None) -> str | None:
    """Station name from a OneBuilding file name, e.g. AUS_QLD_Coconut.Island.AP.941820_TMYx.zip."""
    # Station codes are WMO numbers or alphanumeric (A05735, USA109).
    match = re.search(r"/(?:[A-Z]{3}_)(?:[A-Z]{2,3}_)?([^/_]+?)\.(?:\d{5,6}|[A-Z]{1,3}\d{3,6})_[^/]+\.zip$",
                      url or "")
    return match.group(1).replace(".", " ") if match else None


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
    for entry, mask in verified_masks(footprints_root, "nsrdb"):
        step = float(entry.get("step_degrees") or mask.get("step_degrees") or 0)
        if step <= 0:
            continue
        masks[(entry["product_id"], entry["selector"])] = {
            "rects": merge_cell_rows(mask.get("cells", []), step),
            "cell_count": len(mask.get("cells", [])),
            "step": step,
            "source": {key: entry.get(key) for key in (
                "selector", "source_file_id", "source_version", "source_modified_at",
                "retrieved_at", "coordinate_count", "meta_sha256", "mask_sha256")},
            "gates": list(entry.get("gates") or LEGACY_GATES.get(str(entry["product_id"])) or ()),
        }
    return masks


PVGIS_DISPLAY_STEP = 0.5


def _pvgis_mask(footprints_root: Path) -> dict | None:
    """The PVGIS domain mask's inside cells, summarised to display cells (any inside point)."""
    for entry, mask in verified_masks(footprints_root, "pvgis"):
        step = float(entry.get("step_degrees") or mask.get("step_degrees") or 0)
        if step <= 0 or "pvgis:PVGIS TMY" not in (entry.get("gates") or ()):
            continue
        factor = PVGIS_DISPLAY_STEP / step
        cells = {(int(row // factor), column)
                 for row, first, last in mask_runs(mask)
                 for column in range(int(first // factor), int((last - 1) // factor) + 1)}
        return {"rects": merge_cell_rows([list(cell) for cell in cells], PVGIS_DISPLAY_STEP),
                "cell_count": len(cells),
                "source": {key: entry.get(key) for key in (
                    "selector", "basis", "source_file_id", "documentation", "checked_by",
                    "built_at", "mask_sha256")}}
    return None


# The satellite each reviewed NSRDB grid comes from, for the map legend.
NSRDB_GRIDS = {"nsrdb-GOES-tmy-v4-0-0": "GOES", "himawari7": "Himawari",
               "nsrdb-msg-v1-0-0-tmy": "Meteosat", "msg-iodc": "Meteosat IODC"}


class SitePoints:
    """The NOAA station and OneBuilding file points of the map, gathered entry by entry."""

    def __init__(self) -> None:
        self.noaa: list[list] = []
        self.onebuilding: list[list] = []
        self.missing = self.zero = self.onebuilding_missing = 0

    def add(self, provider: str, entry, site, native_product_id: str | None, site_id: str | None) -> None:
        get = site.get if isinstance(site, dict) else (lambda key: getattr(site, key))
        lat, lon = get("lat"), get("lon")
        if provider == "noaa" and isinstance(entry.scope, ActualScope):
            if lat is None or lon is None:
                self.missing += 1
            elif lat == 0 and lon == 0:
                self.zero += 1  # Placeholder origin coordinates are not a station location.
            elif years := _years_with_reports(entry.scope):
                self.noaa.append([lon, lat, site_id, _ranges(years), get("name")])
        elif provider == "onebuilding" and isinstance(entry.scope, TMYReferenceScope):
            if lat is None or lon is None:
                self.onebuilding_missing += 1
                return
            scope = entry.scope
            period = (f"{scope.start_year}-{scope.end_year}"
                      if scope.start_year and scope.end_year else None)
            self.onebuilding.append([lon, lat, scope.product_label, period, get("position_status"),
                                     onebuilding_station_name(native_product_id)])

    def result(self) -> dict:
        return {"noaa_points": self.noaa, "missing": self.missing, "zero": self.zero,
                "onebuilding_points": self.onebuilding, "onebuilding_missing": self.onebuilding_missing}


def site_points(products, sites, entries) -> dict:
    """The map points of catalog records held in memory."""
    by_product = {product.id: product for product in products if product.temporal_kind != "future_window"}
    by_site = {site.id: site for site in sites if site.product_id in by_product}
    points = SitePoints()
    for entry in entries:
        site, product = by_site.get(entry.site_id or ""), by_product.get(entry.product_id)
        if site is not None and product is not None:
            points.add(product.provider, entry, site, product.native_product_id, site.id)
    return points.result()


def catalog_map(index, footprints_root: Path) -> dict:
    """The map's layers. ``index`` is a ``CatalogIndex`` (or a catalog bundle, wrapped in one)."""
    if isinstance(index, CatalogBundle):
        from .catalog_index import CatalogIndex

        index = CatalogIndex(index)
    all_products, all_sites, all_entries, gathered = index.map_parts()
    products = {product.id: product for product in all_products
                if product.temporal_kind != "future_window"}  # Future-weather UI is suspended.
    evidence = {item.id: item for item in index.evidence}

    def dates(product_ids) -> list[str]:
        refs = {ref for pid in product_ids for ref in products[pid].evidence_ids if ref in evidence}
        return sorted({(evidence[ref].checked_at or evidence[ref].retrieved_at).date().isoformat()
                       for ref in refs})

    layers: list[dict] = []
    mapped: set[tuple[str, str]] = set()

    noaa_points, missing, zero = gathered["noaa_points"], gathered["missing"], gathered["zero"]
    onebuilding_points, onebuilding_missing = gathered["onebuilding_points"], gathered["onebuilding_missing"]
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

    # Each reviewed NSRDB grid is drawn once and marks the products it gates as mapped.
    for (source_product, selector), mask in sorted(_nsrdb_masks(footprints_root).items()):
        gated = {gate.split(":", 1)[1] for gate in mask["gates"]}
        mapped |= {(product.provider, product.dataset) for product in products.values()
                   if product.provider == "nsrdb" and product.dataset in gated}
        satellite = NSRDB_GRIDS.get(source_product, source_product)
        layers.append({
            "id": "nsrdb" if source_product == "nsrdb-GOES-tmy-v4-0-0" else f"nsrdb:{source_product}",
            "kind": "cells", "label": f"NSRDB {satellite} source grid",
            "evidence_dates": [str(mask["source"]["retrieved_at"])[:10]],
            "count": mask["cell_count"], "step": mask["step"], "rects": mask["rects"],
            "source": mask["source"],
            "caveat": f"NLR source-grid sites of the {selector} file summarized in {mask['step']}° "
                      "cells. NSRDB products from this grid are offered inside it and not outside "
                      "(owner decision); not weather completeness.",
        })

    pvgis = [pid for pid, product in products.items() if product.provider == "pvgis"]
    if pvgis:
        mapped |= {(products[pid].provider, products[pid].dataset) for pid in pvgis}
        probes = [[entry.probe_location.lon, entry.probe_location.lat] for entry in all_entries
                  if entry.product_id in pvgis and entry.probe_location is not None]
        domain = _pvgis_mask(footprints_root)
        if domain:
            layers.append({
                "id": "pvgis", "kind": "cells", "label": "PVGIS TMY domain (SARAH3 or ERA5)",
                "evidence_dates": dates(pvgis), "count": domain["cell_count"],
                "step": PVGIS_DISPLAY_STEP, "rects": domain["rects"], "source": domain["source"],
                "caveat": "Land between 60° S and 75° N from ECMWF's ERA5-Land land-sea mask, in "
                          f"{PVGIS_DISPLAY_STEP}° display cells; PVGIS TMY is offered inside it. "
                          "Coasts, lakes and small islands stay unknown; the open sea and polar "
                          "land are not served. Radiation is SARAH3 or ERA5 by location.",
            })
        else:
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
        box = footprints[0].footprint
        assert box is not None                       # filtered above
        west, south, east, north = box
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
