"""Build the local multi-product availability map from accepted snapshots."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

from .nsrdb_coverage import AGGREGATE_ID, TMY_ID, load_coverage_manifest, load_point_catalogs


def _coordinate(value: float) -> int:
    return round(float(value) * 1000)


def _year_bits(years: dict[str, list[int]]) -> str:
    value = 0
    for label, months in years.items():
        year = int(label)
        if 1930 <= year <= 2025 and any(month > 0 for month in months):
            value |= 1 << (year - 1930)
    return base64.b64encode(value.to_bytes(12, "little")).decode("ascii")


def _verify_ledger(snapshot_root: Path) -> dict[str, dict[str, object]]:
    ledger = json.loads((snapshot_root / "ledger.json").read_text(encoding="utf-8"))
    records = {}
    for row in ledger["records"]:
        records[row["id"]] = row
        if not row.get("snapshot"):
            continue
        relative = Path(row["snapshot"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("invalid raw path")
        raw = (snapshot_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("raw checksum mismatch")
    return records


def _points(snapshot_root: Path, records: dict[str, dict[str, object]]) -> list[list[object]]:
    catalogs = load_point_catalogs(snapshot_root)
    result = []
    for ident, label in (("nsrdb-ithaca", "Ithaca"), ("nsrdb-phoenix", "Phoenix")):
        row = records[ident]
        document = json.loads((snapshot_root / str(row["snapshot"])).read_text(encoding="utf-8"))
        wkt = document["inputs"]["query"]["wkt"]
        match = re.fullmatch(r"POINT\((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\)", wkt)
        if not match:
            raise ValueError("unsupported point coordinate")
        longitude, latitude = map(float, match.groups())
        result.append([
            label, _coordinate(latitude), _coordinate(longitude),
            catalogs[ident].get(AGGREGATE_ID, []), catalogs[ident].get(TMY_ID, []),
        ])
    return result


def _masks(footprints_root: Path) -> dict[str, dict[str, object]]:
    result = {}
    if not footprints_root.exists():
        return result
    for manifest_path in footprints_root.rglob("manifest.json"):
        manifest = load_coverage_manifest(manifest_path)
        for entry in manifest.entries:
            key = ("actual:" if entry.selector_kind == "actual_year" else "published:") + entry.selector
            if key in result:
                raise ValueError("duplicate NSRDB footprint selector")
            meta_path = manifest_path.parent / "meta.bin"
            if meta_path.exists():
                digest = hashlib.sha256(meta_path.read_bytes()).hexdigest()
                if digest != entry.meta_sha256:
                    raise ValueError("source meta checksum mismatch")
            result[key] = {
                "cells": [list(cell) for cell in sorted(entry.cells)],
                "step_degrees": entry.step_degrees,
                "basis": entry.basis,
                "product_id": entry.product_id,
                "source_file_id": entry.source_file_id,
                "source_version": entry.source_version,
                "selector_kind": entry.selector_kind,
                "selector": entry.selector,
                "retrieved_at": entry.retrieved_at,
                "source_modified_at": entry.source_modified_at,
                "meta_sha256": entry.meta_sha256,
                "coordinate_count": entry.coordinate_count,
                "stale": entry.stale,
            }
    return result


def build_map(
    snapshot_root: Path, output_root: Path, footprints_root: Path, topology_path: Path
) -> Path:
    """Produce ignored local HTML; never download or mutate source snapshots."""
    records = _verify_ledger(snapshot_root)
    analysis = json.loads((snapshot_root / "analysis.json").read_text(encoding="utf-8"))
    if analysis.get("errors"):
        raise ValueError("Stage 1 analysis contains errors")
    inventories = analysis["inventories"]
    year_lookup = inventories["noaa-inventory-authorized"]["station_years"]
    noaa = []
    zero_origin = 0
    for site in inventories["noaa-history"]["sites"]:
        listed = year_lookup.get(site["id"])
        if listed is None:
            continue
        latitude, longitude = site.get("lat"), site.get("lon")
        if latitude is None or longitude is None or not (
            -90 <= latitude <= 90 and -180 <= longitude <= 180
        ):
            continue
        if latitude == 0 and longitude == 0:
            zero_origin += 1
            continue
        noaa.append([
            site["id"], _coordinate(latitude), _coordinate(longitude),
            int(site["start"][:4]), int(site["end"][:4]), _year_bits(listed),
        ])
    onebuilding = []
    unmapped = 0
    sources = ("onebuilding-us", "onebuilding-uk", "onebuilding-au")
    for source in sources:
        for product in inventories[source]["coordinate_matches"]:
            review = product.get("review") or {}
            status = review.get("status", "")
            if status == "reviewed_metadata_match":
                point = review.get("coordinates") or {}
                latitude, longitude = point.get("lat"), point.get("lon")
                position = "reviewed metadata"
            elif status == "approximate_locality":
                point = review.get("approximate_location") or {}
                latitude, longitude = point.get("lat"), point.get("lon")
                position = "approximate locality"
            elif status == "name_code_conflict":
                latitude = longitude = None
                position = "name/code conflict"
            else:
                latitude, longitude = product.get("lat"), product.get("lon")
                position = product.get("position_status", "unknown")
            if latitude is None or longitude is None or not (
                -90 <= latitude <= 90 and -180 <= longitude <= 180
            ):
                unmapped += 1
                continue
            onebuilding.append([
                product.get("station_id") or "", _coordinate(latitude), _coordinate(longitude),
                product.get("product") or "", product.get("period") or "", position,
            ])
    oedi = []
    for site in inventories["oedi-sites"]["sites"]:
        latitude, longitude = site.get("lat"), site.get("lon")
        if latitude is not None and longitude is not None:
            oedi.append([site["id"], _coordinate(latitude), _coordinate(longitude)])
    payload = {
        "schema": "stage2-map-1",
        "noaa": noaa,
        "onebuilding": onebuilding,
        "oedi": oedi,
        "nsrdb": {"points": _points(snapshot_root, records), "masks": _masks(footprints_root)},
        "counts": {
            "noaa_history": len(inventories["noaa-history"]["sites"]),
            "noaa_mappable": len(noaa),
            "noaa_zero_origin": zero_origin,
            "noaa_unmatched_inventory_ids": inventories["noaa-inventory-authorized"]
            ["stations_without_history_coordinates"],
            "onebuilding_products": sum(inventories[source]["product_count"] for source in sources),
            "onebuilding_mappable": len(onebuilding),
            "onebuilding_unmapped": unmapped,
            "oedi_sites": len(oedi),
        },
    }
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    if topology.get("type") != "Topology" or "countries" not in topology.get("objects", {}):
        raise ValueError("invalid world topology")
    template = (Path(__file__).parent / "map.html").read_text(encoding="utf-8")
    encoded = base64.b64encode(gzip.compress(json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8"), compresslevel=9)).decode("ascii")
    html = template.replace("__TOPOLOGY__", json.dumps(topology, separators=(",", ":")))
    html = html.replace("__PAYLOAD__", encoded)
    if "__TOPOLOGY__" in html or "__PAYLOAD__" in html:
        raise ValueError("incomplete map template")
    output_root.mkdir(parents=True, exist_ok=True)
    destination = output_root / "availability-map.html"
    destination.write_text(html, encoding="utf-8")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--footprints-root", type=Path,
                        default=Path(".local/mcp-availability/nsrdb-footprints"))
    parser.add_argument("--topology", required=True, type=Path)
    parser.add_argument("--output-root", type=Path,
                        default=Path(".local/mcp-availability/maps"))
    args = parser.parse_args()
    if not args.output_root.resolve().is_relative_to((Path.cwd() / ".local").resolve()):
        raise ValueError("map output must stay under the ignored .local tree")
    print(build_map(args.snapshot_root, args.output_root, args.footprints_root, args.topology))


if __name__ == "__main__":
    main()
