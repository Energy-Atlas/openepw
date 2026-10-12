"""Fixed standard-time offsets and the location review shown before planning."""

from openepw.config import RuntimeConfig
from openepw.models import BoundingBox, Location
from openepw.planning.offsets import estimate_offsets, location_key, standard_time_note
from openepw.service import WeatherService

AREA = BoundingBox(west=-76.6, east=-76.4, south=42.3, north=42.5).model_dump()


def test_missing_offsets_are_estimated_and_explicit_ones_kept():
    points, sampling, estimated = estimate_offsets([
        {"lat": 42.44, "lon": -76.5},
        {"lat": 42.44, "lon": -76.5, "standard_offset_minutes": 0},
    ])
    assert [point["standard_offset_minutes"] for point in points] == [-300, 0]
    assert sampling is None and estimated is True
    point, _, estimated = estimate_offsets({"lat": 1, "lon": 2, "standard_offset_minutes": 60})
    assert point["standard_offset_minutes"] == 60 and estimated is False


def test_an_area_samples_with_longitude_offsets():
    value, sampling, estimated = estimate_offsets(AREA)
    assert value == AREA and sampling == {"standard_offset": "longitude"} and estimated is True


def test_standard_time_note_names_offsets_and_estimation():
    note = standard_time_note([Location(lat=0, lon=-76.5, standard_offset_minutes=-300)], True)
    assert "UTC-05:00" in note and "no daylight-saving shift" in note
    assert "estimated from longitude" in note
    assert "estimated" not in standard_time_note([Location(lat=0, lon=0)], False)


def test_location_key_changes_when_the_geography_changes():
    assert location_key({"lat": 1, "lon": 2}) == location_key({"lon": 2, "lat": 1})
    assert location_key({"lat": 1, "lon": 2}) != location_key({"lat": 1, "lon": 3})


def test_service_review_returns_points_note_and_stable_key(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    first = service.review_locations({"lat": 42.44, "lon": -76.5, "name": "Ithaca"})
    assert first["points"][0]["standard_offset_minutes"] == -300
    assert first["offset_estimated"] is True and first["point_count"] == 1
    assert "UTC-05:00" in first["standard_time"] and first["sampling"] is None
    assert service.review_locations({"lat": 42.44, "lon": -76.5, "name": "Ithaca"})["key"] == first["key"]
    area = service.review_locations(AREA)
    assert area["sampling"]["standard_offset"] == "longitude" and area["point_count"] >= 1
    assert {point["standard_offset_minutes"] for point in area["points"]} == {-300}
