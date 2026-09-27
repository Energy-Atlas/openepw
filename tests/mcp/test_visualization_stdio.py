"""A real stdio client receives a reusable visualization spec and data page."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic

from openepw.artifacts.store import ArtifactStore
from openepw.epw.writer import epw_bytes
from openepw.harness.mcp_client import StdioMCPPort


def test_visualization_json_survives_real_stdio_roundtrip(tmp_path):
    ref = ArtifactStore(tmp_path).write("a" * 32, "weather.epw",
                                        epw_bytes(synthetic(2023, 24)), "weather")

    async def journey():
        async with StdioMCPPort(tmp_path) as client:
            result = await client.call("weather_visualize", request={
                "artifact_ids": [ref.id], "family": "time_series",
                "variable": "dry_bulb"})
            assert result["total_rows"] == 24
            assert result["specs"][0]["data_ref"]["page_tool"] == "weather_data_page"
        async with StdioMCPPort(tmp_path) as client:
            page = await client.call("weather_data_page", view_id=result["view_id"],
                                     offset=20, limit=4)
            assert len(page["rows"]) == 4
            assert page["next_offset"] is None

    asyncio.run(journey())
