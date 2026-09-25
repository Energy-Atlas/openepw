import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from openepw.config import RuntimeConfig
from openepw.mcp.server import _bounded, create_server
from openepw.models import OpenEPWError
from openepw.service import WeatherService


def test_stage4_tool_contract(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {
        "weather_geocode", "weather_assess", "weather_discover", "weather_plan",
        "future_plan", "plan_inspect", "baseline_upload", "baseline_register_path",
        "weather_submit", "future_submit", "job_inspect", "job_cancel",
        "job_retry_failed", "artifact_inspect", "weather_export_compact",
        "weather_fetch", "weather_inspect", "weather_generate_future",
    } <= names


def test_invalid_input_has_safe_code(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError, match="INVALID_BASELINE") as error:
        asyncio.run(server.call_tool("baseline_upload", {"content_base64": "bad!"}))
    assert "Traceback" not in str(error.value)


def test_catalog_sized_tool_result_fits_but_runaway_result_is_rejected():
    catalog_sized = {"availability": {"options": [{"evidence": "x" * 100_000}]}}
    assert _bounded(catalog_sized) == catalog_sized
    with pytest.raises(OpenEPWError, match="RESOURCE_LIMIT"):
        _bounded({"availability": {"options": [{"evidence": "x" * 200_000}]}})
