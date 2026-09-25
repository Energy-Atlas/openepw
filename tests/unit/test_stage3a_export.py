"""Compact export preserves row mapping without duplicating equivalent weather bytes."""

import csv
import io
import json
import zipfile

import pytest
from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.models import Location, OpenEPWError, WeatherRequest
from openepw.service import WeatherService


def _finished(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(WeatherRequest(
        locations=[Location(lat=1, lon=0, name="../unsafe" * 30),
                   Location(lat=12, lon=0, name="CON")],
        start="2024-01-01", end="2024-01-01",
        dataset_selections=[{"provider": "station", "dataset": "synthetic"},
                            {"provider": "missing", "dataset": "unknown"}],
    ))
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan)
    runner.run(job.id)
    return service, runner, job.id


def test_compact_export_maps_all_rows_and_groups_exact_equivalents(tmp_path):
    service, runner, job_id = _finished(tmp_path)
    ref = runner.export_compact(job_id)
    assert ref.media_type == "application/zip"
    _, path = service.artifacts.resolve(ref.id)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert names.count("mapping.csv") == 1
        assert {"manifest.json", "qc.json"} <= set(names)
        assert len([name for name in names if name.endswith(".epw")]) == 1
        mapping = list(csv.DictReader(io.StringIO(archive.read("mapping.csv").decode())))
        assert sorted(row["status"] for row in mapping) == [
            "succeeded", "succeeded", "unresolved", "unresolved"]
        successes = [row for row in mapping if row["status"] == "succeeded"]
        unresolved = [row for row in mapping if row["status"] == "unresolved"]
        assert successes[0]["compact_member"] == successes[1]["compact_member"]
        assert all(row["compact_member"] == "" for row in unresolved)
        assert successes[0]["artifact_id"] != successes[1]["artifact_id"]
        assert all(".." not in name and not name.startswith("/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["simulation_ready"] is False
    assert runner.export_compact(job_id).id == ref.id
    runner.close()


def test_compact_export_refuses_corrupt_weather_artifact(tmp_path):
    service, runner, job_id = _finished(tmp_path)
    weather = runner.store.get(job_id).bundle.weather[0]
    (tmp_path / weather.path).write_bytes(b"corrupt")
    with pytest.raises(OpenEPWError, match="INVALID_ARTIFACT"):
        runner.export_compact(job_id)
    runner.close()


def test_compact_export_refuses_unfinished_job(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(WeatherRequest(locations=Location(lat=1, lon=0),
                                       start="2024-01-01", end="2024-01-01"))
    runner = JobRunner(service)
    job = runner.store.submit(plan)
    with pytest.raises(OpenEPWError, match="EXPORT_UNAVAILABLE"):
        runner.export_compact(job.id)
    runner.close()


def test_failed_row_has_no_compact_member(tmp_path):
    class FailingStation(StationProvider):
        def fetch(self, task, http):
            if task.source.identity == "2":
                raise OpenEPWError("FETCH_FAILED", "Synthetic fetch failure")
            return super().fetch(task, http)

    service = WeatherService(RuntimeConfig(data_root=tmp_path),
                             providers=[FailingStation()])
    plan = service.plan(WeatherRequest(
        locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
        start="2024-01-01", end="2024-01-01"))
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan)
    runner.run(job.id)
    _, path = service.artifacts.resolve(runner.export_compact(job.id).id)
    with zipfile.ZipFile(path) as archive:
        mapping = list(csv.DictReader(io.StringIO(archive.read("mapping.csv").decode())))
    failed = next(row for row in mapping if row["status"] == "failed")
    assert failed["artifact_id"] == failed["compact_member"] == ""
    assert failed["issue_codes"] == "FETCH_FAILED"
    runner.close()
