"""The outputs of a weather job, from its verified manifest: the place, year and status of each."""

import time

import pytest
from fastapi.testclient import TestClient

from openepw.agent.evals.stubs import stub_service
from openepw.jobs.outputs import job_outputs
from openepw.jobs.worker import TERMINAL, JobRunner
from openepw.models import OpenEPWError, WeatherRequest

ITHACA = {"lat": 42.44, "lon": -76.5, "name": "Ithaca, New York, United States"}
BOSTON = {"lat": 42.36, "lon": -71.06, "name": "Boston, Massachusetts, United States"}


def request(years=(2016, 2017), places=(ITHACA, BOSTON)):
    return WeatherRequest.model_validate({
        "locations": list(places), "product": "historical", "years": list(years),
        "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]})


def finish(runner, job_id, seconds=60):
    deadline = time.monotonic() + seconds
    while runner.store.get(job_id).state not in TERMINAL:
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.05)
    return runner.store.get(job_id)


@pytest.fixture
def runner(tmp_path):
    runner = JobRunner(stub_service(tmp_path, fail_near=[(42.36, -71.06)]))
    yield runner
    runner.close()


def test_rows_name_place_year_status_and_artifact(runner):
    plan = runner.service.plan(request())
    job = runner.submit(plan)
    pending = job_outputs(runner, job.id)
    assert pending["counts"] == {"pending": 4} or finish(runner, job.id)   # the stub may finish first
    finish(runner, job.id)
    result = job_outputs(runner, job.id)
    assert result["state"] == "partially_completed" and result["total"] == 4
    assert result["counts"] == {"succeeded": 2, "failed": 2}
    by_place = {(row["place"]["name"].split(",")[0], row["year"]): row for row in result["outputs"]}
    assert set(by_place) == {("Ithaca", 2016), ("Ithaca", 2017), ("Boston", 2016), ("Boston", 2017)}
    ithaca, boston = by_place["Ithaca", 2016], by_place["Boston", 2016]
    assert ithaca["status"] == "succeeded" and len(ithaca["artifact_id"]) == 32
    assert ithaca["filename"].endswith(".epw") and ithaca["bytes"] > 0 and len(ithaca["sha256"]) == 64
    assert (ithaca["provider"], ithaca["dataset"], ithaca["product"]) == ("openmeteo", "era5", "historical")
    weather = {ref.id for ref in runner.store.get(job.id).bundle.weather}
    assert {row["artifact_id"] for row in result["outputs"] if row["artifact_id"]} <= weather
    # A failed output names no file, and keeps its recorded issue codes.
    assert boston["status"] == "failed" and boston["artifact_id"] is None and boston["filename"] is None
    assert "PROVIDER_ERROR" in boston["issue_codes"]


def test_a_retry_lists_only_the_outputs_it_retried(runner):
    job = finish(runner, runner.submit(runner.service.plan(request())).id)
    runner.service.providers["openmeteo"].fail_near.clear()            # the outage is over
    retry = finish(runner, runner.retry_failed(job.id).id)
    result = job_outputs(runner, retry.id)
    assert result["retry_of"] == job.id and result["plan_hash"] == retry.plan_hash
    assert result["counts"] == {"succeeded": 2}
    assert {row["place"]["name"].split(",")[0] for row in result["outputs"]} == {"Boston"}


def test_a_typical_or_partial_period_has_no_year():
    from openepw.jobs.outputs import _year
    assert _year("2016-01-01", "2016-12-31") == 2016
    assert _year("2016-01-01", "2016-06-30") is None
    assert _year(None, None) is None


def test_unknown_job_is_job_not_found(runner):
    with pytest.raises(OpenEPWError, match="Unknown job"):
        job_outputs(runner, "0" * 32)


def test_rest_and_mcp_return_the_same_rows(tmp_path):
    import asyncio
    import json

    from openepw.api.app import create_app
    from openepw.mcp.server import create_server

    service = stub_service(tmp_path)
    app = create_app(service)
    with TestClient(app) as client:
        runner = app.state.runner
        job = finish(runner, runner.submit(service.plan(request(years=(2018,), places=(ITHACA,)))).id)
        rest = client.get(f"/v1/jobs/{job.id}/outputs").json()
        server = create_server(service, runner=runner)
        result = asyncio.run(server.call_tool("job_outputs", {"job_id": job.id}))
        assert json.loads(json.dumps(result.structuredContent)) == rest
        assert "Ithaca" in result.content[0].text and "succeeded" in result.content[0].text
        assert rest["outputs"][0]["year"] == 2018
        assert client.get("/v1/jobs/" + "0" * 32 + "/outputs").status_code == 404
