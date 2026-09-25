"""Offline import of the accepted Stage 1 metadata snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from importlib.resources import files
from pathlib import Path

from .importers import normalize_analysis
from .models import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    ProductRecord,
    ReviewAnnotation,
    SiteRecord,
    TMYReferenceScope,
)
from .store import CatalogImportError


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence(root: Path, ledger: dict) -> tuple[list[EvidenceRef], dict[str, str]]:
    evidence = []
    checksums = {}
    for record in ledger.get("records", []):
        if record.get("outcome") != "saved":
            continue
        source_id = record["id"]
        snapshot = record.get("snapshot")
        if not snapshot or snapshot != f"raw/{source_id}.body":
            raise CatalogImportError("Invalid source snapshot path")
        raw = root / snapshot
        if not raw.is_file():
            raise CatalogImportError(f"SNAPSHOT_MISSING: {source_id}")
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        if digest != record.get("sha256"):
            raise CatalogImportError(f"SNAPSHOT_CHECKSUM: {source_id}")
        basis = ("targeted_probe" if record.get("kind") == "probe" else
                 "documentation" if record.get("kind") == "documentation" else "inventory")
        evidence.append(EvidenceRef(
            id=source_id, source_url=record.get("url"), sha256=digest,
            retrieved_at=datetime.fromisoformat(record.get("finished_at") or
                                                 ledger.get("created_at") or
                                                 datetime.now(timezone.utc).isoformat()),
            basis=basis, last_modified=record.get("headers", {}).get("last-modified"),
            etag=record.get("headers", {}).get("etag"),
        ))
        checksums[source_id] = digest
    return evidence, checksums


def _noaa(inventories: dict, known: set[str]) -> tuple[list[ProductRecord], list[SiteRecord], list[AvailabilityEntry]]:
    history = inventories.get("noaa-history", {})
    counts = inventories.get("noaa-inventory-authorized", {})
    if not history and not counts:
        return [], [], []
    refs = [name for name in ("noaa-history", "noaa-inventory-authorized") if name in known]
    product = ProductRecord(id="noaa:isd", provider="noaa", dataset="ISD global-hourly", spatial_kind="station",
                            temporal_kind="actual", source_variables=["dry_bulb", "dew_point",
                            "relative_humidity", "wind_speed", "wind_direction"],
                            adapter_variables=["dry_bulb", "dew_point", "relative_humidity",
                                               "wind_speed", "wind_direction"], evidence_ids=refs)
    sites_by_id = {}
    for source in history.get("sites", []):
        station_id = str(source["id"])
        sites_by_id[station_id] = SiteRecord(
            id=station_id, product_id=product.id, lat=source.get("lat"), lon=source.get("lon"),
            elevation_m=source.get("elevation_m"), position_status="published",
            station_identity_status="verified", candidate_station_ids=[station_id],
            operating_start=date.fromisoformat(source["start"]) if source.get("start") else None,
            operating_end=date.fromisoformat(source["end"]) if source.get("end") else None,
            evidence_ids=["noaa-history"] if "noaa-history" in known else [],
        )
    entries = []
    for station_id, listed in counts.get("station_years", {}).items():
        station_id = str(station_id)
        if station_id not in sites_by_id:
            sites_by_id[station_id] = SiteRecord(id=station_id, product_id=product.id,
                                                candidate_station_ids=[station_id],
                                                evidence_ids=["noaa-inventory-authorized"])
        years = sorted(int(year) for year in listed)
        month_counts = {int(year): {month: int(value) for month, value in
                      enumerate(months, start=1)} for year, months in listed.items()}
        entries.append(AvailabilityEntry(
            id=f"noaa:isd:{station_id}:years", product_id=product.id, site_id=station_id,
            scope=ActualScope(years=years, month_counts=month_counts),
            evidence_basis="inventory", evidence_ids=["noaa-inventory-authorized"],
        ))
    return [product], list(sites_by_id.values()), entries


def _onebuilding(inventories: dict, known: set[str], checksums: dict[str, str], registry: dict):
    products = []
    sites = []
    entries = []
    reviews = []
    decision_by_url = {r["catalog_url"]: r for r in registry.get("reviews", [])}
    if len(decision_by_url) != len(registry.get("reviews", [])):
        raise CatalogImportError("Duplicate accepted review")
    seen_reviews = set()
    for inventory_id in ("onebuilding-us", "onebuilding-uk", "onebuilding-au"):
        for match in inventories.get(inventory_id, {}).get("coordinate_matches", []):
            url = match["url"]
            token = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
            product_id = f"onebuilding:{token}"
            site_id = f"onebuilding-site:{token}"
            label = match.get("product") or "published"
            period = match.get("period")
            start_year = end_year = None
            if period:
                try:
                    start_year, end_year = (int(part) for part in period.split("-", 1))
                except (ValueError, AttributeError):
                    pass
            match_refs = [ref for ref in match.get("evidence_ids", []) if ref in known]
            if inventory_id in known and inventory_id not in match_refs:
                match_refs.append(inventory_id)
            products.append(ProductRecord(
                id=product_id, provider="onebuilding", dataset="OneBuilding published EPW",
                native_product_id=url, spatial_kind="station", temporal_kind="tmy_reference",
                adapter_variables=["dry_bulb", "dew_point", "relative_humidity", "pressure",
                                   "ghi", "dni", "dhi", "wind_speed", "wind_direction"],
                evidence_ids=match_refs,
            ))
            lat, lon = match.get("lat"), match.get("lon")
            position_status = match.get("position_status", "unknown")
            if position_status not in ("published", "inferred", "consensus",
                                       "approximate_locality", "unknown", "conflicted"):
                position_status = "unknown"
            review = decision_by_url.get(url)
            if review:
                seen_reviews.add(url)
                review_data = match.get("review", {})
                pins_match = all(
                    checksums.get(source_id) == registry.get("source_checksums", {}).get(source_id)
                    for source_id in review.get("evidence_ids", [])
                )
                review_valid = (pins_match and review_data.get("status") == review["status"] and
                                review_data.get("published_url") == review.get("published_url"))
                status = review["status"] if review_valid else "stale_evidence"
                authority = None
                if status == "reviewed_metadata_match":
                    coords = review_data.get("coordinates") or {}
                    lat, lon = coords.get("lat"), coords.get("lon")
                    position_status = "published" if lat is not None and lon is not None else "unknown"
                    authority = "reviewed_metadata" if position_status == "published" else None
                elif status in ("approximate_locality", "name_code_conflict", "stale_evidence"):
                    lat, lon = None, None
                    position_status = ("approximate_locality" if status == "approximate_locality"
                                       else "unknown")
                reviews.append(ReviewAnnotation(
                    product_id=product_id, catalog_url=url, status=status,
                    rationale=review["rationale"], accepted_on=date.fromisoformat(
                        registry.get("accepted_on", "2026-09-24")),
                    evidence_ids=review.get("evidence_ids", []),
                    source_checksums=registry.get("source_checksums", {}),
                    alternate_url=review.get("published_url"), coordinate_authority=authority,
                    original_position_status=match.get("position_status"),
                    original_match_reason=match.get("reason"),
                ))
            station_status = match.get("station_identity_status", "unknown")
            if station_status not in ("verified", "candidate", "ambiguous", "unknown"):
                station_status = "unknown"
            sites.append(SiteRecord(
                id=site_id, product_id=product_id, lat=lat, lon=lon,
                elevation_m=(match.get("elevation_m") if review is None else None),
                position_status=position_status, station_identity_status=station_status,
                candidate_station_ids=[str(x) for x in match.get("source_station_ids", [])],
                evidence_ids=match_refs,
            ))
            entries.append(AvailabilityEntry(
                id=f"{product_id}:published", product_id=product_id, site_id=site_id,
                scope=TMYReferenceScope(start_year=start_year, end_year=end_year,
                                        product_label=label), evidence_basis="inventory",
                evidence_ids=match_refs,
            ))
    if not set(decision_by_url) <= seen_reviews:
        raise CatalogImportError("Accepted review missing from parsed products")
    return products, sites, entries, reviews


def import_stage1(root: Path, *, reviews_path: Path | None = None) -> CatalogBundle:
    root = Path(root)
    if not (root / "ledger.json").is_file() or not (root / "analysis.json").is_file():
        raise CatalogImportError("SNAPSHOT_MISSING: ledger or analysis absent")
    ledger = _json(root / "ledger.json")
    evidence, checksums = _evidence(root, ledger)
    analysis = _json(root / "analysis.json")
    if (not isinstance(analysis, dict) or
            analysis.get("schema_version") != "mcp-research-1" or
            analysis.get("ledger_sha256") != hashlib.sha256(
                (root / "ledger.json").read_bytes()).hexdigest() or
            analysis.get("source_checksums") != checksums or
            not isinstance(analysis.get("inventories"), dict) or
            analysis.get("errors")):
        raise CatalogImportError("ANALYSIS_INPUT_MISMATCH: regenerate local analysis offline")
    inventories = analysis["inventories"]
    if reviews_path is None:
        registry = json.loads(files("openepw.availability").joinpath(
            "data/onebuilding_reviews.json").read_text(encoding="utf-8"))
    else:
        registry = _json(reviews_path)
    known = set(checksums)
    noaa_products, noaa_sites, noaa_entries = _noaa(inventories, known)
    ob_products, ob_sites, ob_entries, reviews = _onebuilding(
        inventories, known, checksums, registry)
    probe_locations = {}
    for record in ledger.get("records", []):
        point = record.get("parameters", {}).get("wkt", "")
        match = re.fullmatch(r"POINT\((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\)", point)
        if match:
            probe_locations[record["id"]] = {"lon": float(match[1]), "lat": float(match[2])}
    remaining = normalize_analysis(inventories, evidence, probe_locations=probe_locations)
    return CatalogBundle(evidence=evidence,
                         products=noaa_products + ob_products + remaining.products,
                         sites=noaa_sites + ob_sites + remaining.sites,
                         entries=noaa_entries + ob_entries + remaining.entries,
                         reviews=reviews)
