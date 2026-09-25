"""Batch planning preserves every requested combination and safe source reuse."""

from datetime import datetime, timezone

import pytest

from openepw.availability import (
    AvailabilityResult,
    EligibilityDecision,
    LocationAssessment,
    ProductRecord,
    SuitabilityOption,
)
from openepw.config import RuntimeConfig
from openepw.jobs.worker import subplan
from openepw.models import (
    Candidate,
    DatasetSelection,
    DiscoveryResult,
    FetchTask,
    Location,
    OpenEPWError,
    OutputSpec,
    SourceRef,
    WeatherPlan,
    WeatherRequest,
)
from openepw.planning.batch import fetch_task_key
from openepw.service import WeatherService


def _service(tmp_path):
    return WeatherService(RuntimeConfig(data_root=tmp_path))


def test_exact_published_url_shares_one_task_but_preserves_partial_rows(tmp_path):
    points = [Location(id=f"p{i}", lat=42 + i, lon=-76) for i in range(3)]
    selection = DatasetSelection(provider="onebuilding", dataset="OneBuilding published EPW",
                                 product_id="USA/NY/Ithaca.zip")
    request = WeatherRequest(locations=points, product="tmyx",
                             dataset_selections=[selection])
    candidates = [Candidate(
        id=f"published:{i}", location_id=points[i].key, product_id=selection.product_id,
        source=SourceRef(provider="onebuilding", dataset=selection.dataset,
                         identity="/USA/NY/Ithaca.zip",
                         citation="https://climate.onebuilding.org/USA/NY/Ithaca.zip"),
        weather_types=["tmyx"],
    ) for i in range(2)]
    product = ProductRecord(id="onebuilding:ithaca", provider="onebuilding",
                            dataset=selection.dataset, temporal_kind="tmy_reference")
    availability = AvailabilityResult(
        locations=[LocationAssessment(occurrence_index=i, requested_location=point)
                   for i, point in enumerate(points)],
        options=[SuitabilityOption(id="excluded", occurrence_index=2, product=product,
                                   eligibility=EligibilityDecision(status="excluded"))],
        checked_at=datetime.now(timezone.utc),
    )
    discovery = DiscoveryResult(locations=points, candidates=candidates,
                                candidate_ids_by_occurrence=[
                                    [candidates[0].id], [candidates[1].id], []],
                                availability=availability)
    plan = _service(tmp_path).plan(request, discovery=discovery)
    assert [row.occurrence_index for row in plan.batch_rows] == [0, 1, 2]
    assert [row.status for row in plan.batch_rows] == ["planned", "planned", "unsupported"]
    assert len(plan.outputs) == 2
    assert len(plan.tasks) == 1
    assert "location" not in plan.tasks[0].parameters
    assert len({output.id for output in plan.outputs}) == 2
    assert plan.batch_rows[2].output_id is None


def test_unresolved_all_nonexecutable_plan_is_inspectable_but_cannot_execute(tmp_path):
    point = Location(lat=42, lon=-76)
    selection = DatasetSelection(provider="noaa", dataset="ISD global-hourly")
    request = WeatherRequest(locations=point, years=[2024],
                             dataset_selections=[selection])
    discovery = DiscoveryResult(locations=[point], candidates=[],
                                candidate_ids_by_occurrence=[[]])
    service = _service(tmp_path)
    plan = service.plan(request, discovery=discovery)
    assert len(plan.batch_rows) == 1
    assert plan.batch_rows[0].status == "unresolved"
    assert plan.tasks == plan.outputs == []
    with pytest.raises(OpenEPWError, match="NO_EXECUTABLE_OUTPUTS"):
        service.execute(plan)


