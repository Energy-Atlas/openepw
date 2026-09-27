"""The published visualization vocabulary is stable even before every family runs."""

import pytest
from pydantic import ValidationError

from openepw.visualization import VisualizationRequest, capabilities


def test_capabilities_distinguish_callable_initial_families_from_planned_families():
    families = {item["family"]: item for item in capabilities()["families"]}
    assert families["monthly_series"]["status"] == "implemented"
    assert families["time_series"]["status"] == "implemented"
    assert families["psychrometric"]["status"] == "planned"
    assert families["wind_rose"]["status"] == "planned"
    assert families["extreme_event_timeline"]["status"] == "planned"


def test_request_rejects_unknown_options_and_duplicate_artifact_ids():
    one = "a" * 32
    with pytest.raises(ValidationError):
        VisualizationRequest(artifact_ids=[one], family="monthly_series",
                             variable="dry_bulb", options={"invented": True})
    with pytest.raises(ValidationError):
        VisualizationRequest(artifact_ids=[one, one], family="monthly_series",
                             variable="dry_bulb")
