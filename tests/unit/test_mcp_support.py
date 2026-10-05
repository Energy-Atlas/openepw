import json

from openepw.mcp.descriptions import DESCRIPTIONS, INSTRUCTIONS
from openepw.mcp.schemas import inline_schema
from openepw.mcp.summaries import LIMIT, summarize
from openepw.models import WeatherRequest

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


def test_unknown_tools_and_broken_summaries_fall_back_to_clipped_json():
    assert summarize("not_a_tool", {"a": 1}) == '{"a": 1}'
    assert len(summarize("not_a_tool", {"a": "x" * 5000})) == LIMIT
    assert summarize("weather_plan", {"issues": "not-a-list"}).startswith("{")


def test_every_tool_has_a_description_with_use_and_limits():
    assert set(DESCRIPTIONS) == TOOLS
    for name, text in DESCRIPTIONS.items():
        assert len(text) >= 100 and "Use " in text and "Do not" in text, name
    assert "weather_locations_review" in INSTRUCTIONS and "simulation" in INSTRUCTIONS
