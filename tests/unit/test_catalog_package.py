"""The catalog as a public CSV data package: export, import, verify."""

import hashlib
import json
from datetime import date, datetime, timezone

import pytest

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    FutureWindowScope,
    ProductRecord,
    ReviewAnnotation,
    SiteRecord,
    TMYReferenceScope,
)
from openepw.availability.package import PackageError, export_package, load_package
from openepw.models import Location

WHEN = datetime(2026, 9, 23, 12, 30, tzinfo=timezone.utc)


def full_bundle() -> CatalogBundle:
    evidence = [
        EvidenceRef(id="noaa-history", source_url="https://example.org/isd-history.csv", sha256="a" * 64,
                    retrieved_at=WHEN, basis="inventory", etag='"abc"', last_modified="Tue, 22 Sep 2026"),
        EvidenceRef(id="doc", sha256="b" * 64, retrieved_at=WHEN, checked_at=WHEN, basis="documentation",
                    published_at=date(2025, 1, 2), terms="CC BY 4.0", attribution="Example", scope="global"),
    ]
    products = [
        ProductRecord(id="noaa:isd", provider="noaa", dataset="ISD global-hourly", spatial_kind="station",
                      temporal_kind="actual", source_variables=["dry_bulb", "wind_speed"],
                      adapter_variables=["dry_bulb"], evidence_ids=["noaa-history"]),
        ProductRecord(id="cds:era5", provider="cds", dataset="reanalysis-era5-single-levels", spatial_kind="grid",
                      temporal_kind="actual", footprint=(0.0, -89.0, 360.0, 89.0), longitude_convention="0_360",
                      access_requirements=["OPENEPW_CDS_KEY", "accepted_terms"], delivered_resolution_minutes=60,
                      license_effective="CC BY 4.0", license_history="2019: licence text", evidence_ids=["doc"]),
        ProductRecord(id="onebuilding:1", provider="onebuilding", dataset="OneBuilding published EPW",
                      native_product_id="https://climate.onebuilding.org/X_TMYx.2009-2023.zip",
                      spatial_kind="station", temporal_kind="tmy_reference", adapter_supported=False,
                      version="v1", citation="cite, with \"quotes\"; and a semicolon", evidence_ids=["doc"]),
        ProductRecord(id="pvgis:tmy", provider="pvgis", dataset="PVGIS TMY", spatial_kind="grid",
                      temporal_kind="tmy_reference", native_resolution_minutes=60, evidence_ids=["doc"]),
        ProductRecord(id="cmip6:m:ssp126", provider="cmip6", dataset="Pangeo CMIP6 Amon", spatial_kind="grid",
                      temporal_kind="future_window", evidence_ids=["doc"]),
    ]
    sites = [
        SiteRecord(id="72509014739", product_id="noaa:isd", name="BOSTON LOGAN, MA", lat=42.361, lon=-71.01,
                   elevation_m=3.7, position_status="published", station_identity_status="verified",
                   candidate_station_ids=["72509014739"], operating_start=date(1943, 1, 1),
                   operating_end=date(2026, 9, 20), evidence_ids=["noaa-history"]),
        SiteRecord(id="onebuilding-site:1", product_id="onebuilding:1", lat=-10.051, lon=143.069,
                   position_status="approximate_locality", evidence_ids=["doc"]),
        SiteRecord(id="nowhere", product_id="noaa:isd", evidence_ids=[]),
    ]
    entries = [
        AvailabilityEntry(id="noaa:isd:72509014739:years", product_id="noaa:isd", site_id="72509014739",
                          scope=ActualScope(years=[2018, 2019], month_counts={
                              2018: {month: 700 + month for month in range(1, 13)},
                              2019: {1: 0, 2: 5, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0, 11: 0, 12: 9}}),
                          evidence_ids=["noaa-history"], evidence_basis="inventory"),
        AvailabilityEntry(id="cds:era5:interval", product_id="cds:era5",
                          scope=ActualScope(operating_start=date(1940, 1, 1), operating_end=date(2026, 9, 17)),
                          evidence_ids=["doc"], evidence_basis="documentation", exclusions=["NO_DNI"],
                          weather_complete=True, variables=["dry_bulb"]),
        AvailabilityEntry(id="onebuilding:1:published", product_id="onebuilding:1", site_id="onebuilding-site:1",
                          scope=TMYReferenceScope(start_year=2009, end_year=2023, product_label="TMYx.2009-2023"),
                          evidence_ids=["doc"], evidence_basis="inventory", source_etag='"x"'),
        AvailabilityEntry(id="pvgis:tmy:london", product_id="pvgis:tmy",
                          scope=TMYReferenceScope(start_year=2005, end_year=2023, product_label="PVGIS London",
                                                  selected_month_years={1: 2016, 2: 2007}),
                          evidence_ids=["doc"], evidence_basis="targeted_probe",
                          probe_location=Location(lat=51.507, lon=-0.128)),
        AvailabilityEntry(id="cmip6:m:ssp126:catalog", product_id="cmip6:m:ssp126",
                          scope=FutureWindowScope(scenario="ssp126", model="M", member="r1i1p1f1", grid="gn",
                                                  start_year=2040, end_year=2069, listed_years=[2040, 2041]),
                          evidence_ids=["doc"], evidence_basis="inventory", weather_complete=False),
    ]
    reviews = [ReviewAnnotation(product_id="onebuilding:1", catalog_url="https://climate.onebuilding.org/X.zip",
                                status="approximate_locality", rationale="Owner-accepted, see notes; \"quoted\"",
                                accepted_on=date(2026, 9, 24), evidence_ids=["doc"],
                                source_checksums={"doc": "b" * 64}, alternate_url="https://example.org/alt",
                                original_position_status="published", epw_coordinates_verified=True)]
    return CatalogBundle(evidence=evidence, products=products, sites=sites, entries=entries, reviews=reviews)


