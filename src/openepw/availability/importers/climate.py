"""Future method inventories; catalog membership is not weather validation."""

from __future__ import annotations

from ..models import (
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    FutureWindowScope,
    ProductRecord,
    SiteRecord,
)


def normalize_climate(inventories: dict, evidence: dict[str, EvidenceRef]) -> CatalogBundle:
    known = set(evidence)
    products = []
    sites = []
    entries = []
    catalog = inventories.get("cmip6-catalog", {})
    licenses = inventories.get("cmip6-license", {}).get("licenses", {})
    if "cmip6-catalog" in known:
        for combination in catalog.get("combinations", []):
            model = combination["model"]
            member = combination["member"]
            grid = combination["grid"]
            scenario = combination["scenario"]
            product_id = f"cmip6:{model}:{member}:{grid}:{scenario}"
            refs = ["cmip6-catalog"]
            license_info = licenses.get(model, {}) if "cmip6-license" in known else {}
            if license_info:
                refs.append("cmip6-license")
            products.append(ProductRecord(
                id=product_id, provider="cmip6", dataset="Pangeo CMIP6 Amon",
                native_product_id=f"{model}/{member}/{grid}/{scenario}",
                spatial_kind="grid", temporal_kind="future_window",
                source_variables=combination.get("variables", []),
                adapter_variables=combination.get("variables", []),
                license_effective=license_info.get("id"),
                license_history=license_info.get("history"),
                evidence_ids=refs,
            ))
            entries.append(AvailabilityEntry(
                id=f"{product_id}:catalog", product_id=product_id,
                scope=FutureWindowScope(scenario=scenario, model=model, member=member,
                                        grid=grid),
                variables=combination.get("variables", []), evidence_basis="inventory",
                evidence_ids=["cmip6-catalog"],
            ))
    location_rows = {str(item["id"]): item for item in
                     inventories.get("oedi-sites", {}).get("sites", [])}
    for source_id, scenario, product_id in (
        ("oedi-45-revised-directory", "rcp45", "oedi:rcp45"),
        ("oedi-85-revised-directory", "rcp85", "oedi:rcp85"),
    ):
        directory = inventories.get(source_id)
        if not directory or source_id not in known or "oedi-sites" not in known:
            continue
        refs = ["oedi-sites", source_id]
        products.append(ProductRecord(
            id=product_id, provider="oedi", dataset="WRF/CCSM4 EPW trajectories",
            spatial_kind="station", temporal_kind="future_window",
            source_variables=["epw_hourly_trajectory"],
            adapter_variables=["epw_hourly_trajectory"], evidence_ids=refs,
        ))
        native_scenario = "RCP4.5" if scenario == "rcp45" else "RCP8.5"
        for native_site_id, scenarios in directory.get("site_years", {}).items():
            row = location_rows.get(str(native_site_id))
            if row is None:
                continue
            site_id = f"{product_id}:{native_site_id}"
            sites.append(SiteRecord(
                id=site_id, product_id=product_id, lat=row.get("lat"), lon=row.get("lon"),
                elevation_m=row.get("elevation_m"), position_status="published",
                station_identity_status="verified", candidate_station_ids=[str(native_site_id)],
                evidence_ids=refs,
            ))
            listed = set(int(year) for year in scenarios.get(native_scenario, []))
            for start, end in ((2045, 2054), (2085, 2094)):
                years = sorted(year for year in listed if start <= year <= end)
                if not years:
                    continue
                entries.append(AvailabilityEntry(
                    id=f"{site_id}:{start}-{end}", product_id=product_id, site_id=site_id,
                    scope=FutureWindowScope(start_year=start, end_year=end,
                                            scenario=scenario, listed_years=years),
                    evidence_basis="inventory", evidence_ids=refs,
                    source_etag=evidence[source_id].etag,
                ))
    return CatalogBundle(products=products, sites=sites, entries=entries)
