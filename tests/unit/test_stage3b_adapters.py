"""REST and CLI expose future baseline IDs and stored plans without raw weather tables."""

import importlib
import json

from fastapi.testclient import TestClient
from test_epw import synthetic
from test_future import signal

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.epw import write_epw
from openepw.epw.writer import epw_bytes
from openepw.service import WeatherService


def _signals(tmp_path):
    path = tmp_path / "signals.json"
    path.write_text(json.dumps([signal().model_dump(mode="json")]))
    return path


def _future_body(baseline, signals):
    return {"baseline": baseline, "signals": signals,
            "reference_period": [1985, 2014], "climate_period": [2036, 2065],
            "climate_scenario": "ssp245"}


def test_rest_upload_plan_hash_job_and_artifact(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    signals = service.artifacts.write("e" * 32, "signals.json",
                                      _signals(tmp_path).read_bytes(), "signals")
    app = create_app(service)
    with TestClient(app) as client:
        upload = client.post("/v1/artifacts", files={
            "file": ("user.epw", epw_bytes(synthetic(2023, 8760)), "text/plain")})
        assert upload.status_code == 201
        ref = upload.json()
        assert ref["registration_route"] == "upload"
        request = _future_body(ref["id"], signals.id)
        plan_response = client.post("/v1/future/plan", json=request)
        assert plan_response.status_code == 200
        plan = plan_response.json()
        assert plan["baseline_ref"]["artifact_id"] == ref["id"]
        assert plan["baseline_ref"]["origin"] == "user_provided"
        assert "dry_bulb" not in plan_response.text
        app.state.runner.enqueue = lambda _: None
        job_response = client.post("/v1/future/jobs", json={"plan_hash": plan["plan_hash"]})
        assert job_response.status_code == 202
        job_id = job_response.json()["id"]
        app.state.runner.run(job_id)
        final = client.get(f"/v1/jobs/{job_id}").json()
        assert final["state"] == "completed"
        output = final["bundle"]["weather"][0]
        assert client.get(f"/v1/artifacts/{output['id']}").status_code == 200
        assert "dry_bulb" not in job_response.text
        fetched = service.artifacts.write("f" * 32, "fetched.epw",
                                          epw_bytes(synthetic(2023, 8760)), "weather")
        source_manifest = service.artifacts.json("f" * 32, "manifest.json", {
            "outputs": [{"artifact_id": fetched.id, "output_id": "a" * 64,
                         "lineage": {}}]}, "manifest")
        service.artifacts.json("f" * 32, "qc.json", [], "qc")
        fetched_plan = client.post("/v1/future/plan", json={
            **request, "baseline": fetched.id})
        assert fetched_plan.status_code == 200
        assert fetched_plan.json()["baseline_ref"]["origin"] == "weather_output"
        assert fetched_plan.json()["baseline_ref"]["source_manifest_id"] == source_manifest.id
        assert client.post("/v1/future/plan", json={
            **request, "baseline": str(tmp_path / "user.epw")}).status_code == 400


def test_cli_register_local_baseline_plan_then_execute_hash(tmp_path, monkeypatch, capsys):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    baseline = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), baseline)
    cli = importlib.import_module("openepw.cli.main")
    monkeypatch.setattr(cli, "WeatherService", lambda config: service)
    assert cli.main(["--data-root", str(tmp_path / "store"),
                     "register-baseline", str(baseline)]) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered["registration_route"] == "allowlisted_path"
    request_file = tmp_path / "future.json"
    request_file.write_text(json.dumps(_future_body(registered["id"],
                                                    str(_signals(tmp_path)))))
    assert cli.main(["--data-root", str(tmp_path / "store"),
                     "future-plan", str(request_file)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["baseline_ref"]["artifact_id"] == registered["id"]
    assert cli.main(["--data-root", str(tmp_path / "store"),
                     "execute", plan["plan_hash"]]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["weather"]) == 1
