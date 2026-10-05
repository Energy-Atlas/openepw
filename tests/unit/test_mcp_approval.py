import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from mcp.types import ElicitRequestFormParams
from mcp_memory import session_call
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.mcp.approval import approval_callback, confirmation_message, plan_hash_from_message
from openepw.mcp.server import create_server
from openepw.models import WeatherRequest
from openepw.service import WeatherService

REQUEST = {"locations": {"lat": 1, "lon": 0}, "start": "2024-01-01", "end": "2024-01-01"}
HASH = "a" * 64


@pytest.fixture
def stack(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    runner = JobRunner(service)
    yield service, runner, create_server(service, runner=runner)
    runner.close()


def _plan(server):
    return asyncio.run(server.call_tool("weather_plan", {"request": REQUEST})).structuredContent


def test_message_round_trips_the_plan_hash():
    assert plan_hash_from_message(confirmation_message(HASH)) == HASH
    assert plan_hash_from_message("Approve something else?") is None


def test_client_callback_accepts_only_recorded_approvals():
    callback = approval_callback({HASH}.__contains__)
    params = ElicitRequestFormParams(message=confirmation_message(HASH),
                                     requestedSchema={"type": "object", "properties": {}})
    assert asyncio.run(callback(None, params)).action == "accept"
    other = ElicitRequestFormParams(message=confirmation_message("b" * 64),
                                    requestedSchema={"type": "object", "properties": {}})
    assert asyncio.run(callback(None, other)).action == "decline"


def test_confirmed_submit_runs_and_records_how_it_was_approved(stack):
    service, runner, server = stack
    plan = _plan(server)
    result = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]}, approve=True)
    assert not result.isError
    job_id = result.structuredContent["id"]
    assert result.structuredContent["approved_via"] == "elicitation"
    for _ in range(100):
        if runner.store.get(job_id).state not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert runner.store.get(job_id).state == "completed"


def test_declined_or_unconfirmable_submit_starts_nothing(stack):
    service, runner, server = stack
    plan = _plan(server)
    declined = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]}, approve=False)
    assert declined.isError and "APPROVAL_DECLINED" in declined.content[0].text
    unable = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]})
    assert unable.isError and "APPROVAL_REQUIRED" in unable.content[0].text
    assert list(runner.store.unfinished()) == []


def test_legacy_inline_fetch_needs_the_same_confirmation_and_stores_the_plan(stack):
    service, runner, server = stack
    plan = service.plan(WeatherRequest.model_validate(REQUEST))
    inline = {"plan": plan.model_dump(mode="json")}
    refused = session_call(server, "weather_fetch", inline)
    assert refused.isError and "APPROVAL_REQUIRED" in refused.content[0].text
    accepted = session_call(server, "weather_fetch", inline, approve=True)
    assert not accepted.isError and accepted.structuredContent["approved_via"] == "elicitation"
    assert service.plan_store.get(plan.plan_hash).plan_hash == plan.plan_hash


def test_rest_submission_records_api_approval(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        plan = client.post("/v1/weather/plan", json=REQUEST).json()
        job = client.post("/v1/weather/jobs", json={"plan_hash": plan["plan_hash"]}).json()
        assert job["approved_via"] == "api"
