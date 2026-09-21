"""Bounded weather inspection; missing samples stay missing in summaries."""

import calendar as cal
from typing import Any

import numpy as np
import pandas as pd
from pydantic import Field

from .dataset import UNITS, local_interval_starts
from .models import Location, Model, OpenEPWError


class PreviewRow(Model):
    timestamp: str
    source_year: int | None = None
    values: dict[str, float | None]


class SummaryValue(Model):
    valid: int
    mean: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    sum: float | None = None


class MonthlySummary(Model):
    source_years: list[int] = Field(default_factory=list)
    year: int
    month: int
    expected: int
    values: dict[str, SummaryValue]


class WeatherPreview(Model):
    total_rows: int
    start: int
    location: Location
    calendar: str
    source_years: list[int]
    units: dict[str, str]
    rows: list[PreviewRow]
    monthly: list[MonthlySummary]
    synthetic_chronology: bool = False
    simulation_ready: bool = False
    warnings: list[str] = Field(default_factory=list)


class WeatherVisualization(Model):
    location: Location
    calendar: str
    total_rows: int
    timestamps: list[str]
    source_years: list[int | None]
    units: dict[str, str]
    series: dict[str, list[float | None]]
    monthly: list[MonthlySummary]
    synthetic_chronology: bool = False
    simulation_ready: bool = False
    warnings: list[str] = Field(default_factory=list)


SUM_VARIABLES = {
    "extraterrestrial_horizontal",
    "extraterrestrial_direct",
    "horizontal_infrared",
    "ghi",
    "dni",
    "dhi",
    "liquid_precipitation",
}
WARNINGS = [
    "Timestamps use fixed local standard-time interval starts",
    "Partial monthly summaries use valid samples only; inspect valid versus expected counts",
]


def _variables(dataset, variables, *, maximum=None):
    if variables is None:
        preferred = ["dry_bulb", "liquid_precipitation", "dni"]
        variables = [name for name in preferred if name in dataset.data]
        if not variables:
            variables = [name for name in UNITS if name in dataset.data][: (maximum or 4)]
    if maximum is not None and not 1 <= len(variables) <= maximum:
        limit = "four" if maximum == 4 else str(maximum)
        raise OpenEPWError("INVALID_REQUEST", f"Visualization requires one to {limit} variables")
    if (
        not variables
        or len(variables) != len(set(variables))
        or any(
            name not in UNITS
            or name not in dataset.data
            or not pd.api.types.is_numeric_dtype(dataset.data[name])
            for name in variables
        )
    ):
        raise OpenEPWError("INVALID_REQUEST", "Unknown or non-numeric weather variable")
    return variables


def _expected(dataset, start, stop):
    if stop <= start:
        return 0
    intervals = pd.date_range(
        start=start,
        end=stop - pd.Timedelta(minutes=dataset.interval_minutes),
        freq=pd.Timedelta(minutes=dataset.interval_minutes),
    )
    if dataset.calendar == "noleap":
        intervals = intervals[~((intervals.month == 2) & (intervals.day == 29))]
    return len(intervals)


def _summary(dataset, variables):
    frame = dataset.data[variables].replace([np.inf, -np.inf], np.nan)
    local = local_interval_starts(dataset)
    source_values = (
        dataset.source_years if len(dataset.source_years) == len(frame) else [None] * len(frame)
    )
    source = pd.Series(source_values, index=frame.index)
    synthetic = any(pd.notna(y) and int(y) != t.year for y, t in zip(source, local))
    monthly = []
    span_start = local.min()
    span_stop = local.max() + pd.Timedelta(minutes=dataset.interval_minutes)
    for (year, month), group in frame.groupby([local.year, local.month]):
        days = 28 if dataset.calendar == "noleap" and month == 2 else cal.monthrange(year, month)[1]
        month_start = pd.Timestamp(year=year, month=month, day=1)
        month_stop = month_start + pd.Timedelta(days=days)
        expected = _expected(dataset, max(month_start, span_start), min(month_stop, span_stop))
        values = {}
        for name in variables:
            finite = group[name].dropna()
            kwargs: dict[str, Any] = {"valid": len(finite)}
            if len(finite):
                if name in SUM_VARIABLES:
                    kwargs["sum"] = float(finite.sum())
                else:
                    kwargs.update(
                        mean=float(finite.mean()),
                        minimum=float(finite.min()),
                        maximum=float(finite.max()),
                    )
            values[name] = SummaryValue(**kwargs)
        monthly.append(
            MonthlySummary(
                year=int(year),
                month=int(month),
                expected=expected,
                values=values,
                source_years=sorted({int(y) for y in source.loc[group.index].dropna()}),
            )
        )
    return frame, local, source, synthetic, monthly


def preview(dataset, start=0, limit=168, variables=None):
    if start < 0 or not 1 <= limit <= 168:
        raise OpenEPWError("INVALID_REQUEST", "Preview requires start >= 0 and limit 1..168")
    variables = _variables(dataset, variables)
    frame, _local, source, synthetic, monthly = _summary(dataset, variables)
    rows = [
        PreviewRow(
            timestamp=t.isoformat(),
            source_year=int(source.loc[t]) if pd.notna(source.loc[t]) else None,
            values={k: float(v) if pd.notna(v) else None for k, v in row.items()},
        )
        for t, row in frame.iloc[start : start + limit].iterrows()
    ]
    return WeatherPreview(
        total_rows=len(frame),
        synthetic_chronology=synthetic,
        start=start,
        location=dataset.location,
        calendar=dataset.calendar,
        source_years=sorted(set(dataset.source_years)),
        units={v: dataset.units.get(v, UNITS[v]) for v in variables},
        rows=rows,
        monthly=monthly,
        warnings=[
            "UTC interval ends; summaries use fixed local standard-time interval starts",
            WARNINGS[1],
        ],
    )


def visualize(dataset, variables=None):
    if len(dataset.data) > 8784:
        raise OpenEPWError("RESOURCE_LIMIT", "Visualization supports at most 8,784 hourly rows")
    variables = _variables(dataset, variables, maximum=4)
    frame, local, source, synthetic, monthly = _summary(dataset, variables)
    return WeatherVisualization(
        location=dataset.location,
        calendar=dataset.calendar,
        total_rows=len(frame),
        timestamps=[timestamp.isoformat() for timestamp in local],
        source_years=[int(value) if pd.notna(value) else None for value in source],
        units={name: dataset.units.get(name, UNITS[name]) for name in variables},
        series={
            name: [float(value) if pd.notna(value) else None for value in frame[name]]
            for name in variables
        },
        monthly=monthly,
        synthetic_chronology=synthetic,
        warnings=WARNINGS,
    )
