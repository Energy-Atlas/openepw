# Python API

The generated UI catalog enumerates every public function in `openepw` and its
current signature. Source of truth: `src/openepw/__init__.py`; regeneration:
`python scripts/export_api_catalog.py` with the MCP extra installed.

- `geocode(query, mode, config)`: resolve candidates; choose one explicitly.
- `discover(request, config)`: source alternatives, credentials and missing variables.
- `plan(request, discovery, config)`: inspect sources, output mappings and estimates.
- `execute(plan, config)`: return an ArtifactBundle; inspect issues and partial outputs.
- `fetch(request, config)`: convenience planning/execution.
- `plan_future(request, config)`: baseline and climate-window-aware planning.
- `generate_future(baseline, ..., config)`: full future output using one of two methods.

Named options are keyword arguments; see generated signatures for exact defaults.
`WeatherRequest`, `FutureRequest`, `Location`, `WeatherPlan`, `WeatherJob` and
`ArtifactBundle` are Pydantic contracts. `WeatherService` exposes the same operations
for injected providers and also `preview_artifact(id, start, limit, variables)`.
See [usage](../usage.md) and [scientific limitations](../limitations.md).
