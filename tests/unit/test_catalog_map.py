"""Stage 1 catalog detail is served as display layers without inventing coverage."""

import hashlib
import json
from datetime import datetime, timezone

import pytest

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    ProductRecord,
    SiteRecord,
    TMYReferenceScope,
)
from openepw.availability.map_layers import catalog_map, merge_cell_rows
from openepw.availability.store import CatalogStore
from openepw.config import RuntimeConfig
from openepw.models import Location
from openepw.service import WeatherService

WHEN = datetime(2026, 9, 24, tzinfo=timezone.utc)


def _evidence(identifier, basis="inventory"):
    return EvidenceRef(id=identifier, sha256="a" * 64, retrieved_at=WHEN, basis=basis)


def _bundle():
    return CatalogBundle(
        evidence=[_evidence("noaa"), _evidence("ob"), _evidence("cds"), _evidence("pv", "targeted_probe"),
                  _evidence("om", "documentation")],
        products=[
            ProductRecord(id="noaa:isd", provider="noaa", dataset="ISD global-hourly",
                          spatial_kind="station", temporal_kind="actual", evidence_ids=["noaa"]),
            ProductRecord(id="onebuilding:a", provider="onebuilding", dataset="OneBuilding published EPW",
                          spatial_kind="station", temporal_kind="tmy_reference", evidence_ids=["ob"]),
            ProductRecord(id="onebuilding:b", provider="onebuilding", dataset="OneBuilding published EPW",
                          spatial_kind="station", temporal_kind="tmy_reference", evidence_ids=["ob"]),
            ProductRecord(id="cds:era5", provider="cds", dataset="reanalysis-era5-single-levels",
                          spatial_kind="grid", temporal_kind="actual", footprint=(0, -89, 360, 89),
                          longitude_convention="0_360", evidence_ids=["cds"]),
            ProductRecord(id="openmeteo:era5", provider="openmeteo", dataset="era5",
                          spatial_kind="grid", temporal_kind="actual", evidence_ids=["om"]),
            ProductRecord(id="pvgis:tmy:v5_3", provider="pvgis", dataset="PVGIS TMY",
                          spatial_kind="grid", temporal_kind="tmy_reference", evidence_ids=["pv"]),
            ProductRecord(id="nsrdb:tmy:v4", provider="nsrdb", dataset="nsrdb-GOES-tmy-v4-0-0",
                          spatial_kind="grid", temporal_kind="tmy_reference", evidence_ids=["pv"]),
            ProductRecord(id="nsrdb:aggregate:v4", provider="nsrdb", dataset="nsrdb-GOES-aggregated-v4-0-0",
                          spatial_kind="grid", temporal_kind="actual", evidence_ids=["pv"]),
        ],
        sites=[
            SiteRecord(id="S1", product_id="noaa:isd", lat=42.0, lon=-76.0, position_status="published"),
            SiteRecord(id="S2", product_id="noaa:isd", lat=0.0, lon=0.0, position_status="published"),
            SiteRecord(id="S3", product_id="noaa:isd", position_status="unknown"),
            SiteRecord(id="S4", product_id="noaa:isd", lat=10.0, lon=10.0, position_status="published"),
            SiteRecord(id="O1", product_id="onebuilding:a", lat=-10.05, lon=143.07,
                       position_status="published"),
            SiteRecord(id="O2", product_id="onebuilding:b", lat=21.3, lon=-157.8,
                       position_status="approximate_locality"),
        ],
        entries=[
            AvailabilityEntry(id="e1", product_id="noaa:isd", site_id="S1", evidence_basis="inventory",
                              scope=ActualScope(years=[2016, 2017, 2018, 2020],
                                                month_counts={2016: {1: 5}, 2017: {1: 9}, 2018: {3: 1},
                                                              2020: {1: 0}})),
            AvailabilityEntry(id="e2", product_id="noaa:isd", site_id="S2", evidence_basis="inventory",
                              scope=ActualScope(years=[2018], month_counts={2018: {1: 2}})),
            AvailabilityEntry(id="e3", product_id="noaa:isd", site_id="S3", evidence_basis="inventory",
                              scope=ActualScope(years=[2018], month_counts={2018: {1: 2}})),
            AvailabilityEntry(id="o1", product_id="onebuilding:a", site_id="O1", evidence_basis="inventory",
                              scope=TMYReferenceScope(start_year=2009, end_year=2023,
                                                      product_label="TMYx.2009-2023")),
            AvailabilityEntry(id="o2", product_id="onebuilding:b", site_id="O2", evidence_basis="inventory",
                              scope=TMYReferenceScope(product_label="TMY3")),
            AvailabilityEntry(id="p1", product_id="pvgis:tmy:v5_3", evidence_basis="targeted_probe",
                              scope=TMYReferenceScope(product_label="PVGIS TMY v5_3 London"),
                              probe_location=Location(lat=51.507, lon=-0.128)),
        ],
    )


def _mask(root, cells, *, stale=False, tamper=False):
    folder = root / "nsrdb" / "nsrdb-GOES-tmy-v4-0-0" / "tdy-2023"
    folder.mkdir(parents=True)
    mask = json.dumps({"cells": cells, "step_degrees": 0.25}).encode()
    (folder / "mask.json").write_bytes(mask)
    digest = hashlib.sha256(mask).hexdigest()
    (folder / "manifest.json").write_text(json.dumps({"schema_version": 1, "entries": [{
        "product_id": "nsrdb-GOES-tmy-v4-0-0", "selector_kind": "published_name", "selector": "tdy-2023",
        "basis": "source_grid_sites", "mask_path": "mask.json",
        "mask_sha256": "0" * 64 if tamper else digest, "meta_sha256": "b" * 64,
        "coordinate_count": 12, "step_degrees": 0.25, "stale": stale,
        "source_file_id": "GOES/tmy/v4.0.0/nsrdb_tdy-2023.h5", "source_version": "4.0.1",
        "retrieved_at": "2026-09-24T23:11:32+00:00",
        "source_modified_at": "Mon, 16 Sep 2024 20:14:37 GMT"}]}))


