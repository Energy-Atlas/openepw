import pytest
from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.jobs.store import JobStore
from openepw.jobs.worker import JobRunner, subplan
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


def test_durable_idempotency_completion_and_restart(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    store = JobStore(tmp_path)
    job = store.submit(plan, "same")
    assert store.submit(plan, "same").id == job.id
    JobRunner(service, store).run(job.id)
    result = JobStore(tmp_path).get(job.id)
    assert result.state == "completed"
    assert result.completed == 1
    assert result.bundle.weather
    JobRunner(service, store).run(job.id)
    assert store.get(job.id).bundle.bundle_id == result.bundle.bundle_id


def test_cancel_before_execution(tmp_path):
    import json

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    store.cancel(job.id)
    JobRunner(service, store).run(job.id)
    final = store.get(job.id)
    assert final.state == "cancelled"
    assert service.providers["station"].calls == 0
    _, path = service.artifacts.resolve(final.bundle.manifest.id)
    assert json.loads(path.read_text())["batch_rows"][0]["status"] == "cancelled"


def test_restart_resumes_after_verified_completed_item(tmp_path):
    provider = StationProvider()
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[provider])
    plan = service.plan(
        WeatherRequest(
            locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
            start="2024-01-01",
            end="2024-01-01",
        )
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    first = plan.outputs[0]
    prior = service.execute(subplan(plan, [first]))
    store.complete_item(job.id, first.id, prior)
    job.state = "running"
    store.save(job)
    JobRunner(service, JobStore(tmp_path)).run(job.id)
    final = store.get(job.id)
    assert final.state == "completed"
    assert provider.calls == 2
    assert prior.weather[0].id in {a.id for a in final.bundle.weather}


def test_future_ensemble_progress_counts_artifacts(tmp_path):
    import json

    from test_epw import synthetic
    from test_future import signal

    from openepw.epw import write_epw
    from openepw.models import FutureRequest

    base = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), base)
    sig = tmp_path / "signals.json"
    signals = [
        signal().model_dump(mode="json"),
        signal().model_copy(update={"member": "r2"}).model_dump(mode="json"),
    ]
    sig.write_text(json.dumps(signals))
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"))
    plan = service.plan_future(
        FutureRequest(
            baseline=str(base),
            signals=str(sig),
            reference_period=(1985, 2014),
            target_year=2050,
            climate_scenario="ssp245",
            profile="ensemble",
        )
    )
    store = JobStore(service.config.data_root)
    job = store.submit(plan)
    JobRunner(service, store).run(job.id)
    final = store.get(job.id)
    assert final.state == "completed"
    assert final.completed == final.total == 2
    assert final.kind == "future"


def test_legacy_job_kind_is_recovered_from_stored_plan(tmp_path):
    import json

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    legacy_plan = plan.model_dump(mode="json")
    legacy_plan["kind"] = "future"
    with store.connect() as db:
        db.execute(
            "UPDATE jobs SET plan=?, job=? WHERE id=?",
            (json.dumps(legacy_plan), job.model_dump_json(), job.id),
        )
    assert store.get(job.id).kind == "future"


def test_job_connections_close_after_transaction(tmp_path):
    import sqlite3

    import pytest

    store = JobStore(tmp_path)
    with store.connect() as db:
        assert db.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")


def test_job_items_use_output_identity_for_shared_fetch(tmp_path):
    import json

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    request = WeatherRequest(
        locations=[Location(lat=1, lon=0), Location(lat=12, lon=0)],
        start="2024-01-01",
        end="2024-01-01",
    )
    plan = service.plan(request)
    assert len(plan.tasks) == 1
    store = JobStore(tmp_path)
    job = store.submit(plan)
    JobRunner(service, store).run(job.id)
    final = store.get(job.id)
    assert final.state == "completed"
    assert final.completed == final.total == 2
    assert set(store.items(job.id)) == {o.id for o in plan.outputs}
    _, manifest_path = service.artifacts.resolve(final.bundle.manifest.id)
    outputs = json.loads(manifest_path.read_text())["outputs"]
    assert {o["output_id"] for o in outputs} == {o.id for o in plan.outputs}
    assert {tuple(o["requested_locations"]) for o in outputs} == {
        (o.requested_location_id,) for o in plan.outputs
    }


