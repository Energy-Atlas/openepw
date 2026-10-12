"""Offline service for agent scenarios: the packaged eval stubs plus the GeoNames test files."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_places_geonames import FakeHttp  # noqa: E402

from openepw.agent.evals.stubs import GEOCODER, StubERA5, geocode_results  # noqa: E402
from openepw.config import RuntimeConfig  # noqa: E402
from openepw.service import WeatherService  # noqa: E402

FakeERA5 = StubERA5
__all__ = ["GEOCODER", "FakeERA5", "ScenarioHttp", "scenario_service"]


class ScenarioHttp(FakeHttp):
    """GeoNames files from the unit-test fake plus the packaged geocoder table."""

    def __init__(self, config):
        super().__init__()
        self.config = config          # the service's cached-fetch replay reads http.config

    def get_json(self, url, params=None, **kwargs):
        self.calls.append("geocode:" + params["name"])
        return geocode_results(params["name"])


def scenario_service(tmp_path, fail_near=()):
    config = RuntimeConfig(data_root=tmp_path)
    return WeatherService(config, http=ScenarioHttp(config), providers=[FakeERA5(fail_near)])
