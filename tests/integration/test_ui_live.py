"""Opt-in real service checks through the HTTP contracts used by the UI."""

import time
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


@pytest.mark.live
def test_live_ui_retrieval_and_future():
    service = WeatherService(RuntimeConfig(data_root=".local/live-cmip", timeout=120))
    with TestClient(create_app(service)) as client:

        def execute(kind, request):
            response = client.post(f"/v1/{kind}/plan", json=request)
            assert response.status_code == 200
            plan = response.json()
            response = client.post(
                f"/v1/{kind}/jobs", json={"plan": plan, "idempotency_key": str(uuid.uuid4())}
            )
            assert response.status_code == 202
            job = response.json()
            deadline = time.monotonic() + 300
            while job["state"] in ("queued", "running") and time.monotonic() < deadline:
                time.sleep(0.5)
                job = client.get("/v1/jobs/" + job["id"]).json()
            assert job["state"] == "completed", job["state"]
            artifact = job["bundle"]["weather"][0]
            preview = client.get(f"/v1/artifacts/{artifact['id']}/preview").json()
            assert preview["total_rows"] == 8760
            assert len(preview["rows"]) == 168
            assert preview["rows"][0]["values"]["dry_bulb"] is not None
            assert client.get(f"/v1/artifacts/{artifact['id']}").status_code == 200
            return artifact

        baseline = execute(
            "weather",
            {
                "locations": {"lat": 34.65, "lon": -87.765},
                "providers": ["openmeteo"],
                "years": [2023],
            },
        )
        execute(
            "future",
            {
                "baseline": baseline["id"],
                "method": "morph",
                "target_year": 2050,
                "reference_period": [1985, 2014],
                "climate_scenario": "ssp245",
                "profile": "typical",
            },
        )
