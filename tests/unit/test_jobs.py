from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.jobs.store import JobStore
from openepw.jobs.worker import JobRunner
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
