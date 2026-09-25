import asyncio
import base64
import json
import time

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from test_batch import StationProvider
from test_epw import synthetic
from test_future import signal
from test_noaa_gap_output import _execute

from openepw.config import RuntimeConfig
from openepw.epw.writer import epw_bytes
from openepw.mcp.server import create_server
from openepw.service import WeatherService


def _call(server, name, **kwargs):
    return asyncio.run(server.call_tool(name, kwargs))[1]


def test_upload_path_controls_future_plan_and_durable_job(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    server = create_server(service, allowed_roots=[tmp_path / "inputs"])
    body = epw_bytes(synthetic(2023, 8760))
    uploaded = _call(server, "baseline_upload", content_base64=base64.b64encode(body).decode(),
                     filename="user.epw")
    assert uploaded["rows"] == 8760
    assert uploaded["input_qc"] == []
    assert "content_base64" not in str(uploaded)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    file = inputs / "user.epw"
    file.write_bytes(body)
    registered = _call(server, "baseline_register_path", path=str(file))
    assert registered["artifact_id"] == uploaded["artifact_id"]
    with pytest.raises(ToolError, match="ACCESS_DENIED"):
        _call(server, "baseline_register_path", path=str(tmp_path / "outside.epw"))
    with pytest.raises(ToolError, match="INVALID_BASELINE"):
        _call(server, "baseline_upload", content_base64="bad!")

    signals = service.artifacts.write(
        "a" * 32, "signals.json",
        json.dumps([signal().model_dump(mode="json")]).encode(), "signals")
    request = {
        "baseline": uploaded["artifact_id"], "signals": signals.id,
        "reference_period": [1985, 2014], "climate_period": [2036, 2065],
        "climate_scenario": "ssp245",
    }
    plan = _call(server, "future_plan", request=request)
    assert plan["baseline_ref"]["origin"] == "user_provided"
    assert plan["plan_hash"] == service.plan_store.get(plan["plan_hash"]).plan_hash
    submitted = _call(server, "future_submit", plan_hash=plan["plan_hash"],
                      idempotency_key="mcp-future-test")
    repeated = _call(server, "future_submit", plan_hash=plan["plan_hash"],
                     idempotency_key="mcp-future-test")
    assert repeated["id"] == submitted["id"]
    for _ in range(100):
        job = _call(server, "job_inspect", job_id=submitted["id"])
        if job["state"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert job["state"] == "completed"
    assert job["artifacts"]["weather_count"] == 1
    inspected = _call(server, "artifact_inspect",
                      artifact_id=job["artifacts"]["weather"][0])
    assert inspected["role"] == "weather"
    assert inspected["uri"].startswith("weather://artifacts/")


@pytest.mark.parametrize("policy", ["warn", "error"])
def test_noaa_gap_remains_visible_in_mcp_artifact_summary(tmp_path, policy):
    bundle = _execute(tmp_path / "store", policy)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    server = create_server(service)
    manifest = _call(server, "artifact_inspect", artifact_id=bundle.manifest.id)
    assert manifest["simulation_ready"] is False
    assert manifest["batch_rows"][0]["status"] == (
        "succeeded" if policy == "warn" else "failed")
    assert "MISSING_CRITICAL_VARIABLE" in manifest["batch_rows"][0]["issue_codes"]
    if policy == "warn":
        assert len(bundle.weather) == 1
        weather = _call(server, "artifact_inspect", artifact_id=bundle.weather[0].id)
        assert weather["simulation_ready"] is False
        assert "MISSING_CRITICAL_VARIABLE" in weather["qc_issue_codes"]
    else:
        assert bundle.weather == []


def test_weather_plan_submit_inspect_and_compact_export(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    server = create_server(service)
    request = {"locations": {"lat": 1, "lon": 0},
               "start": "2024-01-01", "end": "2024-01-01"}
    plan = _call(server, "weather_plan", request=request)
    inspected_plan = _call(server, "plan_inspect", plan_hash=plan["plan_hash"])
    assert inspected_plan["plan_hash"] == plan["plan_hash"]
    assert inspected_plan["outputs"][0]["id"]
    assert inspected_plan["selected_candidates"]
    submitted = _call(server, "weather_submit", plan_hash=plan["plan_hash"])
    for _ in range(100):
        job = _call(server, "job_inspect", job_id=submitted["id"])
        if job["state"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert job["state"] == "completed"
    assert job["artifacts"]["weather_count"] == 1
    assert job["completed_output_ids"]
    exported = _call(server, "weather_export_compact", job_id=job["id"])
    assert _call(server, "artifact_inspect", artifact_id=exported["artifact_id"])[
        "sha256"] == exported["sha256"]