def _layer(result, identifier):
    return next(layer for layer in result["layers"] if layer["id"] == identifier)


def test_noaa_stations_keep_reported_years_and_skip_unplaceable_sites(tmp_path):
    result = catalog_map(_bundle(), tmp_path)
    noaa = _layer(result, "noaa")
    assert noaa["points"] == [[-76.0, 42.0, "S1", [[2016, 2018]], None]]
    assert noaa["omitted"] == {"no_coordinates": 1, "zero_origin": 1}


def test_onebuilding_sites_carry_product_period_and_position(tmp_path):
    sites = _layer(catalog_map(_bundle(), tmp_path), "onebuilding")["points"]
    assert [143.07, -10.05, "TMYx.2009-2023", "2009-2023", "published", None] in sites
    assert [-157.8, 21.3, "TMY3", None, "approximate_locality", None] in sites


def test_era5_extent_uses_catalog_footprint_and_names_documented_members(tmp_path):
    era5 = _layer(catalog_map(_bundle(), tmp_path), "era5")
    assert era5["bounds"] == [-180.0, -89.0, 180.0, 89.0]
    assert era5["members"] == ["cds/reanalysis-era5-single-levels", "openmeteo/era5"]


def test_pvgis_envelope_is_approximate_with_its_saved_probe(tmp_path):
    pvgis = _layer(catalog_map(_bundle(), tmp_path), "pvgis")
    assert len(pvgis["polygon"]) == 22 and pvgis["polygon"][0] == pvgis["polygon"][-1]
    assert pvgis["probes"] == [[-0.128, 51.507]]
    assert "approximate" in pvgis["caveat"].lower()


def test_nsrdb_mask_becomes_merged_cells_and_other_products_stay_unmapped(tmp_path):
    _mask(tmp_path, [[400, 100], [400, 101], [400, 102], [401, 100]])
    result = catalog_map(_bundle(), tmp_path)
    nsrdb = _layer(result, "nsrdb")
    assert nsrdb["rects"] == [[-155.0, 10.0, -154.25, 10.25], [-155.0, 10.25, -154.75, 10.5]]
    assert nsrdb["source"]["selector"] == "tdy-2023"
    assert {"provider": "nsrdb", "dataset": "nsrdb-GOES-aggregated-v4-0-0"} in [
        {key: item[key] for key in ("provider", "dataset")} for item in result["unmapped"]]


@pytest.mark.parametrize("problem", [{"stale": True}, {"tamper": True}])
def test_stale_or_mismatched_nsrdb_mask_is_not_drawn(tmp_path, problem):
    _mask(tmp_path, [[400, 100]], **problem)
    result = catalog_map(_bundle(), tmp_path)
    assert all(layer["id"] != "nsrdb" for layer in result["layers"])
    assert any(item["dataset"] == "nsrdb-GOES-tmy-v4-0-0" for item in result["unmapped"])


def test_merge_cell_rows_joins_only_adjacent_columns():
    assert merge_cell_rows([[0, 0], [0, 1], [0, 3]], 1.0) == [
        [-180.0, -90.0, -178.0, -89.0], [-177.0, -90.0, -176.0, -89.0]]


def test_service_serves_active_catalog_map(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    staged = store.stage(_bundle())
    store.activate(staged.generation_id)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"), catalog_store=store)
    result = service.catalog_map()
    assert result["snapshot"]["generation_id"] == staged.generation_id
    assert [layer["id"] for layer in result["layers"]] == ["noaa", "onebuilding", "pvgis", "era5"]


def test_station_names_come_from_site_records_and_onebuilding_file_names(tmp_path):
    from openepw.availability.map_layers import onebuilding_station_name

    bundle = _bundle()
    bundle.sites[0].name = "BOSTON LOGAN INTL"
    bundle.products[1].native_product_id = ("https://climate.onebuilding.org/WMO_Region_5_Southwest_Pacific/"
                                            "AUS_Australia/QLD_Queensland/AUS_QLD_Coconut.Island.AP.941820_TMYx.2009-2023.zip")
    result = catalog_map(bundle, tmp_path)
    assert _layer(result, "noaa")["points"][0][4] == "BOSTON LOGAN INTL"
    names = {point[2]: point[5] for point in _layer(result, "onebuilding")["points"]}
    assert names["TMYx.2009-2023"] == "Coconut Island AP"
    assert names["TMY3"] is None
    assert onebuilding_station_name("https://x/FRA_Paris.Orly.071490_TMYx.zip") == "Paris Orly"
    assert onebuilding_station_name("https://x/USA_TX_Bowie.Muni.AP.A05735_TMYx.2009-2023.zip") == "Bowie Muni AP"
    assert onebuilding_station_name("not a onebuilding url") is None


def test_stage1_import_keeps_noaa_station_names():
    from openepw.availability.stage1 import _noaa

    inventories = {"noaa-history": {"sites": [{"id": "72509014739", "name": "BOSTON LOGAN INTL", "lat": 42.36,
                                                "lon": -71.01, "start": "1936-01-01", "end": "2025-08-28"}]},
                   "noaa-inventory-authorized": {"station_years": {"72509014739": {"2018": [1] * 12}}}}
    _, sites, _ = _noaa(inventories, {"noaa-history", "noaa-inventory-authorized"})
    assert sites[0].name == "BOSTON LOGAN INTL"
