"""Offline Stage 3a anchors exercise plan, job, QC and compact artifact flow."""

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd
from test_batch import StationProvider

from openepw.availability import (
    AvailabilityResult,
    EligibilityDecision,
    LocationAssessment,
    ProductRecord,
    SuitabilityOption,
)
from openepw.config import RuntimeConfig
from openepw.dataset import WeatherDataset
from openepw.jobs.worker import JobRunner
from openepw.models import (
    Candidate,
    DatasetSelection,
    DiscoveryResult,
    Location,
    SourceRef,
    VariableLineage,
    WeatherRequest,
)
from openepw.providers.base import ProviderResult
from openepw.service import WeatherService


def _run(service, plan):
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan.plan_hash)
    runner.run(job.id)
    return runner, runner.store.get(job.id)


def test_actual_year_with_explicit_alternative_and_qc(tmp_path):
    class AnnualStation(StationProvider):
        def fetch(self, task, http):
            self.calls += 1
            hours = pd.date_range("2024-01-01T01:00Z", periods=8784, freq="h")
            data = pd.DataFrame({"dry_bulb": [20.0] * len(hours),
                                 "ghi": [0.0] * len(hours)}, index=hours)
            lineage = {variable: VariableLineage(
                variable=variable, source=task.source,
                raw_sha256=hashlib.sha256(b"annual-synthetic").hexdigest())
                for variable in data}
            return ProviderResult(WeatherDataset(data=data, location=task.source.location,
                                                 lineage=lineage),
                                  task.source, b"annual-synthetic")

    provider = AnnualStation()
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[provider])
    request = WeatherRequest(
        locations=Location(id="ithaca", lat=42.44, lon=-76.5), years=[2024],
        dataset_selections=[DatasetSelection(provider="station", dataset="synthetic"),
                            DatasetSelection(provider="missing", dataset="alternative")])
    plan = service.plan(request)
    assert len(plan.batch_rows) == 2
    runner, job = _run(service, plan)
    assert job.state == "partially_completed"
    assert job.completed == provider.calls == 1
    _, manifest_path = service.artifacts.resolve(job.bundle.manifest.id)
    manifest = json.loads(manifest_path.read_text())
    assert sorted(row["status"] for row in manifest["batch_rows"]) == [
        "succeeded", "unresolved"]
    assert manifest["counts"]["emitted_artifacts"] == 1
    assert manifest["simulation_ready"] is False
    _, weather_path = service.artifacts.resolve(job.bundle.weather[0].id)
    assert len(weather_path.read_text().splitlines()) - 8 == 8784
    assert runner.export_compact(job.id).media_type == "application/zip"
    runner.close()


def test_published_exact_url_batch_duplicate_and_exclusion(tmp_path):
    class PublishedProvider:
        name = "onebuilding"

        def __init__(self):
            self.calls = 0

        def fetch(self, task, http):
            self.calls += 1
            source_location = Location(lat=42.44, lon=-76.5)
            data = pd.DataFrame({"dry_bulb": [20.0] * 24, "ghi": [0.0] * 24},
                                index=pd.date_range("2024-01-01T01:00Z", periods=24,
                                                    freq="h"))
            lineage = {variable: VariableLineage(
                variable=variable, source=task.source,
                raw_sha256=hashlib.sha256(b"published-synthetic").hexdigest())
                for variable in data}
            return ProviderResult(WeatherDataset(data=data, location=source_location,
                                                 lineage=lineage), task.source,
                                  b"published-synthetic")

    provider = PublishedProvider()
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[provider])
    points = [Location(lat=42.4, lon=-76.5), Location(lat=42.5, lon=-76.5),
              Location(lat=42.4, lon=-76.5), Location(lat=10, lon=10)]
    selection = DatasetSelection(provider="onebuilding", dataset="OneBuilding published EPW",
                                 product_id="USA/NY/Ithaca.zip")
    request = WeatherRequest(locations=points, product="tmyx",
                             dataset_selections=[selection])
    source = SourceRef(provider="onebuilding", dataset=selection.dataset,
                       identity="/USA/NY/Ithaca.zip",
                       provisional=False,
                       citation="https://climate.onebuilding.org/USA/NY/Ithaca.zip")
    candidates = [Candidate(id=f"published:{index}", location_id=point.key,
                            product_id=selection.product_id, source=source,
                            weather_types=["tmyx"])
                  for index, point in enumerate(points[:3])]
    availability = AvailabilityResult(
        locations=[LocationAssessment(occurrence_index=index, requested_location=point)
                   for index, point in enumerate(points)],
        options=[SuitabilityOption(
            id="excluded", occurrence_index=3,
            product=ProductRecord(id="onebuilding:ithaca", provider="onebuilding",
                                  dataset=selection.dataset, temporal_kind="tmy_reference"),
            eligibility=EligibilityDecision(status="excluded"))],
        checked_at=datetime.now(timezone.utc),
    )
    discovery = DiscoveryResult(locations=points, candidates=candidates,
                                candidate_ids_by_occurrence=[
                                    [candidate.id] for candidate in candidates] + [[]],
                                availability=availability)
    plan = service.plan(request, discovery=discovery)
    assert len(plan.tasks) == 1
    runner, job = _run(service, plan)
    assert job.state == "partially_completed"
    assert (provider.calls, job.completed) == (1, 3)
    _, manifest_path = service.artifacts.resolve(job.bundle.manifest.id)
    manifest = json.loads(manifest_path.read_text())
    assert [row["occurrence_index"] for row in manifest["batch_rows"]] == [0, 1, 2, 3]
    assert [row["status"] for row in manifest["batch_rows"]] == [
        "succeeded", "succeeded", "succeeded", "unsupported"]
    ref = runner.export_compact(job.id)
    _, path = service.artifacts.resolve(ref.id)
    with zipfile.ZipFile(path) as archive:
        assert len([name for name in archive.namelist() if name.endswith(".epw")]) == 1
        mapping = list(csv.DictReader(io.StringIO(archive.read("mapping.csv").decode())))
        assert len(mapping) == 4
        assert mapping[-1]["compact_member"] == ""
    runner.close()
