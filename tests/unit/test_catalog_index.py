"""A stored catalog generation is assessed and mapped from a compact index (OneBuilding and NOAA
records read from SQLite on demand) with exactly the answers of the catalog held in memory."""

import json

import pytest
from test_catalog_package import full_bundle

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    FutureAvailabilityQuery,
    ProductRecord,
    SiteRecord,
    TMYReferenceScope,
    WeatherAvailabilityQuery,
)
from openepw.availability.catalog_index import CatalogIndex, StoreCatalogIndex
from openepw.availability.evaluate import evaluate
from openepw.availability.map_layers import catalog_map
from openepw.availability.store import CatalogStore, CatalogView
from openepw.models import Location, WeatherRequest


def _bundle():
    bundle = full_bundle()
    for index in range(30):                            # published files around Ithaca
        product_id, site_id = f"onebuilding:{index + 100}", f"onebuilding-site:{index + 100}"
        url = f"https://climate.onebuilding.org/USA/NY/Place.{index}.7250{index:02d}_TMYx.2009-2023.zip"
        bundle.products.append(ProductRecord(
            id=product_id, provider="onebuilding", dataset="OneBuilding published EPW", native_product_id=url,
            spatial_kind="station", temporal_kind="tmy_reference", adapter_variables=["dry_bulb"],
            evidence_ids=["doc"]))
        status = "approximate_locality" if index == 3 else "published"
        position = (None, None) if index == 4 else (42.0 + index * 0.05, -76.5 + index * 0.03)
        bundle.sites.append(SiteRecord(id=site_id, product_id=product_id, lat=position[0], lon=position[1],
                                       position_status=status, evidence_ids=["doc"]))
        bundle.entries.append(AvailabilityEntry(
            id=f"{product_id}:published", product_id=product_id, site_id=site_id,
            scope=TMYReferenceScope(start_year=2009, end_year=2023, product_label="TMYx.2009-2023"),
            evidence_ids=["doc"], evidence_basis="inventory"))
    for index in range(12):                            # NOAA stations, some without listed years
        site_id = f"72{index:04d}"
        bundle.sites.append(SiteRecord(id=site_id, product_id="noaa:isd", name=f"STATION {index}",
                                       lat=42.2 + index * 0.1, lon=-76.4, position_status="published",
                                       evidence_ids=["noaa-history"]))
        bundle.entries.append(AvailabilityEntry(
            id=f"noaa:isd:{site_id}:years", product_id="noaa:isd", site_id=site_id,
            scope=ActualScope(years=[2018] if index % 2 else [2016], month_counts={2018: {1: 700}}),
            evidence_ids=["noaa-history"], evidence_basis="inventory"))
    return bundle


def _dump(result):
    return json.dumps([item.model_dump(mode="json") for item in (*result.options, *result.issues)],
                      sort_keys=True)


QUERIES = [
    WeatherAvailabilityQuery(request=WeatherRequest(locations=Location(lat=42.44, lon=-76.5), years=[2018])),
    WeatherAvailabilityQuery(request=WeatherRequest(locations=Location(lat=42.44, lon=-76.5), product="tmy")),
    WeatherAvailabilityQuery(request=WeatherRequest(locations=[Location(lat=42.36, lon=-71.0),
                                                               Location(lat=-10.0, lon=143.0)], years=[2019])),
    WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=40, lon=-75), product="tmy",
        product_id="https://climate.onebuilding.org/USA/NY/Place.7.725007_TMYx.2009-2023.zip")),
    WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=40, lon=-75), product="tmy", product_id="USA/NY/Place.8.725008_TMYx.2009-2023.zip")),
    WeatherAvailabilityQuery(request=WeatherRequest(locations=Location(lat=40, lon=-75), product="tmy",
                                                    product_id="onebuilding:109")),
    WeatherAvailabilityQuery(request=WeatherRequest(locations=Location(lat=42.36, lon=-71.0), years=[2018],
                                                    product_id="72509014739", providers=["noaa"])),
    FutureAvailabilityQuery(location=Location(lat=42, lon=-76), method="morph", scenario="ssp126",
                            climate_period=(2041, 2060)),
]


@pytest.mark.parametrize("query", QUERIES)
def test_the_stored_index_answers_like_the_catalog_in_memory(tmp_path, query):
    store = CatalogStore(tmp_path)
    snapshot = store.stage(_bundle())
    store.activate(snapshot.generation_id)
    stored = store.active()
    assert isinstance(stored.index, StoreCatalogIndex)
    held = CatalogView(stored.snapshot, store.bundle(snapshot.generation_id))
    assert _dump(evaluate(query, stored)) == _dump(evaluate(query, held))


def test_the_stored_index_maps_and_lists_like_the_catalog_in_memory(tmp_path):
    store = CatalogStore(tmp_path)
    snapshot = store.stage(_bundle())
    store.activate(snapshot.generation_id)
    stored, held = store.active().index, CatalogIndex(store.bundle(snapshot.generation_id))
    assert json.dumps(catalog_map(stored, tmp_path), sort_keys=True, default=str) == \
        json.dumps(catalog_map(held, tmp_path), sort_keys=True, default=str)
    assert stored.providers() == held.providers()
    assert {(p.provider, p.dataset) for p in stored.scope_products()} == \
        {(p.provider, p.dataset) for p in held.scope_products()}
    # No published file and no NOAA station sits in memory as a full record.
    assert sum(product.provider == "onebuilding" for product in stored._products) == 0
    assert "noaa:isd" not in stored._sites