def test_running_job_persists_completed_and_failed_counts(tmp_path):
    from openepw.models import OpenEPWError

    class SometimesFails(StationProvider):
        def fetch(self, task, http):
            if task.source.identity == "2":
                raise OpenEPWError("SOURCE_FAILED", "Synthetic failure")
            return super().fetch(task, http)

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[SometimesFails()])
    plan = service.plan(
        WeatherRequest(
            locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
            start="2024-01-01",
            end="2024-01-01",
        )
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    snapshots = []
    original = store.save

    def recording_save(value):
        snapshots.append((value.state, value.completed, value.failed))
        original(value)

    store.save = recording_save
    JobRunner(service, store).run(job.id)
    assert ("running", 1, 1) in snapshots
    assert snapshots[-1] == ("partially_completed", 1, 1)


def test_running_job_counts_an_output_that_raises_before_bundling(tmp_path):
    from openepw.models import OpenEPWError

    class FailsBeforeBundle(WeatherService):
        def execute(self, plan, **kwargs):
            if plan.outputs[0].requested_location_id == Location(lat=2, lon=0).key:
                raise OpenEPWError("SOURCE_FAILED", "Synthetic failure")
            return super().execute(plan, **kwargs)

    service = FailsBeforeBundle(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(
            locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
            start="2024-01-01",
            end="2024-01-01",
        )
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    snapshots = []
    original_save = store.save

    def recording_save(value):
        snapshots.append((value.state, value.completed, value.failed))
        original_save(value)

    store.save = recording_save
    JobRunner(service, store).run(job.id)
    assert ("running", 1, 1) in snapshots


def test_retry_failed_uses_only_missing_output_identities(tmp_path):
    import pytest

    from openepw.models import OpenEPWError

    class RecoveringProvider(StationProvider):
        name = "recovering"
        fail = True

        def fetch(self, task, http):
            if self.fail:
                raise OpenEPWError("SOURCE_FAILED", "Synthetic failure")
            return super().fetch(task, http)

    recovering = RecoveringProvider()
    service = WeatherService(
        RuntimeConfig(data_root=tmp_path), providers=[StationProvider(), recovering]
    )
    plan = service.plan(
        WeatherRequest(
            locations=Location(lat=1, lon=0),
            start="2024-01-01",
            end="2024-01-01",
            dataset_selections=[
                {"provider": "station", "dataset": "synthetic"},
                {"provider": "recovering", "dataset": "synthetic"},
            ],
        )
    )
    store = JobStore(tmp_path)
    runner = JobRunner(service, store)
    original = store.submit(plan)
    runner.run(original.id)
    initial = store.get(original.id)
    assert initial.state == "partially_completed"
    successful_id = next(key for key, bundle in store.items(original.id).items() if bundle.weather)
    original_artifact_id = initial.bundle.weather[0].id
    runner.enqueue = lambda job_id: None
    retry = runner.retry_failed(original.id)
    assert retry.retry_of == original.id
    assert retry.total == 1
    retried = store.plan(retry.id)
    assert [o.id for o in retried.outputs] == [o.id for o in plan.outputs if o.id != successful_id]
    recovering.fail = False
    runner.run(retry.id)
    assert store.get(retry.id).state == "completed"
    assert store.get(original.id).bundle.weather[0].id == original_artifact_id
    with pytest.raises(OpenEPWError, match="NOTHING_TO_RETRY"):
        runner.retry_failed(retry.id)


@pytest.mark.parametrize("legacy", [False, True])
def test_future_retry_emits_only_missing_member(tmp_path, legacy):
    import json

    from test_epw import synthetic
    from test_future import signal

    from openepw.epw import write_epw
    from openepw.jobs.worker import subplan
    from openepw.models import FutureRequest, WeatherPlan

    base = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), base)
    signals = tmp_path / "signals.json"
    signals.write_text(
        json.dumps(
            [
                signal().model_dump(mode="json"),
                signal().model_copy(update={"member": "r2"}).model_dump(mode="json"),
            ]
        )
    )
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"))
    plan = service.plan_future(
        FutureRequest(
            baseline=str(base),
            signals=str(signals),
            reference_period=(1985, 2014),
            target_year=2050,
            climate_scenario="ssp245",
            profile="ensemble",
        )
    )
    if legacy:
        raw = plan.model_dump(mode="json", exclude={"plan_hash"})
        for output in raw["outputs"]:
            output.pop("id", None)
            output.pop("index", None)
        plan = WeatherPlan.model_validate(raw)
    first = service.execute(subplan(plan, [plan.outputs[0]]))
    store = JobStore(service.config.data_root)
    original = store.submit(plan)
    store.complete_item(original.id, "future", first)
    original.state = "partially_completed"
    original.completed = 1
    original.failed = 1
    original.bundle = first
    store.save(original)
    runner = JobRunner(service, store)
    runner.enqueue = lambda job_id: None
    retry = runner.retry_failed(original.id)
    assert [o.id for o in store.plan(retry.id).outputs] == [plan.outputs[1].id]
    runner.run(retry.id)
    assert store.get(retry.id).state == "completed"
    assert len(store.get(retry.id).bundle.weather) == 1


def test_plan_unavailability_issues_reach_final_job_bundle(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(
            locations=Location(lat=1, lon=0),
            start="2024-01-01",
            end="2024-01-01",
            dataset_selections=[
                {"provider": "station", "dataset": "synthetic"},
                {"provider": "missing", "dataset": "unknown"},
            ],
        )
    )
    assert sum(issue.code == "DATASET_UNAVAILABLE" for issue in plan.issues) == 1
    store = JobStore(tmp_path)
    job = store.submit(plan)
    JobRunner(service, store).run(job.id)
    final = store.get(job.id)
    assert sum(issue.code == "DATASET_UNAVAILABLE" for issue in final.bundle.issues) == 1


def test_future_retry_keeps_verified_members_when_one_artifact_is_corrupt(tmp_path):
    import json

    from test_epw import synthetic
    from test_future import signal

    from openepw.epw import write_epw
    from openepw.models import FutureRequest

    base = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), base)
    signals = tmp_path / "signals.json"
    signals.write_text(
        json.dumps(
            [
                signal().model_dump(mode="json"),
                signal().model_copy(update={"member": "r2"}).model_dump(mode="json"),
            ]
        )
    )
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"))
    plan = service.plan_future(
        FutureRequest(
            baseline=str(base),
            signals=str(signals),
            reference_period=(1985, 2014),
            target_year=2050,
            climate_scenario="ssp245",
            profile="ensemble",
        )
    )
    full = service.execute(plan)
    store = JobStore(service.config.data_root)
    original = store.submit(plan)
    store.complete_item(original.id, "future", full)
    original.state = "completed"
    original.completed = original.total
    original.bundle = full
    store.save(original)
    (service.config.data_root / full.weather[0].path).write_bytes(b"corrupt-test-artifact")
    runner = JobRunner(service, store)
    runner.enqueue = lambda job_id: None
    retry = runner.retry_failed(original.id)
    assert [o.id for o in store.plan(retry.id).outputs] == [plan.outputs[0].id]
