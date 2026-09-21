import pytest
from pydantic import ValidationError

from openepw.models import FutureRequest, Location, WeatherPlan, WeatherRequest


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, -181), (float("nan"), 0)])
def test_invalid_coordinates_rejected(lat, lon):
    with pytest.raises(ValidationError):
        Location(lat=lat, lon=lon)


def test_request_date_and_product_conflicts():
    for extra in [
        dict(product="tmy", years=[2024]),
        dict(years=[2024], start="2024-01-01", end="2024-01-02"),
        dict(schema_version="2"),
    ]:
        with pytest.raises(ValidationError):
            WeatherRequest(locations=[Location(lat=42, lon=-76)], **extra)


def test_dataset_selections_are_unique_and_cannot_mix_with_hybrid():
    base = dict(locations=Location(lat=42, lon=-76), years=[2024])
    request = WeatherRequest(
        **base,
        dataset_selections=[
            {"provider": "era5", "dataset": "era5-single-levels"},
            {"provider": "pvgis", "dataset": "sarah3", "product_id": "tmy"},
        ],
    )
    assert [selection.provider for selection in request.dataset_selections] == ["era5", "pvgis"]

    with pytest.raises(ValidationError, match="Duplicate dataset selection"):
        WeatherRequest(
            **base,
            dataset_selections=[
                {"provider": "era5", "dataset": "era5-single-levels"},
                {"provider": "era5", "dataset": "era5-single-levels"},
            ],
        )

    with pytest.raises(ValidationError, match="hybrid"):
        WeatherRequest(
            **base,
            dataset_selections=[{"provider": "era5", "dataset": "era5-single-levels"}],
            hybrid_policy={"enabled": True, "assignments": {"dry_bulb": "era5"}},
        )


def test_skip_feb_29_requires_actual_year_request():
    for extra in [
        dict(product="tmy", skip_feb_29=True),
        dict(start="2024-01-01", end="2024-12-31", skip_feb_29=True),
    ]:
        with pytest.raises(ValidationError):
            WeatherRequest(locations=Location(lat=42, lon=-76), **extra)

    request = WeatherRequest(
        locations=Location(lat=42, lon=-76),
        product="amy",
        years=[2024],
        skip_feb_29=True,
    )
    assert request.skip_feb_29 is True
    assert request.leap_policy == "skip_feb_29"

    copied = request.model_copy(update={"skip_feb_29": False})
    assert copied.skip_feb_29 is False
    assert copied.leap_policy == "preserve"

    request.skip_feb_29 = False
    assert request.skip_feb_29 is False
    assert request.leap_policy == "preserve"


def test_future_scenario_and_period_validation():
    with pytest.raises(ValidationError):
        FutureRequest(baseline="base.epw", target_year=2050, climate_scenario="made-up")
    r = FutureRequest(
        baseline="base.epw",
        target_year=2050,
        climate_scenario="ssp245",
        reference_period=(1991, 2020),
    )
    assert r.climate_period == (2036, 2065)


def test_plan_hash_is_stable_and_tampering_detected():
    r = WeatherRequest(locations=[Location(lat=42, lon=-76)], years=[2024])
    p = WeatherPlan(request=r)
    assert WeatherPlan.model_validate_json(p.model_dump_json()).plan_hash == p.plan_hash
    raw = p.model_dump(mode="json")
    raw["request"]["years"] = [2023]
    with pytest.raises(ValidationError):
        WeatherPlan.model_validate(raw)


def test_legacy_plan_without_skip_feb_29_replays():
    plan = WeatherPlan(
        request=WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024])
    ).model_dump(mode="json")
    plan["request"].pop("skip_feb_29", None)
    plan["plan_hash"] = "256d616d06cf1068636f5749da12a410d9b871d37ad98c91f52b1aaa13f23273"

    replayed = WeatherPlan.model_validate(plan)

    assert replayed.plan_hash == plan["plan_hash"]