def footprints(root):
    mask = root / "nsrdb" / "nsrdb-GOES-tmy-v4-0-0" / "tdy-2023"
    mask.mkdir(parents=True)
    (mask / "manifest.json").write_text('{"cells": 2}', encoding="utf-8")
    (mask / "mask.json").write_text('{"rects": [[0, 0, 1, 1]]}', encoding="utf-8")
    return root


def canonical(bundle: CatalogBundle) -> dict:
    return {name: sorted((record.model_dump(mode="json") for record in getattr(bundle, name)),
                         key=lambda item: item.get("id") or item.get("catalog_url"))
            for name in ("evidence", "products", "sites", "entries", "reviews")}


def test_export_then_import_gives_back_the_same_catalog(tmp_path):
    original = full_bundle()
    package = export_package(original, tmp_path / "package", footprints(tmp_path / "footprints"),
                             name="weather-availability-catalog", version="2026.09.27")
    loaded = load_package(package)
    assert canonical(loaded.bundle) == canonical(original)
    assert loaded.footprints == {"nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/manifest.json": b'{"cells": 2}',
                                 "nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/mask.json": b'{"rects": [[0, 0, 1, 1]]}'}


def test_the_package_is_described_split_by_provider_and_reproducible(tmp_path):
    first = export_package(full_bundle(), tmp_path / "a", footprints(tmp_path / "fa"), name="c", version="1")
    second = export_package(full_bundle(), tmp_path / "b", footprints(tmp_path / "fb"), name="c", version="1")
    assert first.read_bytes() == second.read_bytes()                            # byte-identical exports
    descriptor = json.loads(first.read_text(encoding="utf-8"))
    paths = {resource["path"] for resource in descriptor["resources"]}
    assert {"data/sources.csv", "data/reviews.csv", "data/noaa/products.csv", "data/noaa/sites.csv",
            "data/noaa/entries.csv", "data/noaa/month-counts.csv", "data/onebuilding/products.csv",
            "data/footprints/nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/mask.json"} <= paths
    for resource in descriptor["resources"]:
        data = (first.parent / resource["path"]).read_bytes()
        assert resource["bytes"] == len(data) and resource["hash"] == "sha256:" + hashlib.sha256(data).hexdigest()
        if resource["path"].endswith(".csv"):
            header = data.decode("utf-8").splitlines()[0].split(",")
            assert header == [field["name"] for field in resource["schema"]["fields"]]
    months = (first.parent / "data/noaa/month-counts.csv").read_text(encoding="utf-8").splitlines()
    assert months[0] == "entry_id,year,m01,m02,m03,m04,m05,m06,m07,m08,m09,m10,m11,m12"
    assert months[1] == "noaa:isd:72509014739:years,2018,701,702,703,704,705,706,707,708,709,710,711,712"


def test_a_changed_file_is_refused(tmp_path):
    package = export_package(full_bundle(), tmp_path / "p", footprints(tmp_path / "f"), name="c", version="1")
    sites = package.parent / "data/noaa/sites.csv"
    sites.write_bytes(sites.read_bytes().replace(b"BOSTON", b"BOSTOM"))
    with pytest.raises(PackageError, match="sites.csv"):
        load_package(package)


def test_the_cli_exports_the_active_catalog_and_imports_it_elsewhere(tmp_path, capsys):
    from openepw.availability.store import CatalogStore
    from openepw.cli.main import main

    source = tmp_path / "source"
    store = CatalogStore(source / "catalog")
    store.activate(store.stage(full_bundle()).generation_id)
    footprints(source / "footprints")
    metadata = tmp_path / "meta.json"
    metadata.write_text('{"title": "Weather availability catalog"}', encoding="utf-8")
    assert main(["--data-root", str(source), "catalog", "export", "--out", str(tmp_path / "pkg"),
                 "--package-version", "2026.09.28", "--metadata", str(metadata)]) == 0
    exported = json.loads(capsys.readouterr().out)
    descriptor = tmp_path / "pkg" / "datapackage.json"
    assert exported["sha256"] == hashlib.sha256(descriptor.read_bytes()).hexdigest()
    assert json.loads(descriptor.read_text(encoding="utf-8"))["title"] == "Weather availability catalog"

    target = tmp_path / "target"
    assert main(["--data-root", str(target), "catalog", "import", "--from-package", str(descriptor)]) == 0
    assert json.loads(capsys.readouterr().out)["entry_count"] == 5
    assert canonical(CatalogStore(target / "catalog").active().bundle) == canonical(full_bundle())
    assert (target / "footprints/nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/manifest.json").is_file()

    (tmp_path / "pkg/data/sources.csv").write_text("changed", encoding="utf-8")
    assert main(["--data-root", str(target), "catalog", "import", "--from-package", str(descriptor)]) == 2
    assert "sources.csv" in capsys.readouterr().out
