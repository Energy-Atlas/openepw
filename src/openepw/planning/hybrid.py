from copy import deepcopy

import numpy as np

from ..dataset import WeatherDataset
from ..models import Issue, OpenEPWError


def hourly(dataset):
    if dataset.interval_minutes == 60:
        return dataset
    if dataset.interval_minutes <= 0 or 60 % dataset.interval_minutes:
        raise OpenEPWError("INVALID_ALIGNMENT", "Hybrid intervals must divide one hour")
    result = deepcopy(dataset)
    grouped = dataset.data.resample("h", closed="right", label="right")
    counts = grouped.size()
    if (counts != 60 // dataset.interval_minutes).any():
        raise OpenEPWError(
            "INVALID_ALIGNMENT", "Incomplete subhourly intervals cannot be silently aggregated"
        )
    result.data = grouped.mean(numeric_only=True)
    counts_per_variable = grouped.count()
    for name in ("ghi", "dni", "dhi"):
        if name in dataset.data:
            result.data[name] = grouped[name].sum(min_count=60 // dataset.interval_minutes)
    if "wind_direction" in dataset.data:
        radians = np.deg2rad(dataset.data.wind_direction)
        result.data["wind_direction"] = (
            np.rad2deg(
                np.arctan2(
                    np.sin(radians).resample("h", closed="right", label="right").mean(),
                    np.cos(radians).resample("h", closed="right", label="right").mean(),
                )
            )
            + 360
        ) % 360
    result.interval_minutes = 60
    for variable in result.data:
        result.data.loc[
            counts_per_variable[variable] != 60 // dataset.interval_minutes, variable
        ] = np.nan
    for lineage in result.lineage.values():
        lineage.transforms.append(
            "hourly mean states; sum interval solar energy; circular wind direction"
        )
    return result


def combine(datasets: dict[str, WeatherDataset], assignments: dict[str, str]) -> WeatherDataset:
    if not assignments:
        raise OpenEPWError("INVALID_ALIGNMENT", "Explicit hybrid requires variable assignments")
    datasets = {k: hourly(v) for k, v in datasets.items()}
    anchor = datasets[next(iter(assignments.values()))]
    result = deepcopy(anchor)
    result.data = result.data.iloc[:, 0:0].copy()
    result.lineage = {}
    result.headers = []
    result.source_years = []
    for variable, provider in assignments.items():
        if provider not in datasets or variable not in datasets[provider].data:
            raise OpenEPWError(
                "MISSING_CRITICAL_VARIABLE", "Assigned hybrid variable is unavailable"
            )
        data = datasets[provider]
        if data.calendar != anchor.calendar or not data.data.index.equals(anchor.data.index):
            raise OpenEPWError(
                "INVALID_ALIGNMENT",
                "Hybrid sources must cover exactly matching UTC intervals and calendars",
            )
        if data.units.get(variable) != anchor.units.get(variable):
            raise OpenEPWError("INVALID_ALIGNMENT", "Hybrid source units disagree")
        result.data[variable] = data.data[variable]
        if variable in data.lineage:
            lineage = deepcopy(data.lineage[variable])
            lineage.transforms.append("explicit hybrid variable assignment")
            result.lineage[variable] = lineage
    result.metadata = {
        "hybrid_assignments": assignments,
        "source_locations": {k: v.location.model_dump() for k, v in datasets.items()},
    }
    result.issues.append(
        Issue(
            code="HYBRID_SOURCE_MISMATCH",
            message="Hybrid sources may differ in elevation, resolution and measurement semantics; compare source locations",
        )
    )
    return result
