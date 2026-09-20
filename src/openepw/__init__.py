"""OpenEPW's Python domain API. Heavy adapters are imported only on demand."""

__version__ = "0.1.0"

from .models import FutureRequest, Location, WeatherPlan, WeatherRequest

__all__ = ["FutureRequest", "Location", "WeatherPlan", "WeatherRequest"]


def geocode(query, *, mode="point", config=None):
    from .service import WeatherService

    return WeatherService(config).geocode(query, mode=mode)


def discover(request, *, config=None):
    from .service import WeatherService

    return WeatherService(config).discover(request)


def plan(request, *, discovery=None, config=None):
    from .service import WeatherService

    return WeatherService(config).plan(request, discovery=discovery)


def execute(plan, *, config=None):
    from .service import WeatherService

    return WeatherService(config).execute(plan)


def fetch(request, *, config=None):
    from .service import WeatherService

    return WeatherService(config).fetch(request)


def plan_future(request, *, config=None):
    from .service import WeatherService

    return WeatherService(config).plan_future(request)


def generate_future(
    baseline,
    *,
    target_year=None,
    climate_period=None,
    reference_period=None,
    climate_scenario,
    method="morph",
    profile="typical",
    models=None,
    members=None,
    extreme=None,
    signals=None,
    config=None,
):
    import uuid

    from .dataset import WeatherDataset
    from .epw.writer import epw_bytes
    from .models import ArtifactRef
    from .service import WeatherService

    service = WeatherService(config)
    if isinstance(baseline, WeatherDataset):
        baseline = service.artifacts.write(
            uuid.uuid4().hex, "baseline.epw", epw_bytes(baseline), "baseline"
        ).id
    elif isinstance(baseline, ArtifactRef):
        baseline = baseline.id
    request = FutureRequest(
        baseline=str(baseline),
        target_year=target_year,
        climate_period=climate_period,
        reference_period=reference_period,
        climate_scenario=climate_scenario,
        method=method,
        profile=profile,
        models=models or [],
        members=members or [],
        extreme=extreme or {},
        signals=str(signals) if signals else None,
    )
    return service.execute(service.plan_future(request))
