import importlib.util
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

FIXTURE_SERVER = Path(__file__).resolve().parents[1] / "ui_server.py"


def fixture_app(root, monkeypatch):
    monkeypatch.setenv("OPENEPW_UI_TEST_ROOT", str(root))
    spec = importlib.util.spec_from_file_location("ui_fixture_server", FIXTURE_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


def test_sampled_partial_source_failure_keeps_successful_epws(tmp_path, monkeypatch):
    """REST boundary used by the browser Download stage for a sampled partial failure."""
    request = {
        "schema_version": "0.1",
        "missing_policy": "warn",
        "skip_feb_29": False,
        "locations": {
            "type": "Polygon",
            "coordinates": [
                [[-76.52, 42.42], [-76.4, 42.42], [-76.4, 42.48], [-76.52, 42.48], [-76.52, 42.42]]
            ],
        },
        "sampling": {"dx_km": 5, "dy_km": 5},
        "years": [2024],
        "product": "amy",
    }
    with TestClient(fixture_app(tmp_path, monkeypatch)) as client:
        preview = client.post("/v1/spatial/preview", json=request)
        assert preview.status_code == 200
        points = preview.json()["total_count"]
        assert points >= 2

        discovery = client.post("/v1/weather/discover", json=request).json()
        datasets = {
            (c["source"]["provider"], c["source"]["dataset"]) for c in discovery["candidates"]
        }
        assert ("cds", "reanalysis-era5-single-levels") in datasets
        request["dataset_selections"] = [
            {"provider": provider, "dataset": dataset} for provider, dataset in sorted(datasets)
        ]

        plan = client.post("/v1/weather/plan", json=request)
        assert plan.status_code == 200
        job = client.post(
            "/v1/weather/jobs", json={"plan": plan.json(), "idempotency_key": "partial"}
        )
        assert job.status_code == 202
        job_id = job.json()["id"]

        deadline = time.monotonic() + 60
        while (result := client.get(f"/v1/jobs/{job_id}").json())["state"] in {
            "queued",
            "running",
        }:
            assert time.monotonic() < deadline, result
            time.sleep(0.05)

        assert result["state"] == "partially_completed"
        assert result["total"] == 2 * points
        assert 0 < result["failed"] < points
        assert result["completed"] == result["total"] - result["failed"]
        assert len(result["bundle"]["weather"]) == result["completed"]
        assert all(issue["code"] == "SOURCE_UNAVAILABLE" for issue in result["errors"])
        listed = client.get("/v1/jobs").json()["items"]
        assert [(item["id"], item["state"]) for item in listed] == [(job_id, "partially_completed")]

        # Retrying submits only the missing outputs; the synthetic source fails again.
        retry = client.post(f"/v1/jobs/{job_id}/retry", json={"idempotency_key": "retry"})
        assert retry.status_code == 202
        assert retry.json()["total"] == result["failed"]
        assert retry.json()["kind"] == "weather"
        missing = client.post("/v1/jobs/unknown/retry")
        assert missing.status_code == 404
