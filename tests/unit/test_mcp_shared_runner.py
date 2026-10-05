import asyncio

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server
from openepw.service import WeatherService


async def _open_and_close(server):
    async with create_connected_server_and_client_session(server) as client:
        await client.list_tools()


def test_a_supplied_runner_is_used_and_left_running(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    runner = JobRunner(service)
    try:
        server = create_server(service, runner=runner)
        assert server.openepw_runner is runner
        asyncio.run(_open_and_close(server))
        assert runner.pool._shutdown is False
    finally:
        runner.close()


def test_the_app_shares_its_runner_with_its_mcp_server(tmp_path):
    with TestClient(create_app(WeatherService(RuntimeConfig(data_root=tmp_path)))) as client:
        state = client.app.state
        assert state.mcp_server is not None
        assert state.mcp_server.openepw_runner is state.runner
