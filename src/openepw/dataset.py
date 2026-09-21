"""Scientific tables use UTC interval ends and fixed local standard-time output."""

import calendar
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .models import Issue, Location, OpenEPWError, VariableLineage

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
    "extraterrestrial_horizontal": "Wh/m2",
    "extraterrestrial_direct": "Wh/m2",
    "horizontal_infrared": "Wh/m2",
    "global_illuminance": "lux",
    "direct_illuminance": "lux",
    "diffuse_illuminance": "lux",
    "zenith_luminance": "cd/m2",
    "opaque_sky_cover": "tenths",
    "visibility": "km",
    "ceiling_height": "m",
    "present_weather_observation": "code",
    "present_weather_codes": "code",
    "precipitable_water": "mm",
    "aerosol_optical_depth": "1",
    "snow_depth": "cm",
    "days_since_snow": "day",
    "albedo": "1",
    "liquid_precipitation": "mm",
    "liquid_precipitation_quantity": "h",
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
    return pd.DatetimeIndex(dataset.data.index).tz_localize(None) + pd.Timedelta(
        minutes=dataset.location.standard_offset_minutes - dataset.interval_minutes
    )


def without_feb_29(dataset: WeatherDataset) -> WeatherDataset:
    """Return an explicitly no-leap copy, preserving source-year labels and provenance."""
    local = local_interval_starts(dataset)
    feb_29 = (local.month == 2) & (local.day == 29)
    expected = sum(24 for year in set(local.year) if calendar.isleap(year))
    if int(feb_29.sum()) != expected or not local[feb_29].is_unique:
        raise OpenEPWError(
            "INVALID_LEAP_DAY",
            "skip_feb_29 requires exactly 24 unique local February 29 intervals per leap year",
        )
    keep = ~feb_29
    transform = "removed local February 29 intervals"
    source_years = (
        [year for year, retained in zip(dataset.source_years, keep) if retained]
        if dataset.source_years
        else []
    )
    lineage = {
        name: item.model_copy(
            update={
                "transforms": list(
                    dict.fromkeys([*item.transforms, transform])
                )
            }
        )
        for name, item in dataset.lineage.items()
    }
    return WeatherDataset(
        data=dataset.data.loc[keep].copy(),
        location=dataset.location,
        interval_minutes=dataset.interval_minutes,
        calendar="noleap",
        units=dict(dataset.units),
        lineage=lineage,
        headers=[list(row) for row in dataset.headers],
        source_years=source_years,
        metadata={
            **dataset.metadata,
            "leap_policy": "skip_feb_29",
            "removed_feb_29_intervals": int((~keep).sum()),
        },
        issues=list(dataset.issues),
    )
