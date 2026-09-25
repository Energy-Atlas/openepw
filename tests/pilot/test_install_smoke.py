"""Installed client and agent entry points keep the local stdio contract usable."""

import asyncio
from importlib.metadata import distribution

from openepw.artifacts.store import ArtifactStore
from openepw.harness.mcp_client import StdioMCPPort


def test_installed_entrypoint_and_real_stdio_resource(tmp_path):
    scripts = {entry.name for entry in distribution("openepw").entry_points}
    assert {"openepw", "openepw-agent"} <= scripts
    artifact = ArtifactStore(tmp_path).write(
        "pilot", "check.json", b'{"pilot":true}', "manifest")

    async def smoke():
        async with StdioMCPPort(tmp_path) as client:
            assert client.session is not None
            tools = await client.session.list_tools()
            assert {"weather_assess", "weather_plan", "artifact_inspect"} <= {
                item.name for item in tools.tools}
            templates = await client.session.list_resource_templates()
            assert any(str(item.uriTemplate).startswith("weather://artifacts/")
                       for item in templates.resourceTemplates)
            inspected = await client.call("artifact_inspect", artifact_id=artifact.id)
            assert inspected["sha256"] == artifact.sha256

    asyncio.run(smoke())
