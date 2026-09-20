import pytest
from test_batch import StationProvider

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.store import JobStore
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


def test_job_pagination_and_schema(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    with TestClient(create_app(service)) as client:
        store = JobStore(tmp_path)
        ids = {store.submit(plan).id for _ in range(3)}
        first = client.get("/v1/jobs?limit=2").json()
        second = client.get("/v1/jobs", params={"limit": 2, "cursor": first["next_cursor"]}).json()
        assert {j["id"] for j in first["items"] + second["items"]} == ids
        assert second["next_cursor"] is None
        assert client.get("/v1/jobs?limit=101").status_code == 422
        assert client.get("/v1/jobs?cursor=garbage").status_code == 400
        schema = client.get("/openapi.json").json()
        assert (
            "$ref"
            in schema["paths"]["/v1/weather/plan"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
        )


def test_signal_upload_and_preview(tmp_path):
    from test_epw import synthetic
    from test_future import signal

    from openepw.epw.writer import epw_bytes

    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    with TestClient(create_app(service)) as client:
        assert client.post("/v1/artifacts/signals", json=[{}]).status_code == 422
        result = client.post("/v1/artifacts/signals", json=[signal().model_dump(mode="json")])
        assert result.status_code == 201
        assert result.json()["role"] == "signals"
        upload = client.post(
            "/v1/artifacts", files={"file": ("test.epw", epw_bytes(synthetic()))}
        ).json()
        result = client.get(f"/v1/artifacts/{upload['id']}/preview").json()
        assert result["total_rows"] == 24
        assert client.get(f"/v1/artifacts/{upload['id']}/preview?limit=169").status_code == 422
