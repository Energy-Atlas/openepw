import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from openepw.config import RuntimeConfig
from openepw.mcp.server import create_server
from openepw.service import WeatherService

ITHACA = {"lat": 42.44, "lon": -76.5, "name": "Ithaca"}


def test_location_review_estimates_offsets_and_returns_a_key(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    result = asyncio.run(server.call_tool("weather_locations_review", {"locations": ITHACA}))
    data = result.structuredContent
    assert data["points"][0]["standard_offset_minutes"] == -300 and data["offset_estimated"] is True
    assert data["key"] in result.content[0].text and "UTC-05:00" in result.content[0].text


def test_location_review_rejects_invalid_coordinates_with_details(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError, match="INVALID_REQUEST"):
        asyncio.run(server.call_tool("weather_locations_review", {"locations": {"lat": 95, "lon": 0}}))


def test_product_offers_tool_matches_the_service(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    server = create_server(service)
    result = asyncio.run(server.call_tool("weather_product_offers",
                                          {"locations": ITHACA, "product": "tmy"}))
    expected = service.product_offers(ITHACA, product="tmy")
    assert result.structuredContent == expected
    assert expected["options"] and all(option["group"] == "typical" for option in expected["options"])
    assert expected["options"][0]["id"] in result.content[0].text
