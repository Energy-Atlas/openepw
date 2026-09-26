"""Real stdio access to generic EPW inputs and existing weather artifacts."""

import asyncio
import base64
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl
from test_epw import synthetic

from openepw.artifacts.store import ArtifactStore
from openepw.epw.writer import epw_bytes


def test_real_client_upload_and_existing_weather_resource(tmp_path):
    store = ArtifactStore(tmp_path)
    body = epw_bytes(synthetic(2023, 8760))
    fetched = store.write("b" * 32, "weather.epw", body, "weather",
                          "application/vnd.energyplus.epw")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from openepw.cli.main import main; raise SystemExit(main())",
              "--data-root", str(tmp_path), "mcp"],
    )

    async def run():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                tools = {item.name for item in (await client.list_tools()).tools}
                assert "future_plan" not in tools
                assert "epw_upload" in tools
                upload = await client.call_tool(
                    "epw_upload", {"content_base64": base64.b64encode(body).decode()})
                assert not upload.isError
                uploaded_id = upload.structuredContent["artifact_id"]
                assert uploaded_id != fetched.id
                for artifact_id in (uploaded_id, fetched.id):
                    inspected = await client.call_tool(
                        "artifact_inspect", {"artifact_id": artifact_id})
                    assert not inspected.isError
                    resource = await client.read_resource(
                        AnyUrl(f"weather://artifacts/{artifact_id}"))
                    assert base64.b64decode(resource.contents[0].blob) == body

    asyncio.run(run())
