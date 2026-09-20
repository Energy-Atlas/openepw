import json

import httpx
import pandas as pd
import pytest

from openepw.config import RuntimeConfig
from openepw.epw import read_epw
from openepw.models import Location, OpenEPWError, WeatherRequest
from openepw.providers.http import HttpClient
from openepw.service import WeatherService


def transport(request):
    q = request.url.params
    times = pd.date_range(q["start_date"], q["end_date"] + " 23:00", freq="h")
    hourly = {"time": times.strftime("%Y-%m-%dT%H:%M").tolist()}
    units = {}
    for name in q["hourly"].split(","):
        value, unit = {
            "temperature_2m": (20, "°C"),
            "dew_point_2m": (10, "°C"),
            "relative_humidity_2m": (50, "%"),
            "surface_pressure": (1013.25, "hPa"),
            "shortwave_radiation": (0, "W/m²"),
            "direct_normal_irradiance": (0, "W/m²"),
            "diffuse_radiation": (0, "W/m²"),
            "wind_speed_10m": (2, "m/s"),
            "wind_direction_10m": (180, "°"),
        }[name]
        hourly[name] = [value] * len(times)
        units[name] = unit
    return httpx.Response(
        200,
        json={
            "latitude": 42.5,
            "longitude": -76.5,
            "elevation": 200,
            "hourly": hourly,
            "hourly_units": units,
        },
    )


def test_leap_local_year_bundle_and_exact_replay(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return transport(request)

    config = RuntimeConfig(data_root=tmp_path)
    service = WeatherService(
        config, http=HttpClient(config, transport=httpx.MockTransport(handler))
    )
    request = WeatherRequest(
        locations=[Location(lat=42.44, lon=-76.5, standard_offset_minutes=-300)],
        years=[2024],
        providers=["openmeteo"],
    )
    plan = service.plan(request)
    bundle = service.execute(plan)
    data = read_epw(tmp_path / bundle.weather[0].path)
    assert len(data.data) == 8784
    assert data.data.index[0] == pd.Timestamp("2024-01-01T06:00Z")
    assert data.data.index[-1] == pd.Timestamp("2025-01-01T05:00Z")
    assert data.data.pressure.iloc[0] == 101325
    manifest = json.loads((tmp_path / bundle.manifest.path).read_text())
    assert manifest["outputs"][0]["lineage"]["dry_bulb"]["source"]["location"]["lat"] == 42.5
    service.execute(plan)
    assert len(calls) == 1


def test_retry_bounds_and_error_does_not_leak_key(tmp_path):
    attempts = []

    def handler(r):
        attempts.append(1)
        return httpx.Response(503)

    h = HttpClient(
        RuntimeConfig(data_root=tmp_path, retries=2),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    with pytest.raises(OpenEPWError) as exc:
        h.get("https://example.org/api", params={"api_key": "test-secret-value"})
    assert len(attempts) == 3
    assert "test-secret-value" not in str(exc.value)


def test_empty_weather_does_not_succeed(tmp_path):
    h = HttpClient(
        RuntimeConfig(data_root=tmp_path),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hourly": {"time": []}})),
    )
    s = WeatherService(h.config, http=h)
    r = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024], providers=["openmeteo"])
    b = s.fetch(r)
    assert not b.weather
    assert any(i.severity == "error" for i in b.issues)


def test_nsrdb_approved_redirect_does_not_forward_credentials(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                302,
                headers={
                    "Location": "https://s3.us-west-2.amazonaws.com/nsrdb-data.stratus.nlr.gov/data.csv?signature=safe"
                },
            )
        assert "PRIVATE-TOKEN" not in request.headers
        assert "api_key" not in request.url.params
        return httpx.Response(200, content=b"weather")

    http = HttpClient(RuntimeConfig(data_root=tmp_path), transport=httpx.MockTransport(handler))
    assert (
        http.get(
            "https://developer.nlr.gov/api/data",
            params={"api_key": "secret"},
            headers={"PRIVATE-TOKEN": "secret"},
        )
        == b"weather"
    )


def test_fractional_hour_request_fails_before_network(tmp_path):
    def handler(request):
        raise AssertionError("Should reject before network")

    config = RuntimeConfig(data_root=tmp_path)
    service = WeatherService(
        config, http=HttpClient(config, transport=httpx.MockTransport(handler))
    )
    r = WeatherRequest(
        locations=Location(lat=20, lon=75, standard_offset_minutes=330),
        years=[2024],
        providers=["openmeteo"],
    )
    with pytest.raises(OpenEPWError) as exc:
        service.plan(r)
    assert exc.value.issue.code == "UNSUPPORTED_TIMEZONE"
