import asyncio

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session
from mcp_memory import session_call
from test_batch import StationProvider

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
        assert runner._root_lock is None          # the owner recovers and locks; the server does not
    finally:
        runner.close()


def test_an_owned_runner_outlives_each_session(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    server = create_server(service)
    try:
        request = {"locations": {"lat": 1, "lon": 0}, "start": "2024-01-01", "end": "2024-01-01"}
        plan = session_call(server, "weather_plan", {"request": request}).structuredContent
        submitted = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]},
                                 approve=True)
        assert not submitted.isError, submitted.content[0].text
        assert server.openepw_runner.pool._shutdown is False
        assert server.openepw_runner._root_lock is not None    # held until the process closes it
    finally:
        server.openepw_runner.close()
    assert server.openepw_runner._root_lock is None


def test_the_app_shares_its_runner_with_its_mcp_server(tmp_path):
    with TestClient(create_app(WeatherService(RuntimeConfig(data_root=tmp_path)))) as client:
        state = client.app.state
        assert state.mcp_server is not None
        assert state.mcp_server.openepw_runner is state.runner


def test_the_mcp_command_closes_its_runner_when_the_server_stops(tmp_path, monkeypatch):
    import openepw.mcp.server as mcp_server
    from openepw.cli.main import main

    built = []

    def fake_create_server(service, **kwargs):
        server = create_server(service, **kwargs)
        server.run = lambda transport: server.openepw_runner.recover()   # serve, then stop
        built.append(server)
        return server

    monkeypatch.setattr(mcp_server, "create_server", fake_create_server)
    assert main(["--data-root", str(tmp_path), "mcp"]) == 0
    [server] = built
    assert server.openepw_runner._root_lock is None and server.openepw_runner.pool._shutdown
