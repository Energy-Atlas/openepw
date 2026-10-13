"""Existing-weather source contracts and narrowly scoped probes."""

from __future__ import annotations

from datetime import date, datetime

from openepw.models import Location

from ..models import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    ProductRecord,
    TMYReferenceScope,
)

_EPW_FIELDS = ["dry_bulb", "dew_point", "relative_humidity", "pressure", "ghi", "dni",
               "dhi", "wind_speed", "wind_direction"]

# NSRDB API datasets the provider adapter downloads, and their catalog product ids.
NSRDB_PRODUCT_IDS = {"nsrdb-GOES-aggregated-v4-0-0": "nsrdb:aggregate:v4", "nsrdb-GOES-tmy-v4-0-0": "nsrdb:tmy:v4"}
# Kept in step with providers/nsrdb.py DATASETS (checked by a test).
NSRDB_ADAPTED = frozenset((*NSRDB_PRODUCT_IDS, "himawari7", "himawari-tmy", "nsrdb-msg-v1-0-0",
                           "nsrdb-msg-v1-0-0-tmy", "nsrdb-msg-v1-0-0-tdy", "nsrdb-msg-v1-0-0-tgy",
                           "msg-iodc"))


def _location(value: dict | None) -> Location | None:
    if not value:
        return None
    lat = value.get("lat", value.get("latitude"))
    lon = value.get("lon", value.get("longitude"))
    return Location(lat=lat, lon=lon) if lat is not None and lon is not None else None


def normalize_contracts(inventories: dict, known: set[str], probe_locations: dict) -> CatalogBundle:
    products = []
    entries = []
    if "openmeteo-doc" in known:
        for dataset, start, adapter in (
            ("era5", 1940, _EPW_FIELDS),
            ("era5_land", 1950, _EPW_FIELDS[:4]),
        ):
            product_id = f"openmeteo:{dataset}"
            products.append(ProductRecord(
                id=product_id, provider="openmeteo", dataset=dataset, spatial_kind="grid",
                temporal_kind="actual", source_variables=_EPW_FIELDS,
                adapter_variables=adapter, delivered_resolution_minutes=60,
                evidence_ids=["openmeteo-doc"],
            ))
            entries.append(AvailabilityEntry(
                id=f"{product_id}:documented", product_id=product_id,
                scope=ActualScope(operating_start=date(start, 1, 1)),
                evidence_basis="documentation", evidence_ids=["openmeteo-doc"],
            ))
    london = inventories.get("pvgis-london")
    if london and "pvgis-london" in known:
        product_id = "pvgis:tmy:v5_3"
        products.append(ProductRecord(
            id=product_id, provider="pvgis", dataset="PVGIS TMY", version="v5_3",
            spatial_kind="grid", temporal_kind="tmy_reference",
            adapter_variables=_EPW_FIELDS, source_variables=_EPW_FIELDS,
            evidence_ids=["pvgis-london"],
        ))
        meteo = london.get("meteo_data", {})
        selected = {int(m["month"]): int(m["year"]) for m in london.get("months_selected", [])}
        entries.append(AvailabilityEntry(
            id="pvgis:tmy:v5_3:london-probe", product_id=product_id,
            scope=TMYReferenceScope(start_year=meteo.get("year_min"),
                                    end_year=meteo.get("year_max"),
                                    product_label="PVGIS TMY v5_3 London",
                                    selected_month_years=selected),
            evidence_basis="targeted_probe", evidence_ids=["pvgis-london"],
            probe_location=_location(london.get("location")),
        ))
    # Every saved NSRDB data-query probe (Stage 1: Ithaca, Phoenix; 2026-10-13: Singapore,
    # Nairobi, London). A dataset the adapter does not download is catalogued as unsupported.
    probe_ids = sorted(key for key, value in inventories.items()
                       if key.startswith("nsrdb-") and isinstance(value, dict) and "products" in value)
    for probe_id in probe_ids:
        probe = inventories.get(probe_id)
        if not probe or probe_id not in known:
            continue
        location = _location(probe.get("location") or probe_locations.get(probe_id))
        for item in probe.get("products", []):
            native = item["name"]
            values = item.get("available_years_or_products", [])
            typical = bool(values) and not any(isinstance(value, int) for value in values)
            product_id = NSRDB_PRODUCT_IDS.get(native, f"nsrdb:{native}" if native in NSRDB_ADAPTED
                                               else f"nsrdb:upstream:{native}")
            kind = "tmy_reference" if typical else "actual"
            adapter = _EPW_FIELDS if native in NSRDB_ADAPTED else []
            if not any(p.id == product_id for p in products):
                products.append(ProductRecord(
                    id=product_id, provider="nsrdb", dataset=native, version="v4",
                    native_product_id=native, spatial_kind="grid", temporal_kind=kind,
                    source_variables=_EPW_FIELDS, adapter_variables=adapter,
                    adapter_supported=bool(adapter),
                    access_requirements=["OPENEPW_NLR_API_KEY", "OPENEPW_NLR_EMAIL"],
                    evidence_ids=[probe_id],
                ))
            if kind == "actual":
                scope = ActualScope(years=sorted(v for v in values if isinstance(v, int)))
                entries.append(AvailabilityEntry(
                    id=f"{product_id}:{probe_id}:actual", product_id=product_id,
                    scope=scope, evidence_basis="targeted_probe", evidence_ids=[probe_id],
                    probe_location=location,
                ))
            else:
                for label in values:
                    entries.append(AvailabilityEntry(
                        id=f"{product_id}:{probe_id}:{label}", product_id=product_id,
                        scope=TMYReferenceScope(product_label=str(label)),
                        evidence_basis="targeted_probe", evidence_ids=[probe_id],
                        probe_location=location,
                    ))
    for source_id, product_id, start_year in (
        ("cds-era5", "cds:era5", 1940), ("cds-land", "cds:era5_land", 1950),
    ):
        item = inventories.get(source_id)
        if not item or source_id not in known:
            continue
        extent = item.get("extent", {})
        bboxes = extent.get("spatial", {}).get("bbox", [])
        bbox = tuple(bboxes[0]) if bboxes else None
        intervals = extent.get("temporal", {}).get("interval", [])
        last = datetime.fromisoformat(intervals[0][1]).date() if intervals else None
        products.append(ProductRecord(
            id=product_id, provider="cds", dataset=item.get("dataset", product_id),
            spatial_kind="grid", temporal_kind="actual", footprint=bbox,
            longitude_convention="0_360", source_variables=_EPW_FIELDS,
            adapter_variables=[v for v in _EPW_FIELDS if v not in ("dni", "dhi")],
            access_requirements=["OPENEPW_CDS_KEY", "accepted_terms"],
            license_effective=item.get("license"), evidence_ids=[source_id],
        ))
        entries.append(AvailabilityEntry(
            id=f"{product_id}:catalog-interval", product_id=product_id,
            scope=ActualScope(operating_start=date(start_year, 1, 1), operating_end=last),
            evidence_basis="inventory", evidence_ids=[source_id],
        ))
    return CatalogBundle(products=products, entries=entries)
