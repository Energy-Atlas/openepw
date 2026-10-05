from __future__ import annotations

import json
import logging

from pydantic import BaseModel

from openepw.config import RuntimeConfig
from openepw.mcp.descriptions import DESCRIPTIONS, INSTRUCTIONS
from openepw.mcp.schemas import inline_schema
from openepw.mcp.summaries import LIMIT, SUMMARIES, summarize
from openepw.models import WeatherRequest
from openepw.service import WeatherService

TOOLS = {
    "weather_geocode", "weather_places_interpret", "weather_places_preview", "weather_place_set",
    "weather_locations_review", "weather_product_offers", "weather_assess", "weather_discover",
    "weather_plan", "plan_inspect", "epw_upload", "epw_register_path", "weather_submit",
    "job_inspect", "job_cancel", "job_retry_failed", "artifact_inspect",
    "weather_visualization_capabilities", "weather_data_describe", "weather_visualize",
    "weather_data_page", "weather_export_compact", "weather_fetch", "weather_inspect",
}


def test_inline_schema_has_fields_and_no_references():
    schema = inline_schema(WeatherRequest)
    assert "locations" in schema["properties"]
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema


def test_plan_summary_names_the_hash_and_estimates_not_the_rows():
    data = {"plan_hash": "a" * 64, "kind": "weather", "output_count": 3, "batch_row_count": 4,
            "estimated_calls": 2, "warnings": ["w"], "issues": [{"code": "NO_SOURCE"}],
            "outputs": [{"id": "x" * 40}], "truncated": False}
    text = summarize("weather_plan", data)
    assert "a" * 64 in text and "3 outputs" in text and "2 estimated source calls" in text
    assert "NO_SOURCE" in text and "x" * 40 not in text


def test_view_summary_keeps_rows_out_of_model_context():
    data = {"view_id": "v1", "total_rows": 12, "rows": [{"value": 123456.789}],
            "request": {"family": "monthly_series", "variable": "dry_bulb"},
            "specs": [{"family": "monthly_series", "summary": "12 monthly_series points."}],
            "warnings": []}
    text = summarize("weather_visualize", data)
    assert "v1" in text and "12 monthly_series points." in text and "123456" not in text


def test_unknown_tool_stub_names_fields_and_identifiers_but_not_values():
    text = summarize("not_a_tool", {"plan_hash": "h1", "rows": [{"value": 98765}], "note": "secret"})
    assert text.startswith("not_a_tool result; fields: ")
    assert "h1" in text and "rows" in text and "98765" not in text and "secret" not in text
    assert "plan_hash=h1" in text


def test_stub_only_includes_scalar_identifier_values():
    text = summarize("not_a_tool", {"id": {"nested": "x"}, "job_id": 7, "state": True, "kind": ["a"]})
    assert "job_id=7" in text and "state=True" in text and "nested" not in text and "kind=" not in text


def test_broken_summary_falls_back_to_the_stub_and_logs_the_tool(caplog):
    with caplog.at_level(logging.WARNING, logger="openepw.mcp"):
        text = summarize("weather_plan", {"issues": "not-a-list", "plan_hash": "h2"})
    assert text.startswith("weather_plan result; fields: ") and "plan_hash=h2" in text
    records = [record for record in caplog.records if record.name == "openepw.mcp"]
    assert len(records) == 1
    assert "weather_plan" in records[0].getMessage() and "not-a-list" not in records[0].getMessage()


def test_non_dict_data_never_raises():
    for data in (None, [1, 2], "text", 5):
        assert summarize("not_a_tool", data) == "not_a_tool result"
        assert summarize("weather_plan", data) == "weather_plan result"


def test_long_key_lists_are_clipped():
    text = summarize("not_a_tool", {f"key_{index:04d}": 1 for index in range(1000)})
    assert len(text) == LIMIT


def _job_data(tmp_path):
    from openepw.mcp.server import _job_summary
    from openepw.models import WeatherJob
    return _job_summary(WeatherJob(id="job1", plan_hash="h" * 64, total=2, completed=1, failed=1))


