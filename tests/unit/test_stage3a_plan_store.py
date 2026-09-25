"""Stored plan hashes are durable integrity references, not executable paths."""

import json

import pytest
from fastapi.testclient import TestClient
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.store import JobStore
from openepw.jobs.worker import JobRunner
from openepw.models import Location, OpenEPWError, WeatherPlan, WeatherRequest
from openepw.service import WeatherService


def _request():
    return WeatherRequest(locations=Location(lat=1, lon=0),
                          start="2024-01-01", end="2024-01-01")


def test_weather_plan_hash_survives_service_restart(tmp_path):
    first = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = first.plan(_request())
    second = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    restored = second.plan_store.get(plan.plan_hash)
    assert restored.plan_hash == plan.plan_hash
    assert restored.model_dump(mode="json") == plan.model_dump(mode="json")
    job = JobRunner(second, JobStore(tmp_path)).submit(plan.plan_hash)
    assert job.plan_hash == plan.plan_hash


def test_plan_store_rejects_bad_missing_and_tampered_hashes(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(_request())
    for bad in ("../other", "A" * 64, "f" * 63, "g" * 64):
        with pytest.raises(OpenEPWError, match="PLAN_NOT_FOUND"):
            service.plan_store.get(bad)
    with pytest.raises(OpenEPWError, match="PLAN_NOT_FOUND"):
        service.plan_store.get("0" * 64)
    path = tmp_path / "plans" / f"{plan.plan_hash}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["request"]["end"] = "2024-01-02"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OpenEPWError, match="PLAN_STALE"):
        service.plan_store.get(plan.plan_hash)


def test_empty_weather_plan_can_be_inspected_but_not_submitted(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    empty = WeatherPlan(request=_request())
    service.plan_store.put(empty)
    assert service.plan_store.get(empty.plan_hash).outputs == []
    with pytest.raises(OpenEPWError, match="NO_EXECUTABLE_OUTPUTS"):
        JobRunner(service, JobStore(tmp_path)).submit(empty.plan_hash)
    with pytest.raises(OpenEPWError, match="NO_EXECUTABLE_OUTPUTS"):
        JobStore(tmp_path).submit(empty)


def test_rest_weather_job_accepts_hash_or_inline_plan_but_not_both(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    app = create_app(service)
    with TestClient(app) as client:
        app.state.runner.enqueue = lambda job_id: None
        planned = client.post("/v1/weather/plan", json=_request().model_dump(mode="json"))
        assert planned.status_code == 200
        plan = planned.json()
        stored = client.post("/v1/weather/jobs", json={"plan_hash": plan["plan_hash"]})
        assert stored.status_code == 202
        assert stored.json()["plan_hash"] == plan["plan_hash"]
        inline = client.post("/v1/weather/jobs", json={"plan": plan})
        assert inline.status_code == 202
        assert inline.json()["plan_hash"] == plan["plan_hash"]
        assert client.post("/v1/weather/jobs", json={}).status_code == 422
        assert client.post("/v1/weather/jobs", json={"plan": plan,
                                                     "plan_hash": plan["plan_hash"]}).status_code == 422
        assert client.post("/v1/future/jobs", json={"plan_hash": plan["plan_hash"]}).status_code == 422
