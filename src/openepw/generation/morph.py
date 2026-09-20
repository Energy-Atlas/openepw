"""Independent Belcher/Jentsch monthly shift/stretch equations; no reused code."""

from copy import deepcopy

import numpy as np
import pandas as pd
from pydantic import Field, model_validator

from ..dataset import local_interval_starts
from ..models import Issue, Model, OpenEPWError, SourceRef, VariableLineage, digest


class MonthlySignal(Model):
    model: str
    member: str
    scenario: str
    reference_period: tuple[int, int]
    climate_period: tuple[int, int]
    license: str
    source_uri: str
    source_checksums: list[str]
    calendar: str = "gregorian"
    source_location: dict[str, float] = Field(default_factory=dict)
    temperature_delta: list[float]
    dtr_delta: list[float] = Field(default_factory=lambda: [0.0] * 12)
    humidity_delta: list[float] = Field(default_factory=lambda: [0.0] * 12)
    pressure_delta: list[float] = Field(default_factory=lambda: [0.0] * 12)
    wind_ratio: list[float] = Field(default_factory=lambda: [1.0] * 12)
    solar_ratio: list[float] = Field(default_factory=lambda: [1.0] * 12)
    units: dict[str, str] = Field(
        default_factory=lambda: {
            "temperature_delta": "K",
            "dtr_delta": "K",
            "humidity_delta": "percentage_point",
            "pressure_delta": "Pa",
            "wind_ratio": "1",
            "solar_ratio": "1",
        }
    )
    warnings: list[str] = Field(default_factory=list)
    profile_year: int | None = None

    @model_validator(mode="after")
    def valid(self):
        expected = {
            "temperature_delta": "K",
            "dtr_delta": "K",
            "humidity_delta": "percentage_point",
            "pressure_delta": "Pa",
            "wind_ratio": "1",
            "solar_ratio": "1",
        }
        if self.units != expected:
            raise ValueError("Signal units must match documented contract")
        for name in expected:
            values = getattr(self, name)
            if len(values) != 12 or not all(np.isfinite(v) for v in values):
                raise ValueError("Signal arrays require twelve finite monthly values")
            if name.endswith("ratio") and min(values) < 0:
                raise ValueError("Negative climate ratios are invalid")
        if not self.source_checksums or not self.license or not self.source_uri:
            raise ValueError("Signals require source provenance")
        return self


