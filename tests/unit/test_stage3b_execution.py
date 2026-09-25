"""Future members survive partial failure, cancellation and retry independently."""

import importlib
import json

from test_epw import synthetic
from test_future import signal

from openepw.config import RuntimeConfig
from openepw.epw import read_epw, write_epw
from openepw.jobs.worker import JobRunner, subplan
from openepw.models import FutureRequest, OpenEPWError
from openepw.service import WeatherService


def _plan(tmp_path):
    baseline = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), baseline)
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps([
        signal().model_dump(mode="json"),
        signal().model_copy(update={"member": "r2"}).model_dump(mode="json"),
    ]))
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    ref = service.register_baseline(baseline)
    plan = service.plan_future(FutureRequest(
        baseline=ref.id, signals=str(signals), reference_period=(1985, 2014),
        climate_period=(2036, 2065), climate_scenario="ssp245", profile="ensemble"))
    return service, plan


def test_future_job_persists_each_member_and_reuses_source_result(tmp_path, monkeypatch):
    service, plan = _plan(tmp_path)
    module = importlib.import_module("openepw.generation.morph")
    original = module.morph
    calls = []
    fail = {"r2": True}

    def controlled(baseline, selected):
        calls.append(selected.member)
        if selected.member == "r2" and fail["r2"]:
            raise OpenEPWError("INVALID_CLIMATE_SIGNAL", "Synthetic invalid member")
        return original(baseline, selected)

    monkeypatch.setattr(module, "morph", controlled)
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan)
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "partially_completed"
    assert final.completed == 1
    assert calls == ["r1", "r2"]
    assert set(runner.store.items(job.id)) == {output.id for output in plan.outputs}
    assert len(final.bundle.weather) == 1
    _, path = service.artifacts.resolve(final.bundle.manifest.id)
    manifest = json.loads(path.read_text())
    assert [row["status"] for row in manifest["future_rows"]] == [
        "succeeded", "failed"]
    assert manifest["future_rows"][0]["baseline_artifact_id"] == plan.baseline_ref.artifact_id
    assert len(read_epw(service.artifacts.resolve(final.bundle.weather[0].id)[1]).data) == 8760
    fail["r2"] = False
    retry = runner.retry_failed(job.id)
    assert [output.id for output in runner.store.plan(retry.id).outputs] == [
        plan.outputs[1].id]
    runner.run(retry.id)
    assert runner.store.get(retry.id).state == "completed"
    assert final.bundle.weather[0].id == runner.store.get(job.id).bundle.weather[0].id
    runner.close()


def test_future_cancel_after_one_member_retains_its_artifact(tmp_path):
    service, plan = _plan(tmp_path)
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan)
    original = runner.store.complete_item

    def cancel_after_first(job_id, name, bundle):
        original(job_id, name, bundle)
        runner.store.cancel(job_id)

    runner.store.complete_item = cancel_after_first
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "cancelled"
    assert final.completed == 1
    _, path = service.artifacts.resolve(final.bundle.manifest.id)
    rows = json.loads(path.read_text())["future_rows"]
    assert [row["status"] for row in rows] == ["succeeded", "cancelled"]
    runner.close()


def test_future_restart_keeps_verified_member_and_refetches_corrupt_one(tmp_path):
    service, plan = _plan(tmp_path)
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.store.submit(plan)
    first, second = plan.outputs
    first_bundle = service.execute(subplan(plan, [first]))
    second_bundle = service.execute(subplan(plan, [second]))
    runner.store.complete_item(job.id, first.id, first_bundle)
    runner.store.complete_item(job.id, second.id, second_bundle)
    (service.config.data_root / second_bundle.weather[0].path).write_bytes(b"corrupt")
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "completed"
    ids = {ref.id for ref in final.bundle.weather}
    assert first_bundle.weather[0].id in ids
    assert second_bundle.weather[0].id not in ids
    assert len(ids) == 2
    runner.close()


def test_shared_upstream_failure_marks_each_member_without_weather(tmp_path):
    service, plan = _plan(tmp_path)
    _, signals_path = service.artifacts.resolve(plan.request.signals)
    signals_path.write_bytes(b"corrupt")
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan)
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "failed"
    assert final.bundle.weather == []
    _, path = service.artifacts.resolve(final.bundle.manifest.id)
    rows = json.loads(path.read_text())["future_rows"]
    assert [row["status"] for row in rows] == ["failed", "failed"]
    assert all(row["issue_codes"] == ["INVALID_ARTIFACT"] for row in rows)
    runner.close()
