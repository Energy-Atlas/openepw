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
