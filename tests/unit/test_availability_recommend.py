"""Ranking is deterministic and does not promote unknowns to recommendations."""

from datetime import datetime, timezone

from openepw.availability import (
    AvailabilityResult,
    EligibilityDecision,
    LocationAssessment,
    ProductRecord,
    SuitabilityOption,
    WeatherAvailabilityQuery,
)
from openepw.availability.recommend import rank
from openepw.models import Location, WeatherRequest


def _result():
    location = Location(lat=42, lon=-76)
    return AvailabilityResult(
        checked_at=datetime(2026, 9, 24, tzinfo=timezone.utc),
        locations=[LocationAssessment(occurrence_index=0, requested_location=location)],
        options=[
            SuitabilityOption(id="0:noaa", occurrence_index=0,
                              product=ProductRecord(id="noaa", provider="noaa", dataset="isd",
                                                    temporal_kind="actual"),
                              eligibility=EligibilityDecision(status="supported"),
                              missing_preferred_variables=["ghi", "dni", "dhi"]),
            SuitabilityOption(id="0:nsrdb", occurrence_index=0,
                              product=ProductRecord(id="nsrdb", provider="nsrdb",
                                                    dataset="aggregate", temporal_kind="actual"),
                              eligibility=EligibilityDecision(status="supported")),
        ],
    )


def test_solar_purpose_explains_radiation_gap():
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2024]), purpose="solar")
    ranked = rank(_result(), query)
    assert ranked.locations[0].recommended_option_ids == ["0:nsrdb"]
    noaa = next(o for o in ranked.options if o.id == "0:noaa")
    assert "MISSING_PREFERRED_RADIATION" in noaa.reasons


def test_no_recommendation_when_all_options_unknown():
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2024]))
    result = _result()
    for option in result.options:
        option.eligibility.status = "unknown"
    ranked = rank(result, query)
    assert ranked.locations[0].recommended_option_ids == []
    assert len(ranked.options) == 2


def test_thermal_extremes_labels_typical_year_limitation():
    result = _result()
    result.options[0].product.temporal_kind = "tmy_reference"
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), product="tmy"), purpose="thermal_extremes")
    ranked = rank(result, query)
    assert "TYPICAL_YEAR_LIMITATION" in ranked.options[0].reasons
