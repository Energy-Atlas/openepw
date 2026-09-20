"""Inspect a small spatial plan without fetching hourly data."""

from openepw import WeatherRequest, plan
from openepw.models import BoundingBox, SamplingSpec

if __name__ == "__main__":
    request = WeatherRequest(
        locations=BoundingBox(west=-76.7, south=42.3, east=-76.3, north=42.6),
        sampling=SamplingSpec(dx_km=25, dy_km=25, max_locations=20),
        years=[2024],
        providers=["openmeteo"],
    )
    print(plan(request).model_dump_json(indent=2))
