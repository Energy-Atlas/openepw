import os

import pytest

from openepw.config import RuntimeConfig
from openepw.epw import read_epw
from openepw.models import FutureRequest, Location, WeatherRequest
from openepw.service import WeatherService


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("OPENEPW_RUN_CDS") != "1", reason="Set OPENEPW_RUN_CDS=1 for queued CDS retrievals"
)
@pytest.mark.parametrize("dataset", ["reanalysis-era5-single-levels", "reanalysis-era5-land"])
def test_direct_cds(dataset):
    config = RuntimeConfig.load(env_file=".env", data_root=".local/live-cds")
    service = WeatherService(config)
    bundle = service.fetch(
        WeatherRequest(
            locations=Location(lat=42.44, lon=-76.5),
            providers=["cds"],
            dataset=dataset,
            start="2024-01-02",
            end="2024-01-02",
        )
    )
    assert len(bundle.weather) == 1, [(i.code, i.message) for i in bundle.issues]
    data = read_epw(config.data_root / bundle.weather[0].path)
    assert len(data.data) == 24
    assert data.data.ghi.notna().all()
    assert data.data.dni.isna().all()


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("OPENEPW_RUN_CLIMATE") != "1",
    reason="Set OPENEPW_RUN_CLIMATE=1 for climate archive checks",
)
@pytest.mark.parametrize(
    "method,profile,extreme,count",
    [
        ("morph", "typical", {}, 1),
        ("morph", "extreme", {"mode": "warming", "quantile": 0.95}, 1),
        ("climate_profile", "typical", {}, 1),
        ("climate_profile", "ensemble", {}, 10),
        ("climate_profile", "extreme", {"type": "hot", "mode": "shock"}, 1),
        ("climate_profile", "extreme", {"type": "hot", "mode": "persistence"}, 1),
    ],
)
def test_future_live(method, profile, extreme, count):
    config = RuntimeConfig(
        data_root=".local/live-cmip" if method == "morph" else ".local/live-hourly", timeout=120
    )
    service = WeatherService(config)
    baseline = service.fetch(
        WeatherRequest(
            locations=Location(lat=34.65, lon=-87.765), providers=["openmeteo"], years=[2023]
        )
    )
    assert baseline.weather
    request = FutureRequest(
        baseline=baseline.weather[0].id,
        method=method,
        target_year=2050,
        reference_period=(1985, 2014) if method == "morph" else None,
        climate_scenario="ssp245" if method == "morph" else "rcp85",
        profile=profile,
        extreme=extreme,
    )
    plan = service.plan_future(request)
    bundle = service.execute(plan)
    assert len(bundle.weather) == count
    assert not any(i.severity == "error" for i in bundle.issues)
