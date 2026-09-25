import asyncio
import base64
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl

from openepw.artifacts.store import ArtifactStore


def test_real_stdio_session_tools_errors_and_resource(tmp_path):
    artifact = ArtifactStore(tmp_path).write(
        "abc123", "small.json", b'{"ok": true}', "manifest")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from openepw.cli.main import main; raise SystemExit(main())",
              "--data-root", str(tmp_path), "mcp"],
    )

    async def session_check():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "openepw"
                tools = await client.list_tools()
                assert {"weather_assess", "artifact_inspect", "baseline_upload"} <= {
                    tool.name for tool in tools.tools
                }
                templates = await client.list_resource_templates()
                assert any(str(item.uriTemplate).startswith("weather://artifacts/")
                           for item in templates.resourceTemplates)
                inspected = await client.call_tool(
                    "artifact_inspect", {"artifact_id": artifact.id})
                assert not inspected.isError
                assert inspected.structuredContent["sha256"] == artifact.sha256
                invalid = await client.call_tool(
                    "baseline_upload", {"content_base64": "bad!"})
                assert invalid.isError
                assert "INVALID_BASELINE" in invalid.content[0].text
                resource = await client.read_resource(
                    AnyUrl(f"weather://artifacts/{artifact.id}"))
                content = resource.contents[0]
                assert base64.b64decode(content.blob) == b'{"ok": true}'

    asyncio.run(session_check())
