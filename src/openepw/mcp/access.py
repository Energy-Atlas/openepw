"""Which tools a model may call, which the host calls on a person's action, which are legacy."""

MODEL_TOOLS = frozenset({
    "weather_places_interpret", "weather_geocode", "weather_places_preview", "weather_place_set",
    "weather_locations_review", "weather_product_offers", "weather_assess", "weather_plan",
    "plan_inspect", "job_inspect", "artifact_inspect", "weather_data_describe",
    "weather_visualization_capabilities", "weather_visualize",
})
HOST_TOOLS = frozenset({
    "weather_submit", "job_cancel", "job_retry_failed", "weather_export_compact",
    "epw_upload", "epw_register_path", "weather_data_page",
})
LEGACY_TOOLS = frozenset({"weather_discover", "weather_fetch", "weather_inspect"})
