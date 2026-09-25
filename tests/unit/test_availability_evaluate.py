"""Eligibility distinguishes positive inventory membership from unknown coverage."""

from datetime import datetime, timezone

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    CatalogSnapshotRef,
    EvidenceRef,
    FutureAvailabilityQuery,
    FutureWindowScope,
    ProductRecord,
    SiteRecord,
    TMYReferenceScope,
    WeatherAvailabilityQuery,
)
from openepw.availability.evaluate import evaluate
from openepw.availability.store import CatalogView
from openepw.models import Location, WeatherRequest

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def _view(bundle):
    return CatalogView(CatalogSnapshotRef(generation_id="synthetic", created_at=NOW), bundle)


def _noaa_bundle():
    return CatalogBundle(
        evidence=[EvidenceRef(id="noaa-counts", sha256="a" * 64, retrieved_at=NOW,
                              basis="inventory")],
        products=[ProductRecord(id="noaa:isd", provider="noaa", dataset="isd",
                                spatial_kind="station", temporal_kind="actual",
                                adapter_variables=["dry_bulb", "wind_speed"],
                                evidence_ids=["noaa-counts"])],
        sites=[SiteRecord(id="A00002", product_id="noaa:isd", lat=42, lon=-76,
                          position_status="published", station_identity_status="verified",
                          evidence_ids=["noaa-counts"])],
        entries=[AvailabilityEntry(id="years", product_id="noaa:isd", site_id="A00002",
                                   scope=ActualScope(years=[2024], month_counts={2024: {1: 44}}),
                                   evidence_basis="inventory", evidence_ids=["noaa-counts"])],
    )


def test_sparse_noaa_year_is_unknown_not_excluded():
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2023], providers=["noaa"])
    result = evaluate(WeatherAvailabilityQuery(request=request), _view(_noaa_bundle()))
    assert result.options[0].eligibility.status == "unknown"
    assert "YEAR_NOT_LISTED_IN_DATED_INVENTORY" in result.options[0].eligibility.unknowns


def test_listed_year_supports_attempt_and_duplicate_inputs_remain_distinct():
    location = Location(id="same", lat=42, lon=-76)
    request = WeatherRequest(locations=[location, location], years=[2024], providers=["noaa"])
    result = evaluate(WeatherAvailabilityQuery(request=request), _view(_noaa_bundle()))
    assert len(result.locations) == 2
    assert len(result.options) == 2
    assert result.options[0].id != result.options[1].id
    assert {o.site.id for o in result.options} == {"A00002"}
    assert all(o.eligibility.status == "supported" for o in result.options)
    assert all(o.eligibility.health == "unknown" for o in result.options)


def test_explicitly_required_missing_variable_excludes():
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024], providers=["noaa"])
    result = evaluate(WeatherAvailabilityQuery(request=request, required_variables=["ghi"]),
                      _view(_noaa_bundle()))
    assert result.options[0].eligibility.status == "excluded"
    assert "ghi" in result.options[0].missing_required_variables


def test_oedi_exact_scenario_window_and_cmip6_unknown_window():
    bundle = CatalogBundle(
        evidence=[EvidenceRef(id="oedi", sha256="b" * 64, retrieved_at=NOW,
                              basis="inventory")],
        products=[ProductRecord(id="oedi:rcp45", provider="oedi", dataset="hourly",
                                spatial_kind="station", temporal_kind="future_window",
                                evidence_ids=["oedi"]),
                  ProductRecord(id="cmip6:test", provider="cmip6", dataset="monthly",
                                spatial_kind="grid", temporal_kind="future_window",
                                evidence_ids=["oedi"])],
        sites=[SiteRecord(id="G1", product_id="oedi:rcp45", lat=42, lon=-76,
                          position_status="published")],
        entries=[AvailabilityEntry(id="oedi-window", product_id="oedi:rcp45", site_id="G1",
                                   scope=FutureWindowScope(start_year=2045, end_year=2054,
                                                           scenario="rcp45",
                                                           listed_years=list(range(2045, 2055))),
                                   evidence_basis="inventory", evidence_ids=["oedi"]),
                 AvailabilityEntry(id="cmip6-combo", product_id="cmip6:test",
                                   scope=FutureWindowScope(scenario="ssp245"),
                                   evidence_basis="inventory", evidence_ids=["oedi"])],
    )
    query = FutureAvailabilityQuery(location=Location(lat=42, lon=-76),
                                    method="climate_profile", scenario="rcp45",
                                    climate_period=(2045, 2054))
    result = evaluate(query, _view(bundle))
    assert next(o for o in result.options if o.product.provider == "oedi").eligibility.status == (
        "supported")
    assert next(o for o in result.options if o.product.provider == "cmip6").eligibility.status == (
        "excluded")
    cmip = evaluate(FutureAvailabilityQuery(location=Location(lat=42, lon=-76),
                                           method="morph", scenario="ssp245",
                                           climate_period=(2045, 2054)), _view(bundle))
    assert next(o for o in cmip.options if o.product.provider == "cmip6").eligibility.status == (
        "unknown")


