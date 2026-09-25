"""Job-local reuse and recovery keep artifact identities and partial outcomes."""

import json

from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner, subplan
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


def _runner(tmp_path, request):
    provider = StationProvider()
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[provider])
    plan = service.plan(request)
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    return provider, service, plan, runner


def test_one_verified_fetch_serves_two_distinct_output_artifacts(tmp_path):
    provider, service, plan, runner = _runner(
        tmp_path, WeatherRequest(locations=[Location(lat=1, lon=0),
                                            Location(lat=12, lon=0)],
                                 start="2024-01-01", end="2024-01-01"))
    assert len(plan.tasks) == 1
    job = runner.submit(plan)
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert provider.calls == 1
    assert final.completed == 2
    assert len({ref.id for ref in final.bundle.weather}) == 2
    _, path = service.artifacts.resolve(final.bundle.manifest.id)
    rows = json.loads(path.read_text())["batch_rows"]
    assert [row["status"] for row in rows] == ["succeeded", "succeeded"]
    runner.close()


def test_nonexecutable_selection_makes_successful_job_partial(tmp_path):
    provider, _, plan, runner = _runner(
        tmp_path, WeatherRequest(
            locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01",
            dataset_selections=[{"provider": "station", "dataset": "synthetic"},
                                {"provider": "missing", "dataset": "unknown"}]))
    job = runner.submit(plan)
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "partially_completed"
    assert final.completed == 1
    assert provider.calls == 1
    runner.close()


def test_restart_reuses_verified_item_and_retries_corrupt_one(tmp_path):
    provider, service, plan, runner = _runner(
        tmp_path, WeatherRequest(locations=[Location(lat=1, lon=0),
                                            Location(lat=2, lon=0)],
                                 start="2024-01-01", end="2024-01-01"))
    first, second = plan.outputs
    first_bundle = service.execute(subplan(plan, [first]))
    second_bundle = service.execute(subplan(plan, [second]))
    job = runner.store.submit(plan)
    runner.store.complete_item(job.id, first.id, first_bundle)
    runner.store.complete_item(job.id, second.id, second_bundle)
    (tmp_path / second_bundle.weather[0].path).write_bytes(b"corrupt")
    calls_before = provider.calls
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "completed"
    assert provider.calls == calls_before + 1
    assert first_bundle.weather[0].id in {ref.id for ref in final.bundle.weather}
    runner.close()
