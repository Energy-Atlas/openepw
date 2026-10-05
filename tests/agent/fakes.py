"""Offline service for agent scenarios: fake geocoder, GeoNames files and an ERA5-like provider."""

import hashlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_places_geonames import FakeHttp  # noqa: E402

from openepw.config import RuntimeConfig  # noqa: E402
from openepw.dataset import WeatherDataset  # noqa: E402
from openepw.models import Candidate, OpenEPWError, SourceRef, VariableLineage  # noqa: E402
from openepw.providers.base import ProviderResult  # noqa: E402
from openepw.providers.openmeteo import interval_bounds  # noqa: E402
from openepw.service import WeatherService  # noqa: E402

GEOCODER = {
    "Ithaca, NY": [("Ithaca, New York, United States", 42.44, -76.50)],
    "Springfield": [("Springfield, Illinois, United States", 39.80, -89.64),
                    ("Springfield, Massachusetts, United States", 42.10, -72.59),
                    ("Springfield, Missouri, United States", 37.21, -93.29)],
    "Boston": [("Boston, Massachusetts, United States", 42.36, -71.06)],
    "Austin": [("Austin, Texas, United States", 30.27, -97.74)],
    "Denver": [("Denver, Colorado, United States", 39.74, -104.98)],
    "Phoenix": [("Phoenix, Arizona, United States", 33.45, -112.07)],
}
VALUES = {"dry_bulb": 10.0, "dew_point": 5.0, "relative_humidity": 70.0, "pressure": 101325.0,
          "wind_speed": 3.0, "wind_direction": 180.0, "ghi": 0.0, "dni": 0.0, "dhi": 0.0}


class ScenarioHttp(FakeHttp):
    """GeoNames files from the unit-test fake plus a small Open-Meteo geocoder table."""

    def __init__(self, config):
        super().__init__()
        self.config = config          # the service's cached-fetch replay reads http.config

    def get_json(self, url, params=None, **kwargs):
        self.calls.append("geocode:" + params["name"])
        return {"results": [{"id": index + 1, "name": name, "latitude": lat, "longitude": lon}
                            for index, (name, lat, lon) in enumerate(GEOCODER.get(params["name"], []))]}


class FakeERA5:
    """Answers openmeteo/era5 selections with constant hourly weather for the requested period."""

    name = "openmeteo"

    def __init__(self, fail_near=()):
        self.calls = 0
        self.fail_near = list(fail_near)      # (lat, lon) points whose fetch fails

    def discover(self, request, location, http):
        source = SourceRef(provider=self.name, dataset="era5",
                           identity=f"{location.lat:.2f},{location.lon:.2f}",
                           location=location, provisional=False)
        return [Candidate(id=self.name + location.key, location_id=location.key, source=source,
                          variables=list(VALUES))]

    def fetch(self, task, http):
        self.calls += 1
        location = task.source.location
        if any(abs(location.lat - lat) < 0.5 and abs(location.lon - lon) < 0.5 for lat, lon in self.fail_near):
            raise OpenEPWError("PROVIDER_ERROR", "Fake provider outage for this point", retryable=True)
        start, end = interval_bounds(task.parameters)
        index = pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
        frame = pd.DataFrame({name: [value] * len(index) for name, value in VALUES.items()}, index=index)
        lineage = {variable: VariableLineage(variable=variable, source=task.source,
                                             raw_sha256=hashlib.sha256(b"fake-era5").hexdigest())
                   for variable in frame}
        return ProviderResult(WeatherDataset(data=frame, location=task.source.location, lineage=lineage),
                              task.source, b"fake-era5")


def scenario_service(tmp_path, fail_near=()):
    config = RuntimeConfig(data_root=tmp_path)
    return WeatherService(config, http=ScenarioHttp(config), providers=[FakeERA5(fail_near)])
