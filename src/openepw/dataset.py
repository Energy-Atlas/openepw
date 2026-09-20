"""Scientific tables use UTC interval ends and fixed local standard-time output."""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .models import Issue, Location, VariableLineage

UNITS = {
    "dry_bulb": "degC",
    "dew_point": "degC",
    "relative_humidity": "%",
    "pressure": "Pa",
    "ghi": "Wh/m2",
    "dni": "Wh/m2",
    "dhi": "Wh/m2",
    "wind_speed": "m/s",
    "wind_direction": "degree",
    "total_sky_cover": "tenths",
}


@dataclass
class WeatherDataset:
    data: pd.DataFrame
    location: Location
    interval_minutes: int = 60
    calendar: str = "gregorian"
    units: dict[str, str] = field(default_factory=lambda: dict(UNITS))
    lineage: dict[str, VariableLineage] = field(default_factory=dict)
    headers: list[list[str]] = field(default_factory=list)
    source_years: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.data.index, pd.DatetimeIndex) or self.data.index.tz is None:
            raise ValueError("WeatherDataset requires timezone-aware UTC interval ends")
        self.data.index = self.data.index.tz_convert("UTC")


def irradiance_to_energy(value, interval_minutes: float):
    if interval_minutes <= 0:
        raise ValueError("Positive interval required")
    return value * interval_minutes / 60


def local_interval_starts(dataset: WeatherDataset) -> pd.DatetimeIndex:
    return dataset.data.index.tz_localize(None) + pd.Timedelta(
        minutes=dataset.location.standard_offset_minutes - dataset.interval_minutes
    )
