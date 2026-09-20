"""Select full coherent years; never splice variables or create historical TMYs."""

import numpy as np
import pandas as pd

from ..dataset import local_interval_starts
from ..models import OpenEPWError


def daily(dataset, statistic="mean"):
    series = pd.Series(dataset.data.dry_bulb.to_numpy(), index=local_interval_starts(dataset))
    return getattr(series.resample("D"), statistic)()


def select_profile(years, baseline, profile, extreme):
    keys = sorted(years)
    if not keys:
        raise OpenEPWError("UNAVAILABLE_PERIOD", "No hourly trajectories available")
    if profile == "ensemble":
        return keys
    if profile == "typical":
        groups = []
        for variable in ("dry_bulb", "relative_humidity", "wind_speed", "ghi"):
            features = []
            for year in keys:
                data = years[year]
                if variable not in data.data or data.data[variable].isna().any():
                    raise OpenEPWError(
                        "MISSING_CRITICAL_VARIABLE",
                        "Profile selection requires complete T/RH/wind/GHI",
                    )
                grouped = data.data[variable].groupby(local_interval_starts(data).month)
                values = grouped.sum() if variable == "ghi" else grouped.mean()
                if len(values) != 12:
                    raise OpenEPWError(
                        "UNAVAILABLE_PERIOD", "Profile selection requires every month"
                    )
                features.append(values.to_numpy())
            matrix = np.asarray(features)
            scale = matrix.std(axis=0)
            active = scale > 1e-12
            if active.any():
                normalized = (matrix[:, active] - matrix[:, active].mean(axis=0)) / scale[active]
                groups.append(
                    np.sqrt(((normalized[:, None, :] - normalized[None, :, :]) ** 2).mean(axis=2))
                )
        scores = np.mean(groups, axis=0).sum(axis=1) if groups else np.zeros(len(keys))
        return [keys[int(np.argmin(scores))]]
    if profile != "extreme":
        raise OpenEPWError("UNSUPPORTED_FUTURE_METHOD", "Unsupported hourly profile")
    kind = extreme.get("type", "hot")
    mode = extreme.get("mode", "shock")
    if kind not in ("hot", "cold") or mode not in ("shock", "persistence"):
        raise OpenEPWError(
            "UNSUPPORTED_FUTURE_METHOD", "Extreme requires hot/cold and shock/persistence"
        )
    scores = {}
    if mode == "shock":
        for year, data in years.items():
            values = daily(data, "max" if kind == "hot" else "min").rolling(3, min_periods=3).mean()
            scores[year] = float(values.max() if kind == "hot" else -values.min())
    else:
        if not baseline:
            raise OpenEPWError(
                "INVALID_BASELINE", "Persistence thresholds require paired archive baseline"
            )
        reference = pd.concat([daily(d) for d in baseline.values()])
        # Map month/day to a nonleap calendar, excluding Feb 29 explicitly for thresholds.
        reference = reference[~((reference.index.month == 2) & (reference.index.day == 29))]

        def ordinal(index):
            return pd.to_datetime(
                ["2001-" + d.strftime("%m-%d") for d in index]
            ).dayofyear.to_numpy()

        doy = ordinal(reference.index)
        q = 0.95 if kind == "hot" else 0.05
        thresholds = {
            day: float(
                np.quantile(
                    reference.to_numpy()[np.minimum(abs(doy - day), 365 - abs(doy - day)) <= 15], q
                )
            )
            for day in range(1, 366)
        }
        for year, data in years.items():
            values = daily(data)
            values = values[~((values.index.month == 2) & (values.index.day == 29))]
            targets = np.asarray([thresholds[x] for x in ordinal(values.index)])
            hits = values.to_numpy() > targets if kind == "hot" else values.to_numpy() < targets
            best = run = 0
            for hit in hits:
                run = run + 1 if hit else 0
                best = max(best, run)
            scores[year] = best
    return [min(keys, key=lambda year: (-scores[year], year))]
