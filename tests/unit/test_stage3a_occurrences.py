"""Requested occurrences remain distinct even when location labels collide."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from openepw import models
from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    ProductRecord,
    SiteRecord,
)
from openepw.availability.store import CatalogStore
from openepw.config import RuntimeConfig
from openepw.models import (
    Candidate,
    Location,
    OutputSpec,
    SourceRef,
    WeatherPlan,
    WeatherRequest,
)
from openepw.service import WeatherService


class _LocalProvider:
    name = "noaa"

    def discover(self, request, location, http):
        return [Candidate(
            id=f"noaa:station:{location.key}", location_id=location.key,
            source=SourceRef(provider="noaa", dataset="ISD", identity="station"),
            weather_types=["historical"], variables=["dry_bulb"],
        )]


@pytest.mark.parametrize("points", [
    [Location(lat=42, lon=-76)] * 2,
    [Location(id="same", lat=42, lon=-76), Location(id="same", lat=43, lon=-77)],
])
def test_live_discovery_keeps_each_requested_occurrence(tmp_path, points):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[_LocalProvider()])
    result = service.discover(WeatherRequest(locations=points, years=[2024], providers=["noaa"]))
    assert len(result.candidate_ids_by_occurrence) == 2
    assert all(result.candidate_ids_by_occurrence)
    first, second = (ids[0] for ids in result.candidate_ids_by_occurrence)
    assert first != second
    assert {first, second} <= {candidate.id for candidate in result.candidates}
    assert [location.key for location in result.locations] == [points[0].key, points[1].key]


def test_catalog_discovery_keeps_duplicate_occurrences(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    bundle = CatalogBundle(
        evidence=[EvidenceRef(id="counts", sha256="a" * 64,
                              retrieved_at=datetime.now(timezone.utc), basis="inventory")],
        products=[ProductRecord(id="noaa:isd", provider="noaa", dataset="isd",
                                spatial_kind="station", temporal_kind="actual",
                                adapter_variables=["dry_bulb"], evidence_ids=["counts"])],
        sites=[SiteRecord(id="station", product_id="noaa:isd", lat=42, lon=-76,
                          position_status="published", station_identity_status="verified")],
        entries=[AvailabilityEntry(id="year", product_id="noaa:isd", site_id="station",
                                   scope=ActualScope(years=[2024]), evidence_basis="inventory",
                                   evidence_ids=["counts"])],
    )
    store.activate(store.stage(bundle).generation_id)
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             catalog_store=store)
    point = Location(id="duplicate", lat=42, lon=-76)
    result = service.discover(WeatherRequest(locations=[point, point], years=[2024],
                                             providers=["noaa"]))
    assert len(result.candidate_ids_by_occurrence) == 2
    assert result.candidate_ids_by_occurrence[0][0] != result.candidate_ids_by_occurrence[1][0]


def test_batch_rows_reject_missing_duplicate_and_nonexecutable_output_links():
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024])
    output = OutputSpec(id="a" * 64, requested_location_id="point", task_ids=["task"],
                        name="point.epw")
    source = SourceRef(provider="noaa", dataset="ISD")
    from openepw.models import FetchTask
    task = FetchTask(id="task", source=source, parameters={}, cache_key="b" * 64)
    planned = models.BatchRow(occurrence_index=0, requested_location_id="point",
                       dataset_selection={"provider": "noaa", "dataset": "ISD"},
                       status="planned", output_id=output.id, task_ids=["task"])
    good = WeatherPlan(request=request, tasks=[task], outputs=[output], batch_rows=[planned])
    assert WeatherPlan.model_validate_json(good.model_dump_json()).plan_hash == good.plan_hash
    for rows in (
        [planned, planned],
        [planned.model_copy(update={"output_id": "c" * 64})],
        [planned.model_copy(update={"status": "unsupported"})],
    ):
        with pytest.raises(ValidationError):
            WeatherPlan(request=request, tasks=[task], outputs=[output], batch_rows=rows)


def test_legacy_plan_hash_does_not_gain_empty_batch_fields():
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024])
    old = WeatherPlan(request=request)
    assert "batch_rows" not in old.model_dump(mode="json")
    assert WeatherPlan.model_validate_json(old.model_dump_json()).plan_hash == old.plan_hash
