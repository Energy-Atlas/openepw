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


def fill_group(primary: WeatherDataset, filler: WeatherDataset, variables: list[str], *,
               group: str, provider: str, dataset: str) -> WeatherDataset:
    """Replace whole variables of ``primary`` with ``filler``'s for the same UTC hours.

    The filling source covers the group the chosen source lacks (planning/gaps.py): every
    requested variable of the group comes from it, values unchanged (no adjustment toward the
    primary source). Lineage says which source filled what, and how far apart the two sources'
    locations are; the dataset gains an info issue VARIABLE_FILLED.
    """
    from .gaps import GROUP_LABELS, distance_km, source_label

    primary, filler = hourly(primary), hourly(filler)
    if filler.calendar != primary.calendar or not filler.data.index.equals(primary.data.index):
        raise OpenEPWError("INVALID_ALIGNMENT",
                           "A filling source must cover exactly the same UTC hours and calendar")
    if any(variable not in filler.data for variable in variables):
        raise OpenEPWError("MISSING_CRITICAL_VARIABLE", "The filling source lacks a variable it should fill")
    if any(filler.units.get(variable) != primary.units.get(variable) for variable in variables):
        raise OpenEPWError("INVALID_ALIGNMENT", "Filling source units disagree")
    result = deepcopy(primary)
    distance = distance_km(primary.location, filler.location)
    label = source_label(provider, dataset)
    apart = f", {distance:g} km from the chosen source's location" if distance is not None else ""
    for variable in variables:
        result.data[variable] = filler.data[variable].to_numpy()
        lineage = deepcopy(filler.lineage[variable]) if variable in filler.lineage else None
        if lineage is None:
            raise OpenEPWError("MISSING_CRITICAL_VARIABLE", "The filling source has no lineage for a variable")
        lineage.transforms.append(f"whole-variable fill for {group} from {label}{apart}")
        lineage.filled = True
        result.lineage[variable] = lineage
    result.metadata = {**result.metadata, "fills": [*result.metadata.get("fills", []), {
        "group": group, "variables": list(variables), "provider": provider, "dataset": dataset,
        "location": filler.location.model_dump(mode="json"), "distance_km": distance}]}
    result.issues.append(Issue(
        code="VARIABLE_FILLED", severity="info", field=group,
        message=f"{GROUP_LABELS.get(group, group)} filled from {label} (whole variables{apart})"))
    return result
