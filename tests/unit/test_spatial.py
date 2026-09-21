import pytest

from openepw.config import RuntimeConfig
from openepw.models import (
    BoundingBox,
    Location,
    OpenEPWError,
    PolygonQuery,
    SamplingSpec,
    WeatherRequest,
)
from openepw.planning.spatial import sample
from openepw.service import WeatherService


def test_dateline_and_point_limits():
    points = sample(
        BoundingBox(west=179, south=0, east=-179, north=1), SamplingSpec(dx_km=100, dy_km=100)
    )
    assert points and all(abs(p.lon) >= 179 for p in points)
    with pytest.raises(OpenEPWError):
        sample(
            BoundingBox(west=-180, south=-80, east=180, north=80),
            SamplingSpec(dx_km=1, dy_km=1, max_locations=10),
        )


def test_polygon_holes_and_self_intersection():
    p = PolygonQuery(
        coordinates=[
            [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)],
            [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5), (0.5, 0.5)],
        ]
    )
    points = sample(p, SamplingSpec(dx_km=50, dy_km=50))
    assert points
    assert not any(0.5 < x.lon < 1.5 and 0.5 < x.lat < 1.5 for x in points)
    bow = PolygonQuery(coordinates=[[(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)]])
    with pytest.raises(OpenEPWError):
        sample(bow, SamplingSpec())


def test_spatial_preview_counts_period_outputs_without_allocating_past_render_cap(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    request = WeatherRequest(
        locations=BoundingBox(west=0, south=0, east=1, north=1),
        sampling=SamplingSpec(dx_km=100, dy_km=100, max_locations=10),
        product="amy",
        years=[2023, 2024],
    )

    result = service.preview_spatial(request)

    assert result.total_count == 4
    assert result.returned_count == 4
    assert result.planned_output_count == 8
    assert result.execution_limit == 10
    assert result.executable is True
    assert result.truncated is False
    assert [
        location.model_copy(update={"id": None}) for location in result.locations
    ] == service.locations(request)
    assert all(location.id == location.key for location in result.locations)


def test_spatial_preview_counts_each_selected_dataset_against_execution_limit(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    request = WeatherRequest(
        locations=BoundingBox(west=0, south=0, east=1, north=1),
        sampling=SamplingSpec(dx_km=100, dy_km=100, max_locations=10),
        product="amy",
        years=[2023, 2024],
        dataset_selections=[
            {"provider": "first", "dataset": "archive"},
            {"provider": "second", "dataset": "archive"},
        ],
    )

    result = service.preview_spatial(request)

    assert result.planned_output_count == 16
    assert result.execution_limit == 10


def test_spatial_preview_returns_deterministic_prefix_and_limit_issue(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    request = WeatherRequest(
        locations=BoundingBox(west=0, south=0, east=1, north=1),
        sampling=SamplingSpec(dx_km=100, dy_km=100, max_locations=2),
        product="amy",
        years=[2024],
    )

    result = service.preview_spatial(request)

    assert result.total_count == 4
    assert result.returned_count == 2
    assert [location.model_copy(update={"id": None}) for location in result.locations] == [
        Location(lat=0, lon=0),
        Location(lat=0, lon=0.899321012635454),
    ]
    assert result.executable is False
    assert result.truncated is True
    assert [(issue.code, issue.severity) for issue in result.issues] == [
        ("RESOURCE_LIMIT", "error")
    ]


def test_sampled_points_can_use_longitude_based_standard_time():
    from openepw.models import BoundingBox, SamplingSpec, nominal_offset_minutes
    from openepw.planning.spatial import sample

    assert [nominal_offset_minutes(lon) for lon in (-76.5, -7.5, 7.5, 0, 179.9, -179.9)] == [
        -300,
        0,
        60,
        0,
        720,
        -720,
    ]
    box = BoundingBox(west=-77, south=42, east=-76, north=43)
    utc = sample(box, SamplingSpec(dx_km=50, dy_km=50))
    local = sample(box, SamplingSpec(dx_km=50, dy_km=50, standard_offset="longitude"))
    assert {point.standard_offset_minutes for point in utc} == {0}
    assert {point.standard_offset_minutes for point in local} == {-300}
    assert [(p.lat, p.lon) for p in utc] == [(p.lat, p.lon) for p in local]
    # A grid spanning nominal zones gives each point its own offset.
    wide = sample(
        BoundingBox(west=-10, south=40, east=10, north=41),
        SamplingSpec(dx_km=400, dy_km=400, standard_offset="longitude"),
    )
    assert {nominal_offset_minutes(p.lon) for p in wide} == {
        p.standard_offset_minutes for p in wide
    }
    assert len({p.standard_offset_minutes for p in wide}) > 1
