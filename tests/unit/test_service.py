import json

import httpx
import pandas as pd
import pytest

from openepw.config import RuntimeConfig
from openepw.epw import read_epw
from openepw.models import Location, OpenEPWError, WeatherRequest
from openepw.providers.http import HttpClient
from openepw.providers.nsrdb import NSRDBProvider
from openepw.providers.openmeteo import OpenMeteoProvider
from openepw.qc import validate
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


def test_skip_feb_29_emits_explicit_noleap_year(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return transport(request)

    config = RuntimeConfig(data_root=tmp_path)
    service = WeatherService(
        config, http=HttpClient(config, transport=httpx.MockTransport(handler))
    )
    request = WeatherRequest(
        locations=Location(lat=42.45, lon=-76.5, standard_offset_minutes=-300),
        product="amy",
        years=[2024],
        providers=["openmeteo"],
        skip_feb_29=True,
    )

    bundle = service.fetch(request)

    assert len(bundle.weather) == 1
    assert requests[0].url.params["latitude"] == "42.45"
    assert requests[0].url.params["longitude"] == "-76.5"
    path = tmp_path / bundle.weather[0].path
    rows = [line.split(",") for line in path.read_text().splitlines()[8:]]
    assert len(rows) == 8760
    assert not any(row[1:3] == ["2", "29"] for row in rows)
    assert sum(row[1:3] == ["12", "31"] for row in rows) == 24
    assert {row[0] for row in rows} == {"2024"}

    data = read_epw(path)
    assert data.calendar == "noleap"
    assert not any(i.severity == "error" for i in validate(data, "annual"))

    manifest = json.loads((tmp_path / bundle.manifest.path).read_text())
    assert manifest["leap_policy"] == "skip_feb_29"
    assert manifest["outputs"][0]["metadata"]["leap_policy"] == "skip_feb_29"
    assert manifest["outputs"][0]["metadata"]["removed_feb_29_intervals"] == 24
    assert manifest["outputs"][0]["metadata"]["requested_location"]["lat"] == 42.45
    assert manifest["outputs"][0]["source"]["location"]["lat"] == 42.5
    assert all(
        "removed local February 29 intervals" in item["transforms"]
        for item in manifest["outputs"][0]["lineage"].values()
    )


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


def test_discovery_does_not_wait_for_nsrdb_rate_limit(tmp_path):
    attempts = []
    sleeps = []

    def handler(request):
        attempts.append(request)
        return httpx.Response(429, headers={"Retry-After": "54000"})

    config = RuntimeConfig(data_root=tmp_path, retries=2)
    service = WeatherService(
        config,
        http=HttpClient(config, transport=httpx.MockTransport(handler), sleep=sleeps.append),
        providers=[OpenMeteoProvider(), NSRDBProvider()],
    )
    request = WeatherRequest(locations=Location(lat=42.44, lon=-76.5), product="amy", years=[2024])

    result = service.discover(request)

    assert {candidate.source.provider for candidate in result.candidates} == {"openmeteo"}
    assert [issue.code for issue in result.issues] == ["RATE_LIMITED"]
    assert len(attempts) == 1
    assert sleeps == []


def test_discovery_exposes_ranked_candidates_per_location(tmp_path):
    from openepw.models import Candidate
    from test_batch import StationProvider

    class Choices(StationProvider):
        def discover(self, request, location, http):
            best = super().discover(request, location, http)[0]
            weaker = Candidate(
                id=f"weaker-{location.key}",
                location_id=location.key,
                source=best.source,
                missing_fields=["dry_bulb"],
            )
            return [weaker, best]

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[Choices()])
    result = service.discover(
        WeatherRequest(
            locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
            start="2024-01-01",
            end="2024-01-01",
        )
    )
    for location in result.locations:
        ranking = result.ranked_candidate_ids[location.key]
        assert ranking == [f"station{location.key}", f"weaker-{location.key}"]
        assert ranking[0] in result.selected_candidate_ids


def test_dataset_choices_resolve_local_station_per_point(tmp_path):
    from openepw.models import Candidate
    from test_batch import StationProvider

    class LocalStations(StationProvider):
        def discover(self, request, location, http):
            candidate = super().discover(request, location, http)[0]
            candidate.product_id = f"station-{int(location.lat)}"
            return [candidate]

    grid = StationProvider()
    grid.name = "grid"
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[LocalStations(), grid])
    request = WeatherRequest(
        locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
        start="2024-01-01", end="2024-01-01",
        dataset_selections=[
            {"provider": "station", "dataset": "synthetic"},
            {"provider": "grid", "dataset": "synthetic"},
        ],
    )
    plan = service.plan(request)
    assert len(plan.outputs) == 4
    assert len({o.id for o in plan.outputs}) == 4
    assert [(o.requested_location_id, o.dataset_selection.provider) for o in plan.outputs] == [
        (request.locations[0].key, "station"),
        (request.locations[0].key, "grid"),
        (request.locations[1].key, "station"),
        (request.locations[1].key, "grid"),
    ]
    station_outputs = [o for o in plan.outputs if o.dataset_selection.provider == "station"]
    assert "station-1" in station_outputs[0].name
    assert "station-2" in station_outputs[1].name
    assert not plan.issues


def test_unavailable_dataset_is_reported_per_point_without_substitution(tmp_path):
    from test_batch import StationProvider

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    request = WeatherRequest(
        locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
        start="2024-01-01", end="2024-01-01",
        dataset_selections=[
            {"provider": "station", "dataset": "synthetic"},
            {"provider": "missing", "dataset": "unknown"},
        ],
    )
    plan = service.plan(request)
    assert len(plan.outputs) == 2
    assert len(plan.issues) == 2
    assert {issue.location_id for issue in plan.issues} == {p.key for p in request.locations}
    assert all(issue.dataset_selection == {"provider": "missing", "dataset": "unknown", "product_id": None} for issue in plan.issues)


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
