"""The canonical service shares catalog decisions with existing discovery."""

from datetime import datetime, timezone

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    FutureAvailabilityQuery,
    ProductRecord,
    SiteRecord,
    TMYReferenceScope,
    WeatherAvailabilityQuery,
)
from openepw.availability.store import CatalogStore
from openepw.config import RuntimeConfig
from openepw.models import Candidate, Location, SourceRef, WeatherPlan, WeatherRequest
from openepw.service import WeatherService


class ForbiddenHttp:
    def get(self, *args, **kwargs):
        raise AssertionError("catalog-supported discovery called provider HTTP")

    def get_json(self, *args, **kwargs):
        raise AssertionError("catalog-supported discovery called provider HTTP")


def _catalog(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    bundle = CatalogBundle(
        evidence=[EvidenceRef(id="noaa-counts", sha256="a" * 64,
                              retrieved_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
                              basis="inventory")],
        products=[ProductRecord(id="noaa:isd", provider="noaa", dataset="isd",
                                spatial_kind="station", temporal_kind="actual",
                                adapter_variables=["dry_bulb"], evidence_ids=["noaa-counts"])],
        sites=[SiteRecord(id="A00002", product_id="noaa:isd", lat=42, lon=-76,
                          position_status="published", station_identity_status="verified")],
        entries=[AvailabilityEntry(id="listed", product_id="noaa:isd", site_id="A00002",
                                   scope=ActualScope(years=[2024]), evidence_basis="inventory",
                                   evidence_ids=["noaa-counts"])],
    )
    staged = store.stage(bundle)
    store.activate(staged.generation_id)
    return store


def test_fresh_catalog_avoids_repeated_noaa_inventory_http(tmp_path):
    store = _catalog(tmp_path)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=store)
    point = Location(id="repeat", lat=42, lon=-76)
    request = WeatherRequest(locations=[point] * 100, years=[2024], providers=["noaa"])
    discovery = service.discover(request)
    assert discovery.availability is not None
    assert len(discovery.availability.locations) == 100
    assert len({option.id for option in discovery.availability.options}) == 100
    assert any(candidate.source.provider == "noaa" for candidate in discovery.candidates)
    assert len(discovery.selected_candidate_ids) == 1


def test_broad_assessment_bounds_options_per_occurrence(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    bundle = CatalogBundle(
        products=[ProductRecord(id=f"openmeteo:{i}", provider="openmeteo",
                                dataset=f"synthetic-{i}", spatial_kind="grid",
                                temporal_kind="actual", adapter_variables=["dry_bulb"])
                  for i in range(60)],
        entries=[AvailabilityEntry(id=f"entry:{i}", product_id=f"openmeteo:{i}",
                                   scope=ActualScope(years=[2024]),
                                   evidence_basis="inventory") for i in range(60)],
    )
    store.activate(store.stage(bundle).generation_id)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=store)
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=[Location(id="a", lat=42, lon=-76),
                   Location(id="b", lat=42, lon=-76)], years=[2024],
        providers=["openmeteo"]))
    result = service.assess_availability(query)
    assert len(result.locations) == 2
    assert len(result.options) == 100
    assert all(len(loc.ranked_option_ids) == 50 for loc in result.locations)
    assert any(issue.code == "OPTIONS_TRUNCATED" for issue in result.issues)


def test_assessment_without_catalog_returns_typed_unknown(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=CatalogStore(tmp_path / "empty"))
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2024], providers=["noaa"]))
    result = service.assess_availability(query)
    assert result.options[0].eligibility.status == "unknown"
    assert result.issues[0].code == "CATALOG_UNAVAILABLE"


def test_future_capability_does_not_read_baseline_file(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=CatalogStore(tmp_path / "empty"))
    query = FutureAvailabilityQuery(location=Location(lat=42, lon=-76), method="morph",
                                    scenario="ssp245", climate_period=(2041, 2070))
    result = service.assess_availability(query)
    assert result.options[0].product.provider == "cmip6"
    assert result.options[0].eligibility.status == "unknown"


