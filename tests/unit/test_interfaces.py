import asyncio
import json

import pytest
from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def test_cli_inspects_epw_without_network(tmp_path, capsys):
    from test_epw import synthetic

    from openepw.cli.main import main
    from openepw.epw import write_epw

    path = tmp_path / "sample.epw"
    write_epw(synthetic(), path)
    assert main(["inspect", str(path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["rows"] == 24
    assert "data" not in data


def test_mcp_tool_surface_and_core_plan(tmp_path):
    pytest.importorskip("mcp")
    from openepw.mcp.server import create_server

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    server = create_server(service)
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} >= {
        "weather_geocode",
        "weather_discover",
        "weather_plan",
        "weather_fetch",
        "weather_inspect",
        "weather_generate_future",
    }
    result = asyncio.run(
        server.call_tool(
            "weather_plan",
            {
                "request": {
                    "locations": {"lat": 1, "lon": 0},
                    "start": "2024-01-01",
                    "end": "2024-01-01",
                }
            },
        )
    )
    assert "plan_hash" in str(result)
    assert "8760" not in str(result)