def _summary_cases(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    point = {"lat": 42.44, "lon": -76.5}
    location = {"id": "loc1", "name": "Ithaca", "lat": 42.44, "lon": -76.5}
    row = {"index": 1, "input": "Ithaca", "name": "Ithaca", "lat": 42.44, "lon": -76.5,
           "status": "resolved", "value": 98765}
    plan = {"plan_hash": "a" * 64, "kind": "weather", "request": {"product": "tmy"},
            "outputs": [{"id": "o1", "name": "Ithaca"}], "output_count": 1,
            "batch_rows": [{"value": 98765}], "batch_row_count": 1,
            "issues": [{"code": "NO_SOURCE"}], "warnings": ["w"], "estimated_calls": 2,
            "estimated_bytes": 10, "truncated": False}
    job = _job_data(tmp_path)
    artifact = {"artifact_id": "art1", "role": "weather", "bytes": 100, "sha256": "f" * 64,
                "simulation_ready": False, "qc_issue_codes": ["QC_GAP"]}
    upload = {"artifact_id": "art2", "sha256": "e" * 64, "bytes": 5, "rows": 8760,
              "input_qc": [{"code": "QC_RANGE"}]}
    view = {"schema_version": "1", "view_id": "v1", "total_rows": 12, "rows": [{"value": 98765}],
            "request": {"family": "monthly_series", "variable": "dry_bulb"},
            "specs": [{"family": "monthly_series", "summary": "12 points."}], "warnings": []}
    return {
        "weather_geocode": {"query": "Ithaca", "mode": "point", "candidates": [location, location]},
        "weather_places_interpret": {"kind": "list", "items": ["Ithaca", "Boston"]},
        "weather_places_preview": {"digest": "d" * 64, "count": 1, "resolved": 1, "rows": [row],
                                   "issues": [], "attribution": "x"},
        "weather_place_set": {"digest": "d" * 64, "count": 1, "resolved": 1, "rows": [row],
                              "issues": [], "attribution": "x"},
        "weather_locations_review": service.review_locations(point),
        "weather_product_offers": service.product_offers(point),
        "weather_assess": {"options": [{"product": {"provider": "p", "dataset": "d"},
                                        "occurrence_index": 0, "eligibility": {"status": "listed"}}],
                           "issues": [{"code": "STALE"}]},
        "weather_discover": {"candidates": [{"id": "c1", "source": {"provider": "p", "dataset": "d"}}]},
        "weather_plan": plan, "plan_inspect": {**plan, "offset": 0, "limit": 50},
        "weather_submit": job, "weather_fetch": job, "job_inspect": job, "job_cancel": job,
        "job_retry_failed": job, "artifact_inspect": artifact,
        "weather_inspect": artifact,
        "epw_upload": upload, "epw_register_path": upload,
        "weather_visualization_capabilities": service.visualization_capabilities(),
        "weather_data_describe": {"schema_version": "1", "sources": [
            {"artifact_id": "art1", "years": [2020],
             "variables": {"dry_bulb": {"unit": "C", "missing_hours": 3, "valid_hours": 8757}}}]},
        "weather_visualize": view,
        "weather_data_page": {"schema_version": "1", "view_id": "v1", "rows": [{"value": 98765}],
                              "total_rows": 12, "next_offset": None},
        "weather_export_compact": {"artifact_id": "art3", "bytes": 9, "sha256": "c" * 64,
                                   "uri": "weather://artifacts/art3"},
    }


def test_every_registered_summary_runs_for_realistic_data(tmp_path, caplog):
    cases = _summary_cases(tmp_path)
    assert set(cases) == set(SUMMARIES)
    with caplog.at_level(logging.WARNING, logger="openepw.mcp"):
        for tool, data in cases.items():
            text = summarize(tool, data)
            assert isinstance(text, str) and text and len(text) <= LIMIT, tool
            assert not text.startswith(f"{tool} result"), tool
            assert "98765" not in text, tool
    assert not caplog.records


def test_weather_inspect_summarizes_a_job_when_it_has_a_state():
    text = summarize("weather_inspect", _job_data(None))
    assert text.startswith("job job1 ")


def test_inline_schema_stops_at_a_recursion_point():
    class Node(BaseModel):
        name: str
        child: Node | None = None

    schema = inline_schema(Node)
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["properties"]["child"]["anyOf"][0] == {"type": "object"}


def test_every_tool_has_a_description_with_use_and_limits():
    assert set(DESCRIPTIONS) == TOOLS
    for name, text in DESCRIPTIONS.items():
        assert len(text) >= 100 and "Use " in text and "Do not" in text, name
    assert "weather_locations_review" in INSTRUCTIONS and "simulation" in INSTRUCTIONS