def test_large_published_catalog_limits_nearest_options_without_losing_explicit_choice():
    products = [ProductRecord(id=f"onebuilding:{n}", provider="onebuilding",
                              dataset="published_epw", native_product_id=f"product-{n}",
                              spatial_kind="station", temporal_kind="tmy_reference")
                for n in range(25)]
    sites = [SiteRecord(id=f"site-{n}", product_id=f"onebuilding:{n}",
                        lat=42 + n * .01, lon=-76, position_status="published")
             for n in range(25)]
    entries = [AvailabilityEntry(id=f"entry-{n}", product_id=f"onebuilding:{n}",
                                 site_id=f"site-{n}",
                                 scope=TMYReferenceScope(product_label="TMYx"),
                                 evidence_basis="inventory") for n in range(25)]
    view = _view(CatalogBundle(products=products, sites=sites, entries=entries))
    request = WeatherRequest(locations=Location(lat=42, lon=-76), product="tmyx",
                             providers=["onebuilding"])
    result = evaluate(WeatherAvailabilityQuery(request=request), view)
    assert len(result.options) == 20
    assert result.options[0].site.id == "site-0"
    explicit = request.model_copy(update={"product_id": "product-24"})
    chosen = evaluate(WeatherAvailabilityQuery(request=explicit), view)
    assert [o.site.id for o in chosen.options] == ["site-24"]


def test_point_probe_year_does_not_transfer_between_locations():
    product = ProductRecord(id="nsrdb:aggregate:v4", provider="nsrdb", dataset="aggregate",
                            spatial_kind="grid", temporal_kind="actual",
                            adapter_variables=["dry_bulb"])
    entries = [AvailabilityEntry(id="ithaca", product_id=product.id,
                                 scope=ActualScope(years=[2024]), evidence_basis="targeted_probe",
                                 probe_location=Location(lat=42.44, lon=-76.5)),
               AvailabilityEntry(id="phoenix", product_id=product.id,
                                 scope=ActualScope(years=[2025]), evidence_basis="targeted_probe",
                                 probe_location=Location(lat=33.45, lon=-112.07))]
    view = _view(CatalogBundle(products=[product], entries=entries))
    request = WeatherRequest(locations=Location(lat=42.44, lon=-76.5), years=[2025],
                             providers=["nsrdb"])
    result = evaluate(WeatherAvailabilityQuery(request=request), view)
    assert result.options[0].eligibility.status == "unknown"
    assert "YEAR_NOT_LISTED_IN_DATED_INVENTORY" in result.options[0].eligibility.unknowns


def test_stale_future_directory_cannot_exclude_new_window():
    product = ProductRecord(id="oedi:rcp45", provider="oedi", dataset="hourly",
                            spatial_kind="station", temporal_kind="future_window",
                            evidence_ids=["oedi-directory"])
    site = SiteRecord(id="G1", product_id=product.id, lat=42, lon=-76)
    entry = AvailabilityEntry(id="known-window", product_id=product.id, site_id="G1",
                              scope=FutureWindowScope(start_year=2045, end_year=2054,
                                                      scenario="rcp45"),
                              evidence_basis="inventory", evidence_ids=["oedi-directory"])
    view = _view(CatalogBundle(products=[product], sites=[site], entries=[entry]))
    view.snapshot.stale_sources = ["oedi-directory"]
    query = FutureAvailabilityQuery(location=Location(lat=42, lon=-76),
                                    method="climate_profile", scenario="rcp45",
                                    climate_period=(2035, 2044))
    result = evaluate(query, view)
    assert result.options[0].eligibility.status == "unknown"
    assert "STALE_SOURCE_EVIDENCE" in result.options[0].eligibility.unknowns


def test_documented_history_start_does_not_promise_future_calendar_year():
    product = ProductRecord(id="openmeteo:era5", provider="openmeteo", dataset="era5",
                            spatial_kind="grid", temporal_kind="actual",
                            adapter_variables=["dry_bulb"])
    entry = AvailabilityEntry(id="documented", product_id=product.id,
                              scope=ActualScope(operating_start=datetime(1940, 1, 1).date()),
                              evidence_basis="documentation")
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2100],
                             providers=["openmeteo"])
    result = evaluate(WeatherAvailabilityQuery(request=request),
                      _view(CatalogBundle(products=[product], entries=[entry])))
    assert result.options[0].eligibility.status == "unknown"
    assert "MOVING_END_UNVERIFIED" in result.options[0].eligibility.unknowns


def test_unknown_elevation_cannot_satisfy_user_limit():
    bundle = _noaa_bundle()
    request = WeatherRequest(locations=Location(lat=42, lon=-76, elevation=300),
                             years=[2024], providers=["noaa"])
    result = evaluate(WeatherAvailabilityQuery(request=request,
                                               max_elevation_delta_m=100), _view(bundle))
    assert result.options[0].eligibility.status == "unknown"
    assert "ELEVATION_DIFFERENCE_UNKNOWN" in result.options[0].eligibility.unknowns
