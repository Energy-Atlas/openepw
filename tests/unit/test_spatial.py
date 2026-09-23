import pytest

from openepw.models import BoundingBox, OpenEPWError, PolygonQuery, SamplingSpec
from openepw.planning.spatial import sample


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


def test_sampled_points_can_use_longitude_based_standard_time():
    from openepw.models import nominal_offset_minutes

    assert [nominal_offset_minutes(lon) for lon in (-76.5, -7.5, 7.5, 0, 179.9, -179.9)] == [
        -300, 0, 60, 0, 720, -720,
    ]
    box = BoundingBox(west=-77, south=42, east=-76, north=43)
    utc = sample(box, SamplingSpec(dx_km=50, dy_km=50))
    local = sample(box, SamplingSpec(dx_km=50, dy_km=50, standard_offset="longitude"))
    assert {point.standard_offset_minutes for point in utc} == {0}
    assert {point.standard_offset_minutes for point in local} == {-300}
    assert [(p.lat, p.lon) for p in utc] == [(p.lat, p.lon) for p in local]
