"""Every requested batch row has an explicit final outcome."""

import json
from datetime import date, datetime, timezone

from test_batch import StationProvider

from openepw.availability import (
    AvailabilityResult,
    EligibilityDecision,
    LocationAssessment,
    ProductRecord,
    SuitabilityOption,
)
from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.models import (
    BatchRow,
    Candidate,
    DatasetSelection,
    DiscoveryResult,
    FetchTask,
    Issue,
    Location,
    OpenEPWError,
    OutputSpec,
    SourceRef,
    WeatherPlan,
    WeatherRequest,
)
from openepw.planning.batch import fetch_task_key, finalize_batch_rows
from openepw.service import WeatherService


def _plan():
    locations = [Location(id=f"point-{index}", lat=40 + index, lon=-75)
                 for index in range(4)]
    selection = DatasetSelection(provider="noaa", dataset="ISD global-hourly")
    source = SourceRef(provider="noaa", dataset=selection.dataset,
                       identity="station", location=Location(lat=40.5, lon=-75))
    params = {"location": locations[0].model_dump(mode="json"),
              "start": "2024-01-01", "end": "2024-01-01", "product": "historical"}
    key = fetch_task_key(source, params)
    task = FetchTask(id=key[:20], source=source, parameters=params, cache_key=key)
    outputs = [OutputSpec(id=str(index) * 64, occurrence_index=index,
                          requested_location_id=locations[index].key,
                          task_ids=[task.id], name=f"point-{index}.epw")
               for index in range(2)]
    rows = [BatchRow(occurrence_index=index, requested_location_id=location.key,
                     dataset_selection=selection, period_start=date(2024, 1, 1),
                     period_end=date(2024, 1, 1),
                     status="planned" if index < 2 else
                            ("unsupported" if index == 2 else "unresolved"),
                     task_ids=[task.id] if index < 2 else [],
                     output_id=outputs[index].id if index < 2 else None)
            for index, location in enumerate(locations)]
    return WeatherPlan(request=WeatherRequest(locations=locations, years=[2024]),
                       tasks=[task], outputs=outputs, batch_rows=rows)


def test_final_rows_preserve_success_failure_and_nonexecutable_identity():
    plan = _plan()
    success = {"output_id": plan.outputs[0].id, "artifact_id": "artifact",
               "task_ids": plan.outputs[0].task_ids,
               "source": plan.tasks[0].source.model_dump(mode="json"),
               "lineage": {"dry_bulb": {"source": "station"}}}
    issues = [Issue(code="FETCH_FAILED", message="failed", severity="error",
                    task_id=plan.outputs[1].id),
              Issue(code="DATASET_UNAVAILABLE", message="unavailable",
                    occurrence_index=2, location_id="point-2")]
    rows = finalize_batch_rows(plan, [success], issues, cancelled=False)
    assert [row["status"] for row in rows] == [
        "succeeded", "failed", "unsupported", "unresolved"]
    assert rows[0]["artifact_id"] == "artifact"
    assert rows[0]["source"]["location"]["lat"] == 40.5
    assert rows[0]["requested_location_id"] == "point-0"
    assert rows[1]["issue_codes"] == ["FETCH_FAILED"]
    assert rows[1].get("artifact_id") is None
    assert rows[2]["issue_codes"] == ["DATASET_UNAVAILABLE"]
    assert rows[3].get("artifact_id") is None


def test_cancelled_unproduced_row_is_not_claimed_as_failed():
    plan = _plan()
    rows = finalize_batch_rows(plan, [], [], cancelled=True)
    assert [row["status"] for row in rows] == [
        "cancelled", "cancelled", "unsupported", "unresolved"]


def test_job_manifest_accounts_for_mixed_fetch_outcomes(tmp_path):
    class FlakyStation(StationProvider):
        def fetch(self, task, http):
            if task.source.identity == "2":
                raise OpenEPWError("FETCH_FAILED", "Synthetic fetch failed")
            return super().fetch(task, http)

    provider = FlakyStation()
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[provider])
    points = [Location(id=f"point-{index}", lat=index + 1, lon=0)
              for index in range(4)]
    selection = DatasetSelection(provider="station", dataset="synthetic")
    request = WeatherRequest(locations=points, start="2024-01-01",
                             end="2024-01-01", dataset_selections=[selection])
    candidates: list[Candidate] = [provider.discover(request, point, service.http)[0]
                                   for point in points[:2]]
    availability = AvailabilityResult(
        locations=[LocationAssessment(occurrence_index=index, requested_location=point)
                   for index, point in enumerate(points)],
        options=[SuitabilityOption(
            id="excluded", occurrence_index=2,
            product=ProductRecord(id="station:synthetic", provider="station",
                                  dataset="synthetic", temporal_kind="actual"),
            eligibility=EligibilityDecision(status="excluded"))],
        checked_at=datetime.now(timezone.utc),
    )
    discovery = DiscoveryResult(
        locations=points, candidates=candidates,
        candidate_ids_by_occurrence=[[candidate.id] for candidate in candidates] + [[], []],
        availability=availability,
    )
    plan = service.plan(request, discovery=discovery)
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan)
    runner.run(job.id)
    final = runner.store.get(job.id)
    assert final.state == "partially_completed"
    _, manifest_path = service.artifacts.resolve(final.bundle.manifest.id)
    manifest = json.loads(manifest_path.read_text())
    assert [row["status"] for row in manifest["batch_rows"]] == [
        "succeeded", "failed", "unsupported", "unresolved"]
    assert manifest["batch_rows"][0]["source"]["location"]["lat"] == 1
    assert manifest["batch_rows"][1]["issue_codes"] == ["FETCH_FAILED"]
    assert all("artifact_id" not in row for row in manifest["batch_rows"][1:])
    assert manifest["counts"] == {
        "requested_occurrences": 4, "output_intents": 2, "native_tasks": 2,
        "shared_native_tasks": 0, "unsupported": 1, "unresolved": 1,
        "emitted_artifacts": 1,
    }
    runner.close()
