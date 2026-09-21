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
    assert result.locations == service.locations(request)


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
    assert result.locations == [
        Location(lat=0, lon=0),
        Location(lat=0, lon=0.899321012635454),
    ]
    assert result.executable is False
    assert result.truncated is True
    assert [(issue.code, issue.severity) for issue in result.issues] == [
        ("RESOURCE_LIMIT", "error")
    ]
