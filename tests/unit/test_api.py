import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def test_api_plan_parity_and_auth(tmp_path):
    service = WeatherService(
        RuntimeConfig(data_root=tmp_path, bearer_token="test-token"), providers=[StationProvider()]
    )
    with TestClient(create_app(service, remote=True)) as client:
        body = {"locations": {"lat": 1, "lon": 0}, "start": "2024-01-01", "end": "2024-01-01"}
        assert client.post("/v1/weather/plan", json=body).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        response = client.post("/v1/weather/plan", json=body, headers=headers)
        assert response.status_code == 200
        assert len(response.json()["tasks"]) == 1
        bad = client.post(
            "/v1/weather/plan", json={**body, "api_key": "must-not-echo"}, headers=headers
        )
        assert bad.status_code == 422
        assert "must-not-echo" not in bad.text
        assert client.get("/v1/artifacts/not-valid", headers=headers).status_code == 400


def test_remote_without_token_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_app(WeatherService(RuntimeConfig(data_root=tmp_path)), remote=True)
