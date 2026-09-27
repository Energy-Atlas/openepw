"""The published visualization vocabulary is stable even before every family runs."""

import pytest
from pydantic import ValidationError

from openepw.visualization import VisualizationRequest, VisualizationSpec, capabilities


def test_capabilities_distinguish_callable_initial_families_from_planned_families():
    families = {item["family"]: item for item in capabilities()["families"]}
    assert families["monthly_series"]["status"] == "implemented"
    assert families["time_series"]["status"] == "implemented"
    assert families["psychrometric"]["status"] == "planned"
    assert families["wind_rose"]["status"] == "planned"
    assert families["extreme_event_timeline"]["status"] == "planned"
    assert families["histogram"]["supported_options"] == ["bins"]
    assert families["monthly_series"]["supported_options"] == []


def test_request_rejects_unknown_options_and_duplicate_artifact_ids():
    one = "a" * 32
    with pytest.raises(ValidationError):
        VisualizationRequest(artifact_ids=[one], family="monthly_series",
                             variable="dry_bulb", options={"invented": True})
    with pytest.raises(ValidationError):
        VisualizationRequest(artifact_ids=[one, one], family="monthly_series",
                             variable="dry_bulb")


def test_visualization_spec_schema_requires_data_reference_and_quality():
    spec = VisualizationSpec.model_validate({
        "family": "monthly_series",
        "data_ref": {"view_id": None, "shape": "rows", "total_rows": 12,
                     "page_tool": "weather_data_page"},
        "encodings": {"x": {"field": "period"}},
        "transforms": [], "sources": [],
        "quality": {"expected_hours": 8760, "valid_hours": 8760,
                    "missing_hours": 0}, "summary": "Twelve months.",
    })
    assert spec.schema_version == "1"
    assert spec.data_ref.total_rows == 12
    with pytest.raises(ValidationError):
        VisualizationSpec.model_validate({"family": "monthly_series",
                                          "encodings": {"x": {"field": "period"}}})
