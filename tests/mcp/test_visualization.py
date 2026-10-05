"""Visualization MCP tools return bounded JSON without re-fetching weather."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic

from openepw.config import RuntimeConfig
from openepw.epw.writer import epw_bytes
from openepw.mcp.server import create_server
from openepw.service import WeatherService


def call(server, name, **arguments):
    return asyncio.run(server.call_tool(name, arguments)).structuredContent


def test_mcp_exposes_capabilities_and_a_paged_monthly_spec(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    ref = service.artifacts.write("a" * 32, "weather.epw",
                                  epw_bytes(synthetic(2023, 8760)), "weather",
                                  "application/vnd.energyplus.epw")
    server = create_server(service)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {"weather_visualization_capabilities", "weather_data_describe",
            "weather_visualize", "weather_data_page"} <= names
    capabilities = call(server, "weather_visualization_capabilities")
    assert any(item["family"] == "wind_rose" and item["status"] == "planned"
               for item in capabilities["families"])
    described = call(server, "weather_data_describe", artifact_ids=[ref.id])
    assert described["sources"][0]["variables"]["dry_bulb"]["unit"] == "degC"
    result = call(server, "weather_visualize", request={
        "artifact_ids": [ref.id], "family": "monthly_series",
        "variable": "dry_bulb", "aggregation": "mean"})
    assert result["specs"][0]["family"] == "monthly_series"
    assert result["specs"][0]["data_ref"]["view_id"] == result["view_id"]
    assert result["rows"][0]["value"] == 20.0
    page = call(server, "weather_data_page", view_id=result["view_id"], offset=10, limit=2)
    assert [row["month"] for row in page["rows"]] == [11, 12]
    assert len(json.dumps(result)) < 160_000


def test_planned_visualization_family_returns_typed_mcp_error(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    ref = service.artifacts.write("a" * 32, "weather.epw",
                                  epw_bytes(synthetic(2023, 24)), "weather")
    server = create_server(service)
    with pytest.raises(ToolError, match="VISUALIZATION_UNSUPPORTED"):
        call(server, "weather_visualize", request={
            "artifact_ids": [ref.id], "family": "wind_rose", "variable": "wind_speed"})
