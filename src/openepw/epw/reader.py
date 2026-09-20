import csv
import io
from pathlib import Path

import numpy as np
import pandas as pd

from ..dataset import WeatherDataset
from ..models import Issue, Location, OpenEPWError
from .schema import FIELDS, HEADER_NAMES


def read_epw(path: str | Path | bytes) -> WeatherDataset:
    try:
        body = path if isinstance(path, bytes) else Path(path).read_bytes()
        rows = list(csv.reader(io.StringIO(body.decode("utf-8-sig", errors="replace"))))
        names = [r[0].upper() if r else '' for r in rows[:8]]
        if len(names) > 4 and names[4] == 'HOLIDAYS/DAYLIGHT SAVING':
            names[4] = 'HOLIDAYS/DAYLIGHT SAVINGS'
        if len(rows) <= 8 or names != HEADER_NAMES:
            raise ValueError("Expected eight EPW headers and weather rows")
        if any(len(r) != 35 for r in rows[8:]):
            raise ValueError("Expected 35 fields in every data row")
        header = rows[0]
        location = Location(
            name=header[1],
            lat=float(header[6]),
            lon=float(header[7]),
            standard_offset_minutes=round(float(header[8]) * 60),
            elevation=float(header[9]),
        )
        labels = np.asarray([[int(v) for v in r[:5]] for r in rows[8:]])
        if (
            not np.isin(labels[:, 3], np.arange(1, 25)).all()
            or not np.isin(labels[:, 4], [0, 60]).all()
        ):
            raise ValueError("Only hourly EPW labels 1..24, minute 0/60 are supported")
        source_years = labels[:, 0].tolist()
        synthetic = len(set(source_years)) > 1
        # Preserve a real continuous multi-year file; mixed TMY months use a synthetic calendar.
        actual = pd.to_datetime(
            dict(year=labels[:, 0], month=labels[:, 1], day=labels[:, 2])
        ) + pd.to_timedelta(labels[:, 3], unit="h")
        if (
            actual.is_monotonic_increasing
            and actual.is_unique
            and (actual.diff().iloc[1:] == pd.Timedelta(hours=1)).all()
        ):
            synthetic = False
        years = (
            np.full(
                len(labels), 2000 if ((labels[:, 1] == 2) & (labels[:, 2] == 29)).any() else 2001
            )
            if synthetic
            else labels[:, 0]
        )
        ends = pd.DatetimeIndex(
            pd.to_datetime(dict(year=years, month=labels[:, 1], day=labels[:, 2]))
            + pd.to_timedelta(labels[:, 3], unit="h")
            - pd.Timedelta(minutes=location.standard_offset_minutes)
        ).tz_localize("UTC")
        values = np.asarray([[float(v) for v in r[6:]] for r in rows[8:]])
        for i, (_, sentinel) in enumerate(FIELDS):
            values[values[:, i] == sentinel, i] = np.nan
        data = pd.DataFrame(values, index=ends, columns=[f[0] for f in FIELDS])
        data["flags"] = [r[5] for r in rows[8:]]
        issues = (
            [
                Issue(
                    code="NATIVE_MINUTE_ZERO",
                    message="Native hourly minute 0 interpreted as an hour interval; normalized output uses minute 60",
                )
            ]
            if (labels[:, 4] == 0).any()
            else []
        )
        return WeatherDataset(
            data=data,
            location=location,
            calendar="synthetic" if synthetic else "gregorian",
            headers=rows[:8],
            source_years=source_years,
            issues=issues,
        )
    except (ValueError, IndexError, OverflowError) as exc:
        raise OpenEPWError(
            "EPW_CONVERSION_FAILED", "Invalid EPW structure, coordinates or numeric/time fields"
        ) from exc