@pytest.mark.parametrize("provider,verified", [("noaa", True), ("openmeteo", False)])
def test_source_reuse_requires_exact_request_options(tmp_path, provider, verified):
    points = [Location(id="same", lat=42, lon=-76, standard_offset_minutes=0),
              Location(id="same", lat=42.01, lon=-76, standard_offset_minutes=60)]
    dataset = "ISD global-hourly" if provider == "noaa" else "era5"
    selection = DatasetSelection(provider=provider, dataset=dataset)
    request = WeatherRequest(locations=points, years=[2024],
                             dataset_selections=[selection])
    candidates = [Candidate(
        id=f"{provider}:candidate:{i}", location_id=point.key,
        source=SourceRef(provider=provider, dataset=dataset, identity="same-cell",
                         location=Location(lat=42, lon=-76,
                                           standard_offset_minutes=point.standard_offset_minutes)
                         if verified else None, provisional=not verified),
        weather_types=["historical"],
    ) for i, point in enumerate(points)]
    discovery = DiscoveryResult(locations=points, candidates=candidates,
                                candidate_ids_by_occurrence=[[c.id] for c in candidates])
    plan = _service(tmp_path).plan(request, discovery=discovery)
    assert len(plan.batch_rows) == 2
    assert len(plan.tasks) == 2
    assert len(plan.outputs) == 2


def test_dataset_and_year_cross_product_keeps_exact_periods(tmp_path):
    point = Location(lat=42, lon=-76)
    selections = [DatasetSelection(provider="noaa", dataset="ISD global-hourly"),
                  DatasetSelection(provider="openmeteo", dataset="era5")]
    request = WeatherRequest(locations=point, years=[2023, 2024],
                             dataset_selections=selections)
    candidates = [Candidate(id=f"choice:{s.provider}", location_id=point.key,
                            source=SourceRef(provider=s.provider, dataset=s.dataset),
                            weather_types=["historical"]) for s in selections]
    discovery = DiscoveryResult(locations=[point], candidates=candidates,
                                candidate_ids_by_occurrence=[[c.id for c in candidates]])
    plan = _service(tmp_path).plan(request, discovery=discovery)
    assert len(plan.batch_rows) == 4
    assert {(row.dataset_selection.provider, row.period_start.isoformat(),
             row.period_end.isoformat()) for row in plan.batch_rows} == {
                 (provider, f"{year}-01-01", f"{year}-12-31")
                 for provider in ("noaa", "openmeteo") for year in (2023, 2024)
             }
    assert len(plan.tasks) == len(plan.outputs) == 4


def test_location_free_published_task_rejects_unreviewed_source_url(tmp_path):
    class ForbiddenProvider:
        name = "onebuilding"

        def fetch(self, task, http):
            raise AssertionError("unreviewed URL reached provider")

    source = SourceRef(provider="onebuilding", dataset="OneBuilding published EPW",
                       identity="/bad.zip", citation="https://unreviewed.example/bad.zip")
    parameters = {"start": "None", "end": "None", "product": "tmyx",
                  "product_id": "bad.zip"}
    key = fetch_task_key(source, parameters)
    task = FetchTask(id=key[:20], source=source, parameters=parameters, cache_key=key)
    output = OutputSpec(id="a" * 64, requested_location_id="point",
                        task_ids=[task.id], name="point.epw")
    plan = WeatherPlan(request=WeatherRequest(locations=Location(lat=42, lon=-76),
                                              product="tmyx"), tasks=[task], outputs=[output])
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[ForbiddenProvider()])
    with pytest.raises(OpenEPWError, match="PLAN_STALE"):
        service.execute(plan)


def test_job_subplan_keeps_only_selected_executable_batch_row(tmp_path):
    point = Location(lat=42, lon=-76)
    request = WeatherRequest(locations=point, years=[2023, 2024],
                             dataset_selections=[DatasetSelection(provider="noaa",
                                                                  dataset="ISD global-hourly")])
    candidate = Candidate(id="station", location_id=point.key,
                          source=SourceRef(provider="noaa", dataset="ISD global-hourly"),
                          weather_types=["historical"])
    discovery = DiscoveryResult(locations=[point], candidates=[candidate],
                                candidate_ids_by_occurrence=[[candidate.id]])
    plan = _service(tmp_path).plan(request, discovery=discovery)
    sliced = subplan(plan, [plan.outputs[0]])
    assert len(sliced.outputs) == len(sliced.batch_rows) == 1
    assert sliced.batch_rows[0].output_id == plan.outputs[0].id