def test_catalog_product_identity_reaches_static_provider_discovery(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    bundle = CatalogBundle(
        products=[ProductRecord(id=f"openmeteo:{dataset}", provider="openmeteo",
                                dataset=dataset, spatial_kind="grid", temporal_kind="actual",
                                adapter_variables=["dry_bulb"])
                  for dataset in ("era5", "era5_land")],
        entries=[AvailabilityEntry(id=f"{dataset}:period", product_id=f"openmeteo:{dataset}",
                                   scope=ActualScope(operating_start=datetime(1940, 1, 1).date()),
                                   evidence_basis="documentation")
                 for dataset in ("era5", "era5_land")],
    )
    staged = store.stage(bundle)
    store.activate(staged.generation_id)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=store)
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024],
                             providers=["openmeteo"])
    result = service.discover(request)
    assert {c.source.dataset for c in result.candidates} == {"era5", "era5_land"}


def test_explicit_published_path_uses_catalog_without_http(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    url = "https://climate.onebuilding.org/USA/file.zip"
    bundle = CatalogBundle(
        products=[ProductRecord(id="onebuilding:file", provider="onebuilding",
                                dataset="OneBuilding published EPW", native_product_id=url,
                                spatial_kind="station", temporal_kind="tmy_reference",
                                adapter_variables=["dry_bulb"])],
        sites=[SiteRecord(id="published-site", product_id="onebuilding:file",
                          lat=42, lon=-76, position_status="published")],
        entries=[AvailabilityEntry(id="published", product_id="onebuilding:file",
                                   site_id="published-site",
                                   scope=TMYReferenceScope(product_label="TMYx"),
                                   evidence_basis="inventory")],
    )
    staged = store.stage(bundle)
    store.activate(staged.generation_id)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=store)
    request = WeatherRequest(locations=Location(lat=42, lon=-76), product="tmyx",
                             providers=["onebuilding"], product_id="USA/file.zip")
    result = service.discover(request)
    assert result.candidates[0].product_id == "USA/file.zip"


def test_unknown_point_discovery_is_coalesced_for_duplicate_inputs(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    product = ProductRecord(id="nsrdb:aggregate:v4", provider="nsrdb", dataset="aggregate",
                            spatial_kind="grid", temporal_kind="actual",
                            adapter_variables=["dry_bulb"])
    bundle = CatalogBundle(products=[product], entries=[AvailabilityEntry(
        id="other-point", product_id=product.id, scope=ActualScope(years=[2024]),
        evidence_basis="targeted_probe", probe_location=Location(lat=33, lon=-112))])
    staged = store.stage(bundle)
    store.activate(staged.generation_id)

    class CountingProvider:
        name = "nsrdb"

        def __init__(self):
            self.calls = 0

        def discover(self, request, location, http):
            self.calls += 1
            return [Candidate(id=f"nsrdb:live:{location.key}", location_id=location.key,
                              source=SourceRef(provider="nsrdb", dataset="aggregate"))]

    provider = CountingProvider()
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), providers=[provider], catalog_store=store)
    point = Location(id="same", lat=42, lon=-76)
    result = service.discover(WeatherRequest(locations=[point] * 100, years=[2024],
                                             providers=["nsrdb"]))
    assert provider.calls == 1
    assert len(result.availability.locations) == 100


def test_top_level_python_availability_api(tmp_path):
    from openepw import assess_availability

    query = FutureAvailabilityQuery(location=Location(lat=42, lon=-76), method="morph",
                                    scenario="ssp245", climate_period=(2041, 2070))
    result = assess_availability(query, config=RuntimeConfig(data_root=tmp_path))
    assert result.options[0].eligibility.status == "unknown"


def test_catalog_discovery_keeps_existing_plan_round_trip(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp(), catalog_store=_catalog(tmp_path))
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024],
                             providers=["noaa"])
    plan = service.plan(request)
    restored = WeatherPlan.model_validate_json(plan.model_dump_json())
    assert restored.plan_hash == plan.plan_hash
    assert len(restored.outputs) == 1
