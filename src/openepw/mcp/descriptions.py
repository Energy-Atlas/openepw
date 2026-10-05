"""Tool descriptions and server instructions written for a tool-calling model."""

INSTRUCTIONS = (
    "OpenEPW plans and retrieves building-energy weather files (EPW). Workflow: resolve places "
    "(weather_places_interpret, weather_geocode, weather_places_preview, weather_place_set); review "
    "them with weather_locations_review and get the person's approval; offer products with "
    "weather_product_offers and let the person choose; plan with weather_plan using exactly the "
    "approved locations, the chosen products and years the person stated; the person reviews the "
    "plan before weather_submit, which asks the client to confirm with the person. 'Supported' or "
    "'listed' means eligible to try retrieval, not quality assured. Inspect QC with artifact_inspect "
    "and never claim simulation readiness. Future weather is suspended. Keep EPW bytes out of prompts."
)

DESCRIPTIONS: dict[str, str] = {
    "weather_geocode": (
        "Resolve one short place name (1-150 characters) to up to 10 point candidates with ids, "
        "coordinates and names. Use when the person names a single place. Do not pick among several "
        "candidates yourself; ask the person to choose. mode accepts only 'point'."),
    "weather_places_interpret": (
        "Classify free place text as coordinates, a list, a single place, a descriptive set or invalid. "
        "Use when the text may hold several places, coordinates or a set such as 'all cities in Oregon'. "
        "For a descriptive set, ask the person the returned questions and pass the returned draft back "
        "with their reply. Do not enumerate a set before its questions are answered."),
    "weather_places_preview": (
        "Resolve up to 1,000 names or 'lat, lon' strings to numbered rows using the top geocoder match "
        "per name; ambiguous and unresolved rows are flagged. Use after weather_places_interpret returns "
        "a list or coordinates, or to apply an edit; pass earlier rows back unchanged to keep them pinned. "
        "Do not treat ambiguous rows as confirmed; the person reviews them."),
    "weather_place_set": (
        "List a clarified descriptive place set from GeoNames in population order as numbered rows. "
        "Use only with the complete query returned by weather_places_interpret. Do not invent country, "
        "region or population values."),
    "weather_locations_review": (
        "Normalize a point, a point list or an area: estimate fixed standard-time offsets from longitude "
        "where missing, sample areas, and return points, a standard-time note and a location key. Use "
        "before asking the person to approve locations; the plan must use exactly the reviewed geography. "
        "Do not change coordinates or offsets after the person approved them."),
    "weather_product_offers": (
        "List named downloadable weather products for reviewed locations with catalog availability per "
        "location (listed or unverified) and the catalog years used. Use to give the person a product "
        "choice; product (historical, tmy, tmyx, published), provider and years narrow the offers. Do "
        "not describe listed products as quality assured; listed means eligible to try retrieval."),
    "weather_assess": (
        "Compare catalog eligibility, evidence dates and unknowns for a weather request without "
        "retrieval. Use to explain why a source is or is not eligible. Do not use it for future weather "
        "(suspended) and do not treat 'supported' as complete data."),
    "weather_discover": (
        "Legacy discovery of source candidates and catalog alternatives for a weather request; "
        "weather_plan already runs discovery. Use only when an external client needs raw candidates. Do "
        "not use it to choose products for a person; use weather_product_offers."),
    "weather_plan": (
        "Store an immutable weather plan for reviewed locations, chosen products and explicit years or "
        "dates; returns plan_hash, outputs, batch rows, warnings and estimated source calls. Use only "
        "after the person approved the locations and chose products. Do not submit it yourself; the "
        "person reviews the plan and the host submits."),
    "plan_inspect": (
        "Page a stored plan's outputs, batch rows and selected candidates with reasons by plan_hash "
        "(limit 1-50). Use to explain a plan before review or answer questions about it. Do not try to "
        "modify a plan; changed choices need a new weather_plan."),
    "epw_upload": (
        "Host tool: register a person's EPW from base64 bytes encoded outside model context (5 MB "
        "maximum); returns artifact_id, rows and input QC. Use when the person attaches an EPW file. Do "
        "not place EPW bytes in model prompts."),
    "epw_register_path": (
        "Host tool: register a local EPW beneath a directory the server was started with (--allow-root), "
        "5 MB maximum. Use when the person names a file under that directory. Do not guess paths."),
    "weather_submit": (
        "Host tool: submit a stored, reviewed weather plan by plan_hash; the server asks the client to "
        "confirm with the person before any provider retrieval. Use when the person approves the plan "
        "review. Do not call it without that approval; clients that cannot confirm get APPROVAL_REQUIRED."),
    "job_inspect": (
        "Inspect a job's state, counts, per-output rows, issue codes and artifact ids. Use to report "
        "progress or results. Do not poll it in a loop; hosts follow job progress themselves."),
    "job_cancel": (
        "Host tool: request cancellation of a running job; completed artifacts remain. Use when the "
        "person asks to stop a job. Do not cancel on your own initiative."),
    "job_retry_failed": (
        "Host tool: retry only missing or failed outputs of a finished job under the original approval. "
        "Use when the person asks to retry. Do not retry on your own initiative."),
    "artifact_inspect": (
        "Verify an artifact checksum and return bounded metadata, linked manifest and QC ids, QC issue "
        "codes and simulation_ready (currently always false). Use before describing a retrieved or "
        "uploaded EPW. Do not claim an EPW is simulation-ready."),
    "weather_visualization_capabilities": (
        "List implemented and planned view families and the variables with units. Use before proposing "
        "a chart. Do not offer planned families as available."),
    "weather_data_describe": (
        "Describe up to 20 EPW artifacts: variables, units, calendar, years and missing hours. Use to "
        "choose a variable or explain data gaps. Do not infer values beyond these counts."),
    "weather_visualize": (
        "Prepare a bounded, framework-neutral view of EPW artifacts (family and variable) and return a "
        "view_id, a factual summary and the first data page for the renderer. Use when the person asks "
        "for a chart of retrieved or uploaded EPWs. Do not restate data rows; describe the summary."),
    "weather_data_page": (
        "Host tool: page prepared view rows by view_id (limit 1-200); offset 0 also returns the spec. "
        "Use when a renderer needs more rows. Do not use it to read data into model context."),
    "weather_export_compact": (
        "Host tool: build a checksummed compact ZIP of a completed job's outputs with its mapping. Use "
        "when the person asks for an export. Do not export without that request; export does not grant "
        "redistribution rights."),
    "weather_fetch": (
        "Legacy alias: store an inline weather plan and submit it with the same person confirmation as "
        "weather_submit. Use only from v0.1 clients. Do not use it in new clients; plan with weather_plan "
        "and submit by hash."),
    "weather_inspect": (
        "Legacy alias for job_inspect (job_id) or artifact_inspect (artifact_id). Use only from v0.1 "
        "clients. Do not use it in new clients."),
}
