import numpy as np
import pandas as pd

from ..dataset import WeatherDataset, local_interval_starts
from ..models import Issue

ESSENTIAL = [
    "dry_bulb",
    "dew_point",
    "relative_humidity",
    "pressure",
    "ghi",
    "dni",
    "dhi",
    "wind_speed",
    "wind_direction",
]


def validate(dataset: WeatherDataset, profile: str = "standard") -> list[Issue]:
    if profile not in ("standard", "annual", "strict"):
        raise ValueError("Unknown QC profile")
    issues = list(dataset.issues)
    data = dataset.data

    def add(code, message, field=None, error=False):
        issues.append(
            Issue(
                code=code,
                message=message,
                field=field,
                severity="error" if error or profile == "strict" else "warning",
            )
        )

    if data.empty:
        add("EMPTY_DATA", "No weather intervals", error=True)
        return issues
    if not data.index.is_unique:
        add("DUPLICATE_TIME", "Duplicate interval ends", error=True)
    if not data.index.is_monotonic_increasing:
        add("UNSORTED_TIME", "Intervals are not chronological", error=True)
    local = local_interval_starts(dataset)
    if len(data) > 1:
        expected_intervals = pd.date_range(
            local[0], local[-1], freq=pd.Timedelta(minutes=dataset.interval_minutes)
        )
        if dataset.calendar == "noleap":
            expected_intervals = expected_intervals[
                ~((expected_intervals.month == 2) & (expected_intervals.day == 29))
            ]
        if not local.equals(expected_intervals):
            add("MISSING_INTERVAL", "Non-contiguous intervals", error=True)
    if profile == "annual":
        expected = pd.date_range(
            f"{local[0].year}-01-01", f"{local[0].year + 1}-01-01", freq="h", inclusive="left"
        )
        if dataset.calendar == "noleap":
            expected = expected[~((expected.month == 2) & (expected.day == 29))]
        if not local.equals(expected):
            add("INCOMPLETE_YEAR", "Expected one complete local standard-time year", error=True)
    for variable in ESSENTIAL:
        if variable not in data or data[variable].isna().any():
            add(
                "MISSING_CRITICAL_VARIABLE",
                f"Missing values in {variable}; inspect before simulation",
                variable,
            )
    for name, low, high in [
        ("dry_bulb", -70, 70),
        ("dew_point", -70, 70),
        ("relative_humidity", 0, 110),
        ("pressure", 31000, 120000),
        ("wind_speed", 0, 75),
        ("wind_direction", 0, 360),
    ]:
        if name in data and ((data[name] < low) | (data[name] > high) | np.isinf(data[name])).any():
            add("OUT_OF_RANGE", f"{name} outside EPW/plausibility bounds", name)
    if {"dew_point", "dry_bulb"} <= set(data) and (data.dew_point > data.dry_bulb + 0.1).any():
        add("DEW_ABOVE_DRY", "Dew point exceeds dry bulb")
    if "relative_humidity" in data and (data.relative_humidity > 100).any():
        add("RH_SUPERSATURATED", "RH above 100%; accepted syntactically, review physically")
    for name in ("ghi", "dni", "dhi"):
        if name in data and (data[name] < 0).any():
            add("NEGATIVE_SOLAR", "Negative interval solar energy", name)
    # Approximate solar altitude at interval midpoint; flag only well below horizon.
    middle = pd.DatetimeIndex(data.index) - pd.Timedelta(minutes=dataset.interval_minutes / 2)
    day = middle.dayofyear.to_numpy()
    b = 2 * np.pi * (day - 81) / 364
    eot = 9.87 * np.sin(2 * b) - 7.53 * np.cos(b) - 1.5 * np.sin(b)
    hour = (
        middle.hour.to_numpy()
        + middle.minute.to_numpy() / 60
        + dataset.location.lon / 15
        + eot / 60
    )
    dec = np.deg2rad(23.45) * np.sin(2 * np.pi * (284 + day) / 365)
    lat = np.deg2rad(dataset.location.lat)
    altitude = np.rad2deg(
        np.arcsin(
            np.sin(lat) * np.sin(dec)
            + np.cos(lat) * np.cos(dec) * np.cos(np.deg2rad(15 * (hour - 12)))
        )
    )
    if "ghi" in data and ((altitude < -12) & (data.ghi.to_numpy() > 20)).any():
        add(
            "NIGHTTIME_SOLAR",
            "GHI above 20 Wh/m2 with midpoint sun below -12 degrees; inspect timing",
        )
    return issues
