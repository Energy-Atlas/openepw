"""Availability contracts keep temporal meaning and occurrence identity intact."""

import pytest
from pydantic import ValidationError

from openepw.availability import (
    ActualScope,
    FutureWindowScope,
    LocationAssessment,
    SiteRecord,
    TMYReferenceScope,
)
from openepw.models import Location


def test_tmy_reference_cannot_be_read_as_actual_years():
    scope = TMYReferenceScope(start_year=2009, end_year=2023, product_label="TMYx 2009-2023")
    assert scope.kind == "tmy_reference"
    assert "years" not in scope.model_dump()
    with pytest.raises(ValidationError):
        ActualScope.model_validate(scope.model_dump())


def test_actual_years_are_sparse_and_station_id_is_text():
    scope = ActualScope(years=[2001, 2003], month_counts={2001: {1: 44}})
    site = SiteRecord(id="A00002-00001", product_id="noaa:isd", lat=None, lon=None)
    assert scope.years == [2001, 2003]
    assert site.id == "A00002-00001"
    assert site.elevation_m is None


def test_future_window_rejects_reversed_years():
    with pytest.raises(ValidationError):
        FutureWindowScope(start_year=2094, end_year=2085, scenario="rcp45")


def test_location_assessment_retains_duplicate_input_occurrence():
    location = Location(id="same", lat=42, lon=-76)
    a = LocationAssessment(occurrence_index=0, requested_location=location)
    b = LocationAssessment(occurrence_index=1, requested_location=location)
    assert a.requested_location.key == b.requested_location.key
    assert a.occurrence_index != b.occurrence_index
