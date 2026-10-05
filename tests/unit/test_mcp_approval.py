import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from mcp.types import ElicitRequestFormParams, ElicitResult
from mcp_memory import session_call
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.mcp.approval import approval_callback, confirmation_message, plan_hash_from_message
from openepw.mcp.server import create_server
from openepw.models import OpenEPWError, WeatherPlan, WeatherRequest
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


def _job_count(runner):
    with runner.store.connect() as db:
        return db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


class Recorder:
    """Client elicitation callback that records each confirmation it was asked for."""

    def __init__(self, content=None):
        self.messages = []
        self.content = content

    async def __call__(self, context, params):
        self.messages.append(params.message)
        if self.content is None:
            return ElicitResult(action="decline")
        return ElicitResult(action="accept", content=self.content)


class FailingProvider(StationProvider):
    """Every fetch fails, so a finished job has a failed (missing) output to retry."""

    def fetch(self, task, http):
        raise OpenEPWError("SOURCE_FAILED", "Synthetic failure")


@pytest.fixture
def failing(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[FailingProvider()])
    runner = JobRunner(service)
    yield service, runner, create_server(service, runner=runner)
    runner.close()


def _finished_job(service, runner, *, cancel=False, approved_via=None):
    """Run a real job to a finished state with no produced output (failed or cancelled)."""
    plan = service.plan(WeatherRequest.model_validate(REQUEST))
    service.plan_store.put(plan)
    job = runner.store.submit(plan, approved_via=approved_via)
    if cancel:
        runner.store.cancel(job.id)
    runner.run(job.id)
    finished = runner.store.get(job.id)
    assert finished.state == ("cancelled" if cancel else "failed")
    return finished


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
    refused = Recorder(content={"approve": False})
    accepted_no = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]},
                               callback=refused)
    assert accepted_no.isError and "APPROVAL_DECLINED" in accepted_no.content[0].text
    assert refused.messages == [confirmation_message(plan["plan_hash"])]
    assert _job_count(runner) == 0


def test_legacy_inline_fetch_needs_the_same_confirmation_and_stores_the_plan(stack):
    service, runner, server = stack
    plan = service.plan(WeatherRequest.model_validate(REQUEST))
    inline = {"plan": plan.model_dump(mode="json")}
    refused = session_call(server, "weather_fetch", inline)
    assert refused.isError and "APPROVAL_REQUIRED" in refused.content[0].text
    declined = session_call(server, "weather_fetch", inline, approve=False)
    assert declined.isError and "APPROVAL_DECLINED" in declined.content[0].text
    assert _job_count(runner) == 0
    accepted = session_call(server, "weather_fetch", inline, approve=True)
    assert not accepted.isError and accepted.structuredContent["approved_via"] == "elicitation"
    assert service.plan_store.get(plan.plan_hash).plan_hash == plan.plan_hash


def test_rest_submission_records_api_approval(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        plan = client.post("/v1/weather/plan", json=REQUEST).json()
        job = client.post("/v1/weather/jobs", json={"plan_hash": plan["plan_hash"]}).json()
        assert job["approved_via"] == "api"


@pytest.mark.parametrize("tool", ["weather_submit", "weather_fetch"])
def test_plan_without_outputs_is_refused_before_asking(stack, tool):
    service, runner, server = stack
    empty = WeatherPlan(request=WeatherRequest.model_validate(REQUEST))
    service.plan_store.put(empty)
    arguments = ({"plan_hash": empty.plan_hash} if tool == "weather_submit"
                 else {"plan": empty.model_dump(mode="json")})
    recorder = Recorder(content={"approve": True})
    result = session_call(server, tool, arguments, callback=recorder)
    assert result.isError and "NO_EXECUTABLE_OUTPUTS" in result.content[0].text
    assert recorder.messages == []
    assert _job_count(runner) == 0


def test_retry_without_a_confirming_client_starts_nothing(failing):
    service, runner, server = failing
    job = _finished_job(service, runner)
    result = session_call(server, "job_retry_failed", {"job_id": job.id})
    assert result.isError and "APPROVAL_REQUIRED" in result.content[0].text
    assert _job_count(runner) == 1


def test_declined_retry_starts_nothing(failing):
    service, runner, server = failing
    job = _finished_job(service, runner)
    declined = session_call(server, "job_retry_failed", {"job_id": job.id}, approve=False)
    assert declined.isError and "APPROVAL_DECLINED" in declined.content[0].text
    refused = Recorder(content={"approve": False})
    accepted_no = session_call(server, "job_retry_failed", {"job_id": job.id}, callback=refused)
    assert accepted_no.isError and "APPROVAL_DECLINED" in accepted_no.content[0].text
    assert _job_count(runner) == 1


def test_confirmed_retry_asks_about_the_original_plan_and_records_elicitation(failing):
    service, runner, server = failing
    job = _finished_job(service, runner, approved_via="api")
    recorder = Recorder(content={"approve": True})
    result = session_call(server, "job_retry_failed", {"job_id": job.id}, callback=recorder)
    assert not result.isError, result.content[0].text
    assert recorder.messages == [confirmation_message(job.plan_hash)]
    retry = runner.store.get(result.structuredContent["id"])
    assert retry.retry_of == job.id
    assert retry.approved_via == "elicitation"
    assert result.structuredContent["approved_via"] == "elicitation"
    assert _job_count(runner) == 2


def test_cancelled_job_retry_also_needs_confirmation(stack):
    service, runner, server = stack
    job = _finished_job(service, runner, cancel=True)
    unable = session_call(server, "job_retry_failed", {"job_id": job.id})
    assert unable.isError and "APPROVAL_REQUIRED" in unable.content[0].text
    assert _job_count(runner) == 1
    accepted = session_call(server, "job_retry_failed", {"job_id": job.id}, approve=True)
    assert not accepted.isError, accepted.content[0].text
    assert accepted.structuredContent["retry_of"] == job.id
    assert accepted.structuredContent["approved_via"] == "elicitation"
    assert _job_count(runner) == 2


def test_retry_that_cannot_run_is_refused_before_asking(stack):
    service, runner, server = stack
    plan = service.plan(WeatherRequest.model_validate(REQUEST))
    unfinished = runner.store.submit(plan)
    recorder = Recorder(content={"approve": True})
    early = session_call(server, "job_retry_failed", {"job_id": unfinished.id}, callback=recorder)
    assert early.isError and "INVALID_REQUEST" in early.content[0].text
    runner.run(unfinished.id)
    assert runner.store.get(unfinished.id).state == "completed"
    nothing = session_call(server, "job_retry_failed", {"job_id": unfinished.id},
                           callback=recorder)
    assert nothing.isError and "NOTHING_TO_RETRY" in nothing.content[0].text
    assert recorder.messages == []
    assert _job_count(runner) == 1


def test_direct_retry_keeps_the_original_approval(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[FailingProvider()])
    runner = JobRunner(service)
    try:
        job = _finished_job(service, runner, approved_via="api")
        retry = runner.retry_failed(job.id)
        assert retry.retry_of == job.id and retry.approved_via == "api"
    finally:
        runner.close()
