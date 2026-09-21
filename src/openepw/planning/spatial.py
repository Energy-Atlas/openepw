import math

from ..models import BoundingBox, Location, OpenEPWError, PolygonQuery, SamplingSpec


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(p, a, b):
    return (
        abs(cross(a, b, p)) < 1e-10
        and min(a[0], b[0]) - 1e-10 <= p[0] <= max(a[0], b[0]) + 1e-10
        and min(a[1], b[1]) - 1e-10 <= p[1] <= max(a[1], b[1]) + 1e-10
    )


def inside(p, ring):
    hit = False
    for a, b in zip(ring, ring[1:]):
        if on_segment(p, a, b):
            return True
        if (a[1] > p[1]) != (b[1] > p[1]) and p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (
            b[1] - a[1]
        ) + a[0]:
            hit = not hit
    return hit


def validate_polygon(p):
    for ring in p.coordinates:
        if any(abs(a[0] - b[0]) > 180 for a, b in zip(ring, ring[1:])):
            raise OpenEPWError("INVALID_GEOMETRY", "Split dateline polygons before sampling")
        if abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:]))) < 1e-12:
            raise OpenEPWError("INVALID_GEOMETRY", "Polygon has zero signed area or crossing edges")
        segments = list(zip(ring, ring[1:]))
        for i, (a, b) in enumerate(segments):
            for j, (c, d) in enumerate(segments):
                if j <= i + 1 or (i == 0 and j == len(segments) - 1):
                    continue
                if cross(a, b, c) * cross(a, b, d) <= 0 and cross(c, d, a) * cross(c, d, b) <= 0:
                    if max(min(a[0], b[0]), min(c[0], d[0])) <= min(
                        max(a[0], b[0]), max(c[0], d[0])
                    ) and max(min(a[1], b[1]), min(c[1], d[1])) <= min(
                        max(a[1], b[1]), max(c[1], d[1])
                    ):
                        raise OpenEPWError("INVALID_GEOMETRY", "Self-intersecting polygon")
    for hole in p.coordinates[1:]:
        if not all(inside(point, p.coordinates[0]) for point in hole):
            raise OpenEPWError("INVALID_GEOMETRY", "Hole outside exterior ring")


def _iter_points(query: BoundingBox | PolygonQuery, spec: SamplingSpec, *, evaluation_limit: int):
    polygon = query if isinstance(query, PolygonQuery) else None
    if polygon:
        validate_polygon(polygon)
        ring = polygon.coordinates[0]
        box = BoundingBox(
            west=min(x for x, y in ring),
            east=max(x for x, y in ring),
            south=min(y for x, y in ring),
            north=max(y for x, y in ring),
        )
    else:
        box = query
    if box.south <= -89 or box.north >= 89:
        raise OpenEPWError("INVALID_GEOMETRY", "Regular longitude grid unsupported at the poles")
    east = box.east + 360 if box.east < box.west else box.east
    dy = spec.dy_km / 111.195
    first = box.south + (spec.offset_y_km % spec.dy_km) / 111.195
    rows = math.floor((box.north - first) / dy) + 1
    if rows > evaluation_limit:
        raise OpenEPWError("RESOURCE_LIMIT", "Sampling exceeds location limit before allocation")
    evaluated = 0
    for row in range(max(rows, 0)):
        lat = first + row * dy
        factor = 111.195 * math.cos(math.radians(lat))
        dx = spec.dx_km / factor
        origin = box.west + (spec.offset_x_km % spec.dx_km) / factor
        columns = math.floor((east - origin) / dx) + 1
        evaluated += columns
        if evaluated > evaluation_limit:
            raise OpenEPWError("RESOURCE_LIMIT", "Bounding sampling grid exceeds location limit")
        for col in range(max(columns, 0)):
            lon = (origin + col * dx + 180) % 360 - 180
            point = (lon, lat)
            if polygon and (
                not inside(point, polygon.coordinates[0])
                or any(inside(point, hole) for hole in polygon.coordinates[1:])
            ):
                continue
            yield Location(lat=lat, lon=lon)


def sample_preview(
    query: BoundingBox | PolygonQuery,
    spec: SamplingSpec,
    preview_limit: int,
    *,
    evaluation_limit: int = 1_000_000,
) -> tuple[list[Location], int]:
    points: list[Location] = []
    total = 0
    for point in _iter_points(query, spec, evaluation_limit=evaluation_limit):
        total += 1
        if len(points) < preview_limit:
            points.append(point)
    if total == 0:
        raise OpenEPWError("INVALID_GEOMETRY", "Sampling produces no locations")
    return points, total


def sample(query: BoundingBox | PolygonQuery, spec: SamplingSpec) -> list[Location]:
    points = list(_iter_points(query, spec, evaluation_limit=spec.max_locations))
    if not points:
        raise OpenEPWError("INVALID_GEOMETRY", "Sampling produces no locations")
    return points
