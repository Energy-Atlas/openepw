"""Prepared view IDs survive restart and detect corruption."""

import pytest
from test_epw import synthetic

from openepw.config import RuntimeConfig
from openepw.epw.writer import epw_bytes
from openepw.models import OpenEPWError
from openepw.service import WeatherService
from openepw.visualization import VisualizationRequest
from openepw.visualization.store import VisualizationStore


def result():
    return {
        "schema_version": "1",
        "request": {"family": "monthly_series", "artifact_ids": ["a" * 32]},
        "specs": [{"family": "monthly_series",
                   "data_ref": {"view_id": None, "shape": "rows", "total_rows": 3},
                   "sources": [{"artifact_id": "a" * 32, "sha256": "b" * 64}]}],
        "rows": [{"value": 1}, {"value": 2}, {"value": 3}],
        "total_rows": 3,
        "warnings": [],
    }


def test_view_id_is_stable_and_page_zero_recovers_spec_after_restart(tmp_path):
    store = VisualizationStore(tmp_path)
    first = store.save(result(), limit=2)
    same = VisualizationStore(tmp_path).save(result(), limit=2)
    assert first["view_id"] == same["view_id"]
    assert first["rows"] == [{"value": 1}, {"value": 2}]
    assert first["next_offset"] == 2
    last = VisualizationStore(tmp_path).page(first["view_id"], offset=2, limit=2)
    assert last["rows"] == [{"value": 3}]
    assert last["next_offset"] is None
    assert "specs" in VisualizationStore(tmp_path).page(first["view_id"], 0, 1)


def test_corrupt_view_and_unbounded_page_are_rejected(tmp_path):
    store = VisualizationStore(tmp_path)
    saved = store.save(result())
    with pytest.raises(OpenEPWError, match="RESOURCE_LIMIT"):
        store.page(saved["view_id"], offset=0, limit=201)
    path = tmp_path / "views" / f"{saved['view_id']}.json"
    path.write_text(path.read_text().replace('"value":1', '"value":9'))
    with pytest.raises(OpenEPWError, match="INVALID_VIEW"):
        store.page(saved["view_id"], 0, 1)


def test_shared_service_prepares_and_pages_existing_weather_without_provider_call(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    ref = service.artifacts.write("a" * 32, "weather.epw",
                                  epw_bytes(synthetic(2023, 24)), "weather",
                                  "application/vnd.energyplus.epw")
    request = VisualizationRequest(artifact_ids=[ref.id], family="time_series",
                                   variable="dry_bulb")
    prepared = service.visualize_weather(request)
    assert prepared["specs"][0]["family"] == "time_series"
    assert prepared["rows"][0]["value"] == 20.0
    assert service.page_weather_data(prepared["view_id"], 20, 10)["rows"][-1]["value"] == 20.0
    assert service.describe_weather_data([ref.id])["sources"][0]["rows"] == 24