def morph(baseline, signal: MonthlySignal):
    from ..qc import validate

    if any(i.severity == "error" for i in validate(baseline, "annual")):
        raise OpenEPWError(
            "INVALID_BASELINE", "Morphing requires a complete annual hourly baseline"
        )
    required = [
        "dry_bulb",
        "dew_point",
        "relative_humidity",
        "pressure",
        "wind_speed",
        "ghi",
        "dni",
        "dhi",
    ]
    if any(v not in baseline.data or baseline.data[v].isna().any() for v in required):
        raise OpenEPWError(
            "MISSING_CRITICAL_VARIABLE",
            "Morphing requires complete temperature, humidity, pressure, wind and solar",
        )
    result = deepcopy(baseline)
    frame = result.data
    local = local_interval_starts(baseline)
    months: np.ndarray = local.month.to_numpy() - 1
    t = baseline.data.dry_bulb.to_numpy()
    delta = np.asarray(signal.temperature_delta)[months]
    alpha = np.zeros(12)
    by_day = pd.Series(t, index=local).resample("D")
    dtr = by_day.max() - by_day.min()
    for month in range(1, 13):
        value = float(dtr[pd.DatetimeIndex(dtr.index).month == month].mean())
        if value <= 1e-10:
            if signal.dtr_delta[month - 1] != 0:
                result.issues.append(
                    Issue(
                        code="ZERO_BASELINE_DTR",
                        message=f"Month {month}: zero baseline daily range; temperature shift only",
                    )
                )
        else:
            alpha[month - 1] = signal.dtr_delta[month - 1] / value
    if (1 + alpha < 0).any():
        raise OpenEPWError(
            "INVALID_CLIMATE_SIGNAL", "Signal would reverse the diurnal temperature range"
        )
    means = np.array([t[months == m].mean() for m in range(12)])
    frame["dry_bulb"] = t + delta + alpha[months] * (t - means[months])
    humidity = (
        baseline.data.relative_humidity.to_numpy() + np.asarray(signal.humidity_delta)[months]
    )
    if ((humidity < 0) | (humidity > 100)).any():
        result.issues.append(
            Issue(
                code="HUMIDITY_CLIPPED",
                message="Future RH clipped to 0..100; clipping is not silent",
            )
        )
    frame["relative_humidity"] = np.clip(humidity, 0, 100)
    humidity_changed = not np.array_equal(
        frame.relative_humidity.to_numpy(), baseline.data.relative_humidity.to_numpy()
    )
    temp_changed = not np.array_equal(frame.dry_bulb.to_numpy(), t)
    if temp_changed or humidity_changed:
        gamma = np.log(
            np.maximum(frame.relative_humidity.to_numpy(), 0.001) / 100
        ) + 17.625 * frame.dry_bulb.to_numpy() / (243.04 + frame.dry_bulb.to_numpy())
        frame["dew_point"] = 243.04 * gamma / (17.625 - gamma)
    frame["pressure"] = baseline.data.pressure + np.asarray(signal.pressure_delta)[months]
    frame["wind_speed"] = baseline.data.wind_speed * np.asarray(signal.wind_ratio)[months]
    for name in ("ghi", "dni", "dhi"):
        frame[name] = baseline.data[name] * np.asarray(signal.solar_ratio)[months]
    changed = set(required)
    if (temp_changed or humidity_changed) and "horizontal_infrared" in frame:
        # EnergyPlus clear-sky emissivity with Walton opaque-sky correction when available.
        sky = frame.get("opaque_sky_cover", pd.Series(np.nan, index=frame.index))
        emissivity = (0.787 + 0.764 * np.log((frame.dew_point + 273.15) / 273.15)) * (
            1 + 0.0224 * sky - 0.0035 * sky**2 + 0.00028 * sky**3
        )
        frame["horizontal_infrared"] = emissivity * 5.670374419e-8 * (frame.dry_bulb + 273.15) ** 4
        changed.add("horizontal_infrared")
        result.issues.append(
            Issue(
                code="INFRARED_DERIVED",
                message="Longwave recomputed from dry/dew and opaque sky; missing opaque sky remains missing",
            )
        )
    source = SourceRef(
        provider="cmip6" if not signal.source_uri.startswith("synthetic:") else "user_signal",
        dataset=signal.model,
        identity=signal.member,
        provisional=False,
        license=signal.license,
        citation=signal.source_uri,
    )
    sha = digest(signal.model_dump(mode="json"))
    for variable in frame:
        if variable == "flags":
            continue
        if variable in changed:
            baseline_lineage = baseline.lineage.get(variable)
            result.lineage[variable] = VariableLineage(
                variable=variable,
                source=source,
                raw_sha256=sha,
                derived=True,
                dependencies=[variable]
                + ([baseline_lineage.raw_sha256] if baseline_lineage else []),
                transforms=["Belcher monthly shift/stretch; baseline sequence retained"]
                + (
                    ["Magnus dew point from morphed temperature/RH"]
                    if variable == "dew_point"
                    else []
                ),
            )
        elif variable in result.lineage:
            result.lineage[variable].unchanged = True
    result.headers = []
    result.metadata = {
        **baseline.metadata,
        "method": "morph",
        "method_version": "0.1",
        "signal": signal.model_dump(mode="json"),
        "baseline_lineage": {k: v.model_dump() for k, v in baseline.lineage.items()},
        "unchanged_variables": [v for v in frame if v not in changed and v != "flags"],
        "interpretation": "Climate-window sensitivity, not forecast or formally standardized TMY",
        "radiation": "Common monthly scale on GHI/DNI/DHI preserves baseline component proportions",
    }
    result.issues.extend(Issue(code="CLIMATE_LIMITATION", message=w) for w in signal.warnings)
    return result
