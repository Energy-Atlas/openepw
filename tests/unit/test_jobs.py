from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.jobs.store import JobStore
from openepw.jobs.worker import JobRunner
from openepw.models import Location, OpenEPWError, WeatherRequest
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
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    store.cancel(job.id)
    JobRunner(service, store).run(job.id)
    assert store.get(job.id).state == "cancelled"
    assert service.providers["station"].calls == 0


def test_selected_dataset_failure_keeps_successful_artifact_and_counts_partial_job(tmp_path):
    class FailingProvider(StationProvider):
        name = "broken"

        def fetch(self, task, http):
            raise OpenEPWError("SOURCE_FAILED", "Synthetic source failure")

    service = WeatherService(
        RuntimeConfig(data_root=tmp_path), providers=[StationProvider(), FailingProvider()]
    )
    plan = service.plan(
        WeatherRequest(
            locations=Location(lat=1, lon=0),
            start="2024-01-01",
            end="2024-01-01",
            dataset_selections=[
                {"provider": "station", "dataset": "synthetic"},
                {"provider": "broken", "dataset": "synthetic"},
            ],
        )
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)

    JobRunner(service, store).run(job.id)

    result = store.get(job.id)
    assert result.state == "partially_completed"
    assert result.total == 2
    assert result.completed == 1
    assert result.failed == 1
    assert len(result.bundle.weather) == 1
    assert any(issue.code == "SOURCE_FAILED" for issue in result.errors)


def test_running_job_persists_completed_and_failed_progress(tmp_path):
    class FailingProvider(StationProvider):
        name = "broken"

        def fetch(self, task, http):
            raise OpenEPWError("SOURCE_FAILED", "Synthetic source failure")

    service = WeatherService(
        RuntimeConfig(data_root=tmp_path), providers=[StationProvider(), FailingProvider()]
    )
    plan = service.plan(
        WeatherRequest(
            locations=Location(lat=1, lon=0),
            start="2024-01-01",
            end="2024-01-01",
            dataset_selections=[
                {"provider": "station", "dataset": "synthetic"},
                {"provider": "broken", "dataset": "synthetic"},
            ],
        )
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    snapshots = []
    save = store.save

    def record(saved):
        snapshots.append((saved.state, saved.completed, saved.failed))
        save(saved)

    store.save = record
    JobRunner(service, store).run(job.id)

    # Progress is saved after each output, before the job reaches a terminal state.
    assert snapshots[0] == ("running", 0, 0)
    assert snapshots[1] in {("running", 1, 0), ("running", 0, 1)}
    assert snapshots[2] == ("running", 1, 1)
    assert snapshots[-1] == ("partially_completed", 1, 1)


def test_retry_failed_submits_only_the_outputs_a_job_did_not_produce(tmp_path):
    import pytest

    class FailingProvider(StationProvider):
        name = "broken"

        def fetch(self, task, http):
            raise OpenEPWError("SOURCE_FAILED", "Synthetic source failure")

    service = WeatherService(
        RuntimeConfig(data_root=tmp_path), providers=[StationProvider(), FailingProvider()]
    )
    plan = service.plan(
        WeatherRequest(
            locations=Location(lat=1, lon=0),
            start="2024-01-01",
            end="2024-01-01",
            dataset_selections=[
                {"provider": "station", "dataset": "synthetic"},
                {"provider": "broken", "dataset": "synthetic"},
            ],
        )
    )
    store = JobStore(tmp_path)
    runner = JobRunner(service, store)
    job = store.submit(plan)
    runner.run(job.id)
    assert store.get(job.id).state == "partially_completed"
    runner.enqueue = lambda job_id: None  # run synchronously below

    retry = runner.retry_failed(job.id, "retry-1")
    retried = store.plan(retry.id)
    assert retry.total == 1
    assert retry.retry_of == job.id
    assert JobStore(tmp_path).get(retry.id).retry_of == job.id
    assert [o.dataset_selection.provider for o in retried.outputs] == ["broken"]
    assert {t.id for t in retried.tasks} == set(retried.outputs[0].task_ids)
    assert retried.plan_hash != plan.plan_hash
    assert runner.retry_failed(job.id, "retry-1").id == retry.id

    runner.run(retry.id)
    assert store.get(retry.id).state == "failed"

    complete = store.submit(
        service.plan(
            WeatherRequest(locations=Location(lat=2, lon=0), start="2024-01-01", end="2024-01-01")
        )
    )
    with pytest.raises(OpenEPWError, match="INVALID_REQUEST"):
        runner.retry_failed(complete.id)
    runner.run(complete.id)
    with pytest.raises(OpenEPWError, match="NOTHING_TO_RETRY"):
        runner.retry_failed(complete.id)


def test_restart_resumes_after_verified_completed_item(tmp_path):
    from openepw.models import WeatherPlan

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
    raw = plan.model_dump(mode="json", exclude={"plan_hash"})
    raw["outputs"] = [first.model_dump()]
    raw["tasks"] = [t.model_dump() for t in plan.tasks if t.id in first.task_ids]
    prior = service.execute(WeatherPlan.model_validate(raw))
    store.complete_item(job.id, first.name, prior)
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
    assert store.list_jobs().items[0].kind == "future"


def test_job_kind_comes_from_the_stored_plan_for_legacy_rows(tmp_path):
    import json
    import sqlite3

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    store = JobStore(tmp_path)
    job = store.submit(plan)
    assert job.kind == "weather"
    legacy_plan = plan.model_dump(mode="json")
    legacy_plan["kind"] = "future"
    legacy_job = job.model_dump(mode="json", exclude={"kind"})
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE jobs SET plan=?, job=? WHERE id=?",
            (json.dumps(legacy_plan), json.dumps(legacy_job), job.id),
        )
    db.close()

    assert store.get(job.id).kind == "future"
    assert store.list_jobs().items[0].kind == "future"


def test_job_connections_close_after_transaction(tmp_path):
    import sqlite3

    import pytest

    store = JobStore(tmp_path)
    with store.connect() as db:
        assert db.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        db.execute("SELECT 1")
