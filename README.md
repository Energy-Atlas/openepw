# OpenEPW

Python-first weather discovery, retrieval, EPW conversion and future-weather
generation for building-energy simulation, with REST and MCP adapters over one
core service layer. MIT-licensed software; weather data retain their own licenses.

**Status: Stage 1 validation complete; Stage 2 design awaits owner approval.**
There is no installable OpenEPW implementation in this repository yet. Do not
interpret the examples below as working commands or a published PyPI release.

Start with the [Stage 2 plan](docs/plans/2026-09-20-stage-2.md),
[validated providers](docs/providers/README.md), [architecture](ARCHITECTURE.md),
[features](FEATURES.md), [roadmap](ROADMAP.md), and
[handoff brief](docs/20260920-openepw-brief.md).

Planned installation after implementation (publication is a separate owner action):

```bash
python -m pip install .
python -m pip install ".[api,mcp,climate]"
```

Proposed Python workflow:

```python
import openepw
from openepw import Location, WeatherRequest

request = WeatherRequest(
    locations=Location(lat=42.44, lon=-76.50),
    years=[2024], product="historical", provider="openmeteo", dataset="era5",
)
candidates = openepw.discover(request)
plan = openepw.plan(request, discovery=candidates)
bundle = openepw.execute(plan)
# Convenience: bundle = openepw.fetch(request)

future = openepw.generate_future(
    baseline=bundle.weather[0], target_year=2050, reference_period=(1995, 2014),
    climate_scenario="ssp245", method="morph", profile="typical",
)
```

Geocoding is separate: `openepw.geocode("Ithaca")` returns candidates, not an
unannounced weather-provider choice. For large requests, inspect the serialized
plan before execution. EPWs ship with request, plan, manifest and QC artifacts.
Historical TMY/XMY synthesis is outside v0.1; retrieve published products instead.

The proposed second future method uses hourly WRF trajectories at published U.S.
locations, with RCP scenarios and fixed periods. It has different capabilities
from global CMIP6 morphing. See [scientific definitions](docs/methods/future-weather.md).

To repeat the Stage 1 checks, use the dependency-free
[probe instructions](docs/validation/README.md). Credentials and raw downloads
stay local. See [contributing](CONTRIBUTING.md) and [license review](docs/methods/reuse-review.md).
