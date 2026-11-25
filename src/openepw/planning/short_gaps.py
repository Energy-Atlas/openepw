"""Short gaps inside a station's records, filled by interpolation (owner decision 3b, 2026-11-22).

A short gap is a run of at most ``MAX_GAP_HOURS`` consecutive missing hours of one variable with
a measured (or earlier filled) value on both sides. Longer gaps, gaps at the start or end of the
series, and solar radiation are never filled here. Values are interpolated linearly in time:

- dry-bulb temperature, dew point, station pressure and wind speed: straight lines;
- relative humidity: worked out again from the interpolated dry bulb and dew point (Magnus, as
  the providers do) where the source derived it that way, else a straight line;
- wind direction: along the shorter arc, only where the wind blows (speed above zero) at both
  ends and through the gap, because a calm hour has no direction.

Every interpolated hour is recorded: lineage notes the count per variable, ``metadata
["interpolated"]`` lists each gap (UTC start and length), and the dataset gains an info issue
``GAPS_INTERPOLATED``. Nothing is adjusted outside the gaps.
"""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

from ..dataset import WeatherDataset
from ..models import Issue

MAX_GAP_HOURS = 3
# Interpolated in this order: humidity and wind direction use the values filled before them.
VARIABLES = ("dry_bulb", "dew_point", "pressure", "wind_speed", "relative_humidity", "wind_direction")
SOLAR = frozenset({"ghi", "dni", "dhi"})
LABELS = {"dry_bulb": "dry-bulb temperature", "dew_point": "dew point", "pressure": "station pressure",
          "wind_speed": "wind speed", "relative_humidity": "relative humidity",
          "wind_direction": "wind direction"}
_HOUR = pd.Timedelta(hours=1)


def gap_runs(values: pd.Series, max_hours: int = MAX_GAP_HOURS) -> list[tuple[int, int]]:
    """(first position, length) of each run of missing values with a value on both sides, at
    most ``max_hours`` long and exactly that many hours apart in time."""
    missing = values.isna().to_numpy()
    index = values.index
    runs, position, count = [], 0, len(missing)
    while position < count:
        if not missing[position]:
            position += 1
            continue
        end = position
        while end < count and missing[end]:
            end += 1
        length = end - position
        if (position > 0 and end < count and length <= max_hours
                and index[end] - index[position - 1] == (length + 1) * _HOUR):
            runs.append((position, length))
        position = end
    return runs


def _magnus(dry_bulb: np.ndarray, dew_point: np.ndarray) -> np.ndarray:
    return 100 * np.exp(17.625 * dew_point / (243.04 + dew_point) - 17.625 * dry_bulb / (243.04 + dry_bulb))


def interpolate_short_gaps(dataset: WeatherDataset, variables: list[str]) -> WeatherDataset:
    """A copy of ``dataset`` with short gaps of the requested non-solar ``variables`` filled."""
    if dataset.interval_minutes != 60:
        return dataset
    result = deepcopy(dataset)
    data = result.data
    asked = [name for name in VARIABLES if name in variables and name in data and name not in SOLAR]
    record: dict[str, dict[str, object]] = {}
    for name in asked:
        column = data[name].to_numpy(dtype=float, copy=True)
        filled_runs = []
        derived_rh = (name == "relative_humidity" and name in result.lineage and result.lineage[name].derived
                      and "dry_bulb" in data and "dew_point" in data)
        for start, length in gap_runs(data[name]):
            before, after = column[start - 1], column[start + length]
            steps = np.arange(1, length + 1) / (length + 1)
            hours = slice(start, start + length)
            if name == "wind_direction":
                if "wind_speed" not in data:
                    continue
                speed = data["wind_speed"].to_numpy(dtype=float)[start - 1:start + length + 1]
                if np.isnan(speed).any() or (speed <= 0).any():
                    continue                       # a calm hour has no direction to carry over
                turn = (after - before + 180) % 360 - 180
                column[hours] = (before + turn * steps) % 360
            elif derived_rh:
                dry = data["dry_bulb"].to_numpy(dtype=float)[hours]
                dew = data["dew_point"].to_numpy(dtype=float)[hours]
                if np.isnan(dry).any() or np.isnan(dew).any():
                    column[hours] = before + (after - before) * steps
                else:
                    column[hours] = _magnus(dry, dew)
            else:
                column[hours] = before + (after - before) * steps
            filled_runs.append((start, length))
        if not filled_runs:
            continue
        data[name] = column
        count = sum(length for _, length in filled_runs)
        record[name] = {"hours": count, "gaps": [[data.index[start].isoformat(), length]
                                                 for start, length in filled_runs]}
        how = {"wind_direction": "along the shorter arc, only while the wind blows",
               "relative_humidity": ("Magnus RH from the interpolated dry bulb and dew point"
                                     if derived_rh else "linear in time")}.get(name, "linear in time")
        if name in result.lineage:
            result.lineage[name].transforms.append(
                f"short gaps interpolated: {count} h in {len(filled_runs)} gap(s) of up to {MAX_GAP_HOURS} h ({how})")
    if record:
        result.metadata = {**result.metadata, "interpolated": record}
        total = sum(int(entry["hours"]) for entry in record.values())  # type: ignore[call-overload]
        listed = ", ".join(f"{LABELS[name]} {entry['hours']} h" for name, entry in record.items())
        result.issues.append(Issue(
            code="GAPS_INTERPOLATED", severity="info", field="short_gaps",
            message=f"Interpolated {total} h in gaps of up to {MAX_GAP_HOURS} hours: {listed}"))
    return result
