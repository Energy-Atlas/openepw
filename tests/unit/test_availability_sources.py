"""Source-specific imports retain product, point and future-window limits."""

from datetime import datetime, timezone

from openepw.availability import EvidenceRef
from openepw.availability.importers import normalize_analysis


def test_contracts_keep_adapter_support_and_probe_scope():
    evidence = [EvidenceRef(id=name, sha256="a" * 64,
                            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
                            basis="targeted_probe" if name in ("pvgis-london", "nsrdb-ithaca")
                            else "inventory") for name in
                ("openmeteo-doc", "pvgis-london", "nsrdb-ithaca", "cds-era5")]
    inventories = {
        "pvgis-london": {"location": {"latitude": 51.507, "longitude": -0.128},
                          "meteo_data": {"year_min": 2005, "year_max": 2023},
                          "months_selected": [{"month": 1, "year": 2016}]},
        "nsrdb-ithaca": {"location": {"lat": 42.44, "lon": -76.5}, "products": [
            {"name": "nsrdb-GOES-aggregated-v4-0-0", "available_years_or_products":
             [1998, 2025], "intervals": [30, 60]},
            {"name": "nsrdb-GOES-tmy-v4-0-0", "available_years_or_products":
             ["tmy", "tmy-2025"], "intervals": [60]}]},
        "cds-era5": {"dataset": "reanalysis-era5-single-levels",
                      "extent": {"spatial": {"bbox": [[0, -89, 360, 89]]},
                                 "temporal": {"interval": [["1940-01-01T00:00:00+00:00",
                                                            "2026-09-17T00:00:00+00:00"]]}}},
    }
    bundle = normalize_analysis(inventories, evidence)
    land = next(p for p in bundle.products if p.id == "openmeteo:era5_land")
    assert "ghi" in land.source_variables
    assert "ghi" not in land.adapter_variables
    pvgis = next(e for e in bundle.entries if e.product_id == "pvgis:tmy:v5_3")
    assert pvgis.scope.kind == "tmy_reference"
    assert (pvgis.scope.start_year, pvgis.scope.end_year) == (2005, 2023)
    assert pvgis.probe_location.lat == 51.507
    actual = next(e for e in bundle.entries if e.product_id == "nsrdb:aggregate:v4")
    assert actual.scope.years == [1998, 2025]
    assert actual.probe_location is not None
    assert next(p for p in bundle.products if p.id == "cds:era5").footprint == (0, -89, 360, 89)


def test_future_membership_keeps_scenario_windows_and_unknown_quality():
    evidence = [EvidenceRef(id=name, sha256="a" * 64,
                            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
                            basis="inventory",
                            etag='"archive-v1"' if name == "oedi-45-revised-directory" else None)
                for name in
                ("cmip6-catalog", "cmip6-license", "oedi-sites", "oedi-45-revised-directory")]
    inventories = {
        "cmip6-catalog": {"combinations": [{"model": "ACCESS-CM2", "member": "r1i1p1f1",
                                               "grid": "gn", "scenario": "ssp245",
                                               "variables": ["tas", "rsds"],
                                               "temporal_coverage": "unknown"}]},
        "cmip6-license": {"licenses": {"ACCESS-CM2": {"id": "CC BY 4.0",
                                                    "history": "originally CC BY-SA 4.0"}}},
        "oedi-sites": {"sites": [{"id": "G01000100", "lat": 34.65, "lon": -87.765,
                                   "elevation_m": 221}]},
        "oedi-45-revised-directory": {"scenario": "RCP4.5", "site_years": {
            "G01000100": {"RCP4.5": [2045, 2046, 2085, 2086]}}},
    }
    bundle = normalize_analysis(inventories, evidence)
    cmip = next(e for e in bundle.entries if e.product_id.startswith("cmip6:"))
    assert cmip.scope.scenario == "ssp245"
    assert cmip.scope.start_year is None
    assert cmip.weather_complete is None
    assert next(p for p in bundle.products if p.id == cmip.product_id).license_history == (
        "originally CC BY-SA 4.0")
    oedi = [e for e in bundle.entries if e.product_id == "oedi:rcp45"]
    assert {(e.scope.start_year, e.scope.end_year) for e in oedi} == {
        (2045, 2054), (2085, 2094)}
    assert all(e.weather_complete is None for e in oedi)
    assert all(e.source_etag == '"archive-v1"' for e in oedi)
