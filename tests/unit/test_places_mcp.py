"""MCP place tools: interpret, preview lists and clarified place sets."""

import asyncio
import json

import pytest
from test_places_service import Http

from openepw.config import RuntimeConfig
from openepw.service import WeatherService

pytest.importorskip("mcp")
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from openepw.mcp.server import MAX_RESULT, create_server  # noqa: E402


def _server(tmp_path):
    return create_server(WeatherService(RuntimeConfig(data_root=tmp_path), http=Http()))


def _call(server, name, **kwargs):
    return asyncio.run(server.call_tool(name, kwargs)).structuredContent


def test_place_tools_are_listed(tmp_path):
    names = {tool.name for tool in asyncio.run(_server(tmp_path).list_tools())}
    assert {"weather_places_interpret", "weather_places_preview", "weather_place_set"} <= names


def test_preview_is_compact_numbered_and_keeps_ambiguity(tmp_path):
    result = _call(_server(tmp_path), "weather_places_preview", places=["Boston", "Nowhereville", "40, -105"])
    assert result["count"] == 3 and result["resolved"] == 2
    assert result["rows"][0] == {"index": 1, "input": "Boston", "status": "resolved",
                                 "name": "Boston, Massachusetts, United States", "lat": 42.36, "lon": -71.06,
                                 "source": "geocoder", "ambiguous": True, "candidate_count": 2,
                                 "source_id": "1"}
    assert result["rows"][1] == {"index": 2, "input": "Nowhereville", "status": "unresolved"}
    assert {issue["code"] for issue in result["issues"]} == {"AMBIGUOUS_LOCATION", "UNRESOLVED_PLACE"}
    assert "geojson" not in result and len(result["digest"]) == 64


def test_thousand_place_preview_fits_the_result_limit(tmp_path):
    result = _call(_server(tmp_path), "weather_places_preview",
                   places=[f"{40 + index / 1000:.3f}, -105" for index in range(1000)])
    assert result["count"] == 1000
    assert len(json.dumps(result)) < MAX_RESULT


def test_interpret_asks_before_a_set_is_enumerated_and_place_set_previews(tmp_path):
    server = _server(tmp_path)
    vague = _call(server, "weather_places_interpret", text="all cities in America")
    assert vague["kind"] == "descriptive" and vague["query"] is None
    answered = _call(server, "weather_places_interpret", text="Texas, over 100k, top 2", draft=vague["draft"])
    complete = _call(server, "weather_places_interpret", text="top 2 cities over 100k in Texas")
    assert answered["query"] == complete["query"]
    preview = _call(server, "weather_place_set", query=complete["query"])
    assert [row["name"] for row in preview["rows"]] == ["Houston, Texas, United States",
                                                        "Dallas, Texas, United States"]
    assert any("GeoNames" in item for item in preview["attribution"])


def test_errors_are_tool_errors(tmp_path):
    server = _server(tmp_path)
    with pytest.raises(ToolError, match="NEEDS_CLARIFICATION"):
        _call(server, "weather_places_preview", places=["all cities in Texas"])
    with pytest.raises(ToolError, match="INVALID_REQUEST"):
        _call(server, "weather_place_set", query={"kind": "city", "country": "US", "limit": 5})
    with pytest.raises(ToolError, match="INVALID_REQUEST"):
        _call(server, "weather_places_preview", places=["x" * 151])


def test_weather_requests_accept_a_full_preview_of_points(tmp_path):
    server = _server(tmp_path)
    request = {"locations": [{"lat": 40 + index / 1000, "lon": -105} for index in range(60)],
               "start": "2024-01-01", "end": "2024-01-01"}
    try:
        _call(server, "weather_discover", request=request)
    except ToolError as error:        # provider stubs may fail; the point cap must not
        assert "RESOURCE_LIMIT" not in str(error)
