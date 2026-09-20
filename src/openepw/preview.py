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


def preview(dataset, start=0, limit=168, variables=None):
    if start < 0 or not 1 <= limit <= 168:
        raise OpenEPWError("INVALID_REQUEST", "Preview requires start >= 0 and limit 1..168")
    variables = variables or [v for v in UNITS if v in dataset.data]
    if not variables or any(v not in UNITS or v not in dataset.data for v in variables):
        raise OpenEPWError("INVALID_REQUEST", "Unknown preview variable")
    frame = dataset.data[variables].replace([np.inf, -np.inf], np.nan)
    local = local_interval_starts(dataset)
    source = pd.Series(
        dataset.source_years if len(dataset.source_years) == len(frame) else [None] * len(frame),
        index=frame.index,
    )
    synthetic = any(pd.notna(y) and int(y) != t.year for y, t in zip(source, local))
    rows = [
        PreviewRow(
            timestamp=t.isoformat(),
            source_year=int(source.loc[t]) if pd.notna(source.loc[t]) else None,
            values={k: float(v) if pd.notna(v) else None for k, v in row.items()},
        )
        for t, row in frame.iloc[start : start + limit].iterrows()
    ]
    local = local_interval_starts(dataset)
    monthly = []
    for (year, month), group in frame.groupby([local.year, local.month]):
        days = 28 if dataset.calendar == "noleap" and month == 2 else cal.monthrange(year, month)[1]
        values = {}
        for name in variables:
            if name == "wind_direction":
                continue
            finite = group[name].dropna()
            kwargs: dict[str, Any] = {"valid": len(finite)}
            if len(finite):
                if name in ("ghi", "dni", "dhi"):
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
                year=int(year), month=int(month), expected=days * 24, values=values,
                source_years=sorted({int(y) for y in source.loc[group.index].dropna()}),
            )
        )
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
            "Partial monthly sums/means use valid samples only; inspect valid versus expected counts",
        ],
    )
