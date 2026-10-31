"""Offline stand-ins for evals: a small geocoder table and a constant ERA5-like provider.

They keep eval runs deterministic and free; ``openepw eval --live-providers`` uses the real
geocoder and providers instead. The weather they return is synthetic and is not for analysis.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from ...config import RuntimeConfig
from ...dataset import WeatherDataset
from ...models import Candidate, OpenEPWError, SourceRef, VariableLineage
from ...providers.base import ProviderResult
from ...providers.openmeteo import interval_bounds
from ...service import WeatherService

GEOCODER: dict[str, list[tuple[str, float, float]]] = {
    "Ithaca, NY": [("Ithaca, New York, United States", 42.44, -76.50)],
    "Springfield": [("Springfield, Illinois, United States", 39.80, -89.64),
                    ("Springfield, Massachusetts, United States", 42.10, -72.59),
                    ("Springfield, Missouri, United States", 37.21, -93.29)],
    "Boston": [("Boston, Massachusetts, United States", 42.36, -71.06)],
    "Austin": [("Austin, Texas, United States", 30.27, -97.74)],
    "Denver": [("Denver, Colorado, United States", 39.74, -104.98)],
    "Phoenix": [("Phoenix, Arizona, United States", 33.45, -112.07)],
}
STATE_CODES = {"New York": "NY", "Illinois": "IL", "Massachusetts": "MA", "Missouri": "MO",
               "Texas": "TX", "Colorado": "CO", "Arizona": "AZ"}
VALUES = {"dry_bulb": 10.0, "dew_point": 5.0, "relative_humidity": 70.0, "pressure": 101325.0,
          "wind_speed": 3.0, "wind_direction": 180.0, "ghi": 0.0, "dni": 0.0, "dhi": 0.0}


def geocode_results(name: str) -> dict[str, Any]:
    """An Open-Meteo-shaped geocoder answer from the table.

    Like the real search, the place name before any comma is matched case-insensitively and the
    rest narrows the matches (a region name or its initials), so "Ithaca" and "Ithaca, NY" find
    Ithaca, "Springfield, Massachusetts" finds one Springfield, and "Ithaca NY" finds nothing.
    """
    place, _, region = (part.strip() for part in name.partition(","))
    rows = [row for key, entries in GEOCODER.items() if key.split(",")[0].strip().casefold() == place.casefold()
            for row in entries]
    if region:
        def matches(label: str) -> bool:
            parts = [part.strip() for part in label.split(",")[1:]]
            codes = {STATE_CODES.get(part, "") for part in parts}
            return region.casefold() in label.casefold() or region.upper() in codes
        rows = [row for row in rows if matches(row[0])]
    return {"results": [{"id": index + 1, "name": label, "latitude": lat, "longitude": lon}
                        for index, (label, lat, lon) in enumerate(rows)]}


class StubHttp:
    """Answers geocoder lookups from the table; any other download is refused."""

    def __init__(self, config: RuntimeConfig):
        self.config = config          # the service's cached-fetch replay reads http.config
        self.calls: list[str] = []

    def get_json(self, url: str, params: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        name = (params or {}).get("name", "")
        self.calls.append("geocode:" + name)
        return geocode_results(name)

    def get(self, url: str, **kwargs: Any) -> bytes:
        raise OpenEPWError("STUB_OFFLINE", "Eval stubs do not download files; use --live-providers")

    def request(self, *args: Any, **kwargs: Any) -> Any:
        raise OpenEPWError("STUB_OFFLINE", "Eval stubs do not download files; use --live-providers")


class StubERA5:
    """Answers openmeteo/era5 selections with constant hourly weather for the requested period."""

    name = "openmeteo"

    def __init__(self, fail_near: Iterable[tuple[float, float]] = ()):
        self.calls = 0
        self.fail_near = list(fail_near)      # (lat, lon) points whose fetch fails

    def discover(self, request: Any, location: Any, http: Any) -> list[Candidate]:
        source = SourceRef(provider=self.name, dataset="era5",
                           identity=f"{location.lat:.2f},{location.lon:.2f}",
                           location=location, provisional=False)
        return [Candidate(id=self.name + location.key, location_id=location.key, source=source,
                          variables=list(VALUES))]

    def fetch(self, task: Any, http: Any) -> ProviderResult:
        self.calls += 1
        location = task.source.location
        if any(abs(location.lat - lat) < 0.5 and abs(location.lon - lon) < 0.5 for lat, lon in self.fail_near):
            raise OpenEPWError("PROVIDER_ERROR", "Stub provider outage for this point", retryable=True)
        start, end = interval_bounds(task.parameters)
        index = pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
        frame = pd.DataFrame({name: [value] * len(index) for name, value in VALUES.items()}, index=index)
        lineage = {variable: VariableLineage(variable=variable, source=task.source,
                                             raw_sha256=hashlib.sha256(b"stub-era5").hexdigest())
                   for variable in VALUES}
        return ProviderResult(WeatherDataset(data=frame, location=task.source.location, lineage=lineage),
                              task.source, b"stub-era5")


def synthetic_epw(city: str = "Ithaca", year: int = 2023) -> bytes:
    """A constant-weather annual EPW whose header names ``city`` (evals plant text there)."""
    from ...epw.writer import epw_bytes
    from ...models import Location

    index = pd.date_range(f"{year}-01-01 01:00", periods=8760, freq="h", tz="UTC")
    frame = pd.DataFrame({name: [value] * len(index) for name, value in VALUES.items()}, index=index)
    return epw_bytes(WeatherDataset(data=frame, location=Location(lat=42.44, lon=-76.5, name=city)))


class StubService(WeatherService):
    """The service with offers the stub catalog does not list for some years (``unlisted``)."""

    def __init__(self, *args: Any, unlisted: dict[str, list[int]] | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.unlisted = dict(unlisted or {})

    def product_offers(self, locations: Any, *, product: str | None = None,
                       provider: str | None = None, years: list[int] | None = None) -> dict:
        data = super().product_offers(locations, product=product, provider=provider, years=years)
        asked = set(years or [])
        data["options"] = [option for option in data["options"]
                           if not asked & set(self.unlisted.get(option["id"], []))]
        return data


def stub_service(data_root: str | Path, fail_near: Iterable[tuple[float, float]] = (),
                 unlisted: dict[str, list[int]] | None = None) -> WeatherService:
    config = RuntimeConfig(data_root=Path(data_root))
    return StubService(config, http=StubHttp(config), providers=[StubERA5(fail_near)], unlisted=unlisted)
