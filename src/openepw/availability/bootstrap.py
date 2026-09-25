"""Small curated source contracts usable before a local inventory import."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone

from .models import ActualScope, AvailabilityEntry, CatalogBundle, EvidenceRef, ProductRecord

_FIELDS = ["dry_bulb", "dew_point", "relative_humidity", "pressure", "ghi", "dni",
           "dhi", "wind_speed", "wind_direction"]
_CONTRACT_TEXT = (
    "Stage 1 curated documentation, 2026-09-24: Open-Meteo ERA5 1940, ERA5-Land 1950; "
    "CDS ERA5 1940, ERA5-Land 1950, machine bbox 0,-89,360,89. "
    "Adapter variable restrictions are from OpenEPW v0.1."
)


def bundled_contracts() -> CatalogBundle:
    """Return selected documented facts, not a substitute for source inventories."""
    evidence = EvidenceRef(
        id="bundled-stage1-contracts", sha256=hashlib.sha256(_CONTRACT_TEXT.encode()).hexdigest(),
        retrieved_at=datetime(2026, 9, 24, tzinfo=timezone.utc), basis="documentation",
        scope="Checksum of curated bundled summary, not upstream source bytes",
        attribution="Stage 1 source register: docs/validation/mcp-stage-1/sources.md",
    )
    products = []
    entries = []
    for provider, dataset, start, adapter, citation in (
        ("openmeteo", "era5", 1940, _FIELDS,
         "https://open-meteo.com/en/docs/historical-weather-api"),
        ("openmeteo", "era5_land", 1950, _FIELDS[:4],
         "https://open-meteo.com/en/docs/historical-weather-api"),
        ("cds", "reanalysis-era5-single-levels", 1940,
         [v for v in _FIELDS if v not in ("dni", "dhi")],
         "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels"),
        ("cds", "reanalysis-era5-land", 1950,
         [v for v in _FIELDS if v not in ("dni", "dhi")],
         "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land"),
    ):
        product_id = (f"openmeteo:{dataset}" if provider == "openmeteo" else
                      "cds:era5_land" if "land" in dataset else "cds:era5")
        products.append(ProductRecord(
            id=product_id, provider=provider, dataset=dataset,
            spatial_kind="grid", temporal_kind="actual",
            footprint=(0, -89, 360, 89) if provider == "cds" else None,
            longitude_convention="0_360" if provider == "cds" else None,
            source_variables=_FIELDS if provider == "openmeteo" else adapter,
            adapter_variables=adapter,
            access_requirements=["OPENEPW_CDS_KEY", "accepted_terms"] if provider == "cds"
            else [], citation=citation, evidence_ids=[evidence.id],
        ))
        entries.append(AvailabilityEntry(
            id=f"{product_id}:bundled-start", product_id=product_id,
            scope=ActualScope(operating_start=date(start, 1, 1)),
            evidence_basis="documentation", evidence_ids=[evidence.id],
        ))
    return CatalogBundle(evidence=[evidence], products=products, entries=entries)
