import asyncio
import json

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
        "plan_inspect", "epw_upload", "epw_register_path",
        "weather_submit", "job_inspect", "job_cancel",
        "job_retry_failed", "artifact_inspect", "weather_export_compact",
        "weather_fetch", "weather_inspect",
    } <= names


def test_invalid_input_has_safe_code(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError, match="INVALID_BASELINE") as error:
        asyncio.run(server.call_tool("epw_upload", {"content_base64": "bad!"}))
    assert "Traceback" not in str(error.value)


def test_catalog_sized_tool_result_fits_but_runaway_result_is_rejected():
    catalog_sized = {"availability": {"options": [{"evidence": "x" * 100_000}]}}
    assert _bounded(catalog_sized) == catalog_sized
    with pytest.raises(OpenEPWError, match="RESOURCE_LIMIT"):
        _bounded({"availability": {"options": [{"evidence": "x" * 200_000}]}})


def _error(excinfo):
    text = str(excinfo.value)
    return json.loads(text[text.index("{"):])


def test_dict_parameters_publish_inlined_field_schemas(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name, field in (("weather_plan", "request"), ("weather_discover", "request"),
                        ("weather_assess", "query"), ("weather_place_set", "query"),
                        ("weather_visualize", "request")):
        schema = tools[name].inputSchema["properties"][field]
        assert schema.get("properties"), name
        assert "$ref" not in json.dumps(schema), name
    assert "locations" in tools["weather_plan"].inputSchema["properties"]["request"]["properties"]
    assert all(tool.description and "Do not" in tool.description for tool in tools.values())


def test_validation_errors_name_the_failing_field(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("weather_plan", {
            "request": {"locations": {"lat": 200, "lon": 0}, "years": [2020]}}))
    payload = _error(excinfo)
    assert payload["code"] == "INVALID_REQUEST" and payload["retryable"] is False
    assert any(item["loc"].startswith("locations") for item in payload["details"])
    assert "200" not in json.dumps(payload["details"])


def test_internal_errors_carry_a_correlation_id_but_no_detail(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))

    def broken(*args, **kwargs):
        raise RuntimeError(r"C:\secret\path token=zzz-private")

    service.geocode = broken
    server = create_server(service)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("weather_geocode", {"query": "Ithaca"}))
    payload = _error(excinfo)
    assert payload["code"] == "INTERNAL_ERROR" and len(payload["correlation_id"]) == 12
    assert "secret" not in str(excinfo.value) and "zzz" not in str(excinfo.value)


def test_results_carry_a_summary_and_structured_data(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    result = asyncio.run(server.call_tool("weather_visualization_capabilities", {}))
    assert result.structuredContent["families"]
    text = result.content[0].text
    assert text.startswith("View families:") and len(text) <= 1500


def test_every_registered_tool_has_exactly_one_access_class(tmp_path):
    from openepw.mcp.access import HOST_TOOLS, LEGACY_TOOLS, MODEL_TOOLS

    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == MODEL_TOOLS | HOST_TOOLS | LEGACY_TOOLS
    assert not (MODEL_TOOLS & HOST_TOOLS or MODEL_TOOLS & LEGACY_TOOLS or HOST_TOOLS & LEGACY_TOOLS)
    assert "weather_submit" in HOST_TOOLS and "weather_plan" in MODEL_TOOLS
    assert "job_retry_failed" in HOST_TOOLS and "weather_fetch" in LEGACY_TOOLS
