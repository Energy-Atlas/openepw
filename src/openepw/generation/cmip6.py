"""Pangeo CMIP6 catalog selection and calendar-aware monthly point signals."""

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..artifacts.store import atomic_write
from ..models import OpenEPWError, digest
from .morph import MonthlySignal

VARIABLES = ("tas", "tasmin", "tasmax", "hurs", "ps", "sfcWind", "rsds")
CATALOG = "https://storage.googleapis.com/cmip6/pangeo-cmip6.csv"


def monthly_means(point, period):
    selected = point.sel(time=slice(str(period[0]), str(period[1])))
    years = selected.time.dt.year.values
    months = selected.time.dt.month.values
    wanted = {(year, month) for year in range(period[0], period[1] + 1) for month in range(1, 13)}
    pairs = list(zip(years.tolist(), months.tolist()))
    if set(pairs) != wanted or len(pairs) != len(wanted) or not np.isfinite(selected.values).all():
        raise OpenEPWError(
            "UNAVAILABLE_PERIOD",
            "Climate source lacks complete finite monthly values for the requested window",
        )
    # Weight each monthly mean by days in its native calendar; no Gregorian coercion.
    days = selected.time.dt.days_in_month.values
    return np.asarray(
        [np.average(selected.values[months == m], weights=days[months == m]) for m in range(1, 13)]
    )


def make_signal(reference, future, metadata):
    ratios = {}
    for variable in ("sfcWind", "rsds"):
        before = reference[variable]
        after = future[variable]
        if ((before <= 1e-9) & (np.abs(after - before) > 1e-9)).any():
            raise OpenEPWError(
                "INVALID_CLIMATE_SIGNAL",
                "Nonzero future wind/solar with zero reference cannot be stretched",
            )
        ratios[variable] = np.divide(after, before, out=np.ones(12), where=before > 1e-9).tolist()
    return MonthlySignal(
        **metadata,
        temperature_delta=(future["tas"] - reference["tas"]).tolist(),
        dtr_delta=(
            (future["tasmax"] - future["tasmin"]) - (reference["tasmax"] - reference["tasmin"])
        ).tolist(),
        humidity_delta=(future["hurs"] - reference["hurs"]).tolist(),
        pressure_delta=(future["ps"] - reference["ps"]).tolist(),
        wind_ratio=ratios["sfcWind"],
        solar_ratio=ratios["rsds"],
    )


class CMIP6Backend:
    def __init__(self, http):
        self.http = http
        self.root = Path(http.config.data_root) / "cache" / "cmip6"

    def select(self, request):
        if not request.climate_scenario.startswith("ssp"):
            raise OpenEPWError("INVALID_SCENARIO_PERIOD", "CMIP6 morphing requires an SSP scenario")
        path = self.root / "catalog.csv"
        if not path.exists():
            atomic_write(path, self.http.get(CATALOG, limit=100_000_000))
        models = request.models or ["ACCESS-CM2"]
        members = request.members or ["r1i1p1f1"]
        groups: dict[tuple[str, str, str], dict] = {}
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                if (
                    row["source_id"] in models
                    and row["member_id"] in members
                    and row["table_id"] == "Amon"
                    and row["variable_id"] in VARIABLES
                    and row["experiment_id"] in ("historical", request.climate_scenario)
                ):
                    key = (row["source_id"], row["member_id"], row["grid_label"])
                    group = groups.setdefault(key, {})
                    item = (row["experiment_id"], row["variable_id"])
                    # Stable lexicographic version choice, recorded as immutable URLs in the plan.
                    if item not in group or row["zstore"] > group[item]["zstore"]:
                        group[item] = row
        complete = []
        seen = set()
        for key, group in sorted(groups.items()):
            if (
                all(
                    (e, v) in group
                    for e in ("historical", request.climate_scenario)
                    for v in VARIABLES
                )
                and key[:2] not in seen
            ):
                complete.append(
                    {
                        "model": key[0],
                        "member": key[1],
                        "grid": key[2],
                        "rows": list(group.values()),
                        "catalog_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
                seen.add(key[:2])
        if not complete or any(not any(p["model"] == m for p in complete) for m in models):
            raise OpenEPWError(
                "UNAVAILABLE_PERIOD",
                "No complete coherent CMIP6 variable/member intersection for selectors",
            )
        return complete if request.profile in ("ensemble", "extreme") else complete[:1]

    def estimate(self, pairs, request):
        total = 0
        for pair in pairs:
            for row in pair["rows"]:
                url = row["zstore"].replace("gs://", "https://storage.googleapis.com/").rstrip("/")
                path = self.root / (digest(url) + ".json")
                if not path.exists():
                    atomic_write(path, self.http.get(url + "/.zmetadata"))
                meta = json.loads(path.read_bytes())["metadata"]
                array = meta[row["variable_id"] + "/.zarray"]
                # Conservative upper bound: every time chunk touched by full source array.
                # Point queries often still decode full spatial chunks.
                chunk_bytes = math.prod(array["chunks"]) * np.dtype(array["dtype"]).itemsize
                total += chunk_bytes * math.ceil(array["shape"][0] / array["chunks"][0])
                row["metadata_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                row["original_license"] = meta.get(".zattrs", {}).get("license", "unknown")
        return total

    def signals(self, pairs, request, location):
        try:
            import xarray as xr
        except ImportError:
            raise OpenEPWError(
                "OPTIONAL_DEPENDENCY", "Install openepw[climate] for CMIP6"
            ) from None
        signals = []
        for pair in pairs:
            series: dict[str, list[Any]] = {}
            checksums = []
            calendar = None
            actual_location = None
            licenses = []
            for row in pair["rows"]:
                variable = row["variable_id"]
                url = row["zstore"].replace("gs://", "https://storage.googleapis.com/").rstrip("/")
                key = digest(
                    {
                        "url": url,
                        "lat": location.lat,
                        "lon": location.lon,
                        "reference": request.reference_period,
                        "target": request.climate_period,
                    }
                )
                path = self.root / (key + ".nc")
                if not path.exists():
                    try:
                        with xr.open_zarr(url, consolidated=True, chunks=None) as ds:
                            attrs = ds.attrs
                            if (
                                attrs.get("source_id") != pair["model"]
                                or attrs.get("variant_label", attrs.get("member_id"))
                                != pair["member"]
                            ):
                                raise OpenEPWError(
                                    "PLAN_STALE", "CMIP6 source model/member disagrees with catalog"
                                )
                            lo = min(request.reference_period[0], request.climate_period[0])
                            hi = max(request.reference_period[1], request.climate_period[1])
                            longitude = (
                                location.lon % 360 if float(ds.lon.max()) > 180 else location.lon
                            )
                            point = (
                                ds[variable]
                                .sel(lat=location.lat, lon=longitude, method="nearest")
                                .sel(time=slice(str(lo), str(hi)))
                                .load()
                            )
                            atomic_write(path, bytes(point.to_netcdf(engine="h5netcdf")))
                    except OpenEPWError:
                        raise
                    except Exception:
                        raise OpenEPWError(
                            "PROVIDER_UNAVAILABLE",
                            "CMIP6 numeric access or decoding failed",
                            retryable=True,
                        ) from None
                with xr.open_dataarray(path, engine="h5netcdf") as data:
                    point = data.load()
                expected = {
                    "tas": "K",
                    "tasmin": "K",
                    "tasmax": "K",
                    "hurs": "%",
                    "ps": "Pa",
                    "sfcWind": "m s-1",
                    "rsds": "W m-2",
                }
                if point.attrs.get("units") != expected[variable]:
                    raise OpenEPWError(
                        "INVALID_CLIMATE_SIGNAL", "CMIP6 variable units differ from expected units"
                    )
                this_calendar = str(point.time.dt.calendar)
                if calendar and calendar != this_calendar:
                    raise OpenEPWError(
                        "INVALID_CLIMATE_SIGNAL", "CMIP6 variables have different calendars"
                    )
                calendar = this_calendar
                here = {"lat": float(point.lat), "lon": float(point.lon)}
                if actual_location and actual_location != here:
                    raise OpenEPWError(
                        "INVALID_CLIMATE_SIGNAL", "CMIP6 variables resolve different cells"
                    )
                actual_location = here
                checksums.append(hashlib.sha256(path.read_bytes()).hexdigest())
                series.setdefault(variable, []).append(point)
                licenses.append(row.get("original_license", "unknown"))
            merged = {}
            for variable, parts in series.items():
                array = xr.concat(parts, dim="time").sortby("time")
                if len(set(array.time.values)) != array.time.size:
                    raise OpenEPWError(
                        "INVALID_CLIMATE_SIGNAL", "Overlapping historical/scenario months"
                    )
                merged[variable] = array
            reference = {v: monthly_means(s, request.reference_period) for v, s in merged.items()}
            if request.profile == "extreme":
                years = range(request.climate_period[0], request.climate_period[1] + 1)
                ranked = sorted(
                    years,
                    key=lambda y: (
                        float(
                            monthly_means(merged["tas"], (y, y)).mean() - reference["tas"].mean()
                        ),
                        y,
                    ),
                )
                quantile = float(request.extreme.get("quantile", 0.95))
                if not 0 < quantile <= 1:
                    raise OpenEPWError(
                        "INVALID_CLIMATE_SIGNAL", "Extreme quantile must lie in (0,1]"
                    )
                chosen = ranked[max(0, math.ceil(quantile * len(ranked)) - 1)]
                period = (chosen, chosen)
            else:
                chosen = None
                period = request.climate_period
            future = {v: monthly_means(s, period) for v, s in merged.items()}
            metadata = {
                "model": pair["model"],
                "member": pair["member"],
                "scenario": request.climate_scenario,
                "reference_period": request.reference_period,
                "climate_period": request.climate_period,
                "source_uri": CATALOG,
                "source_checksums": checksums,
                "calendar": calendar,
                "source_location": actual_location,
                "license": " | ".join(sorted(set(licenses))),
                "profile_year": chosen,
                "warnings": [
                    "Global-model nearest cell; baseline sequence and unresolved variables retained",
                    "Single-member climate sensitivity; not a weather forecast",
                ],
            }
            signals.append(make_signal(reference, future, metadata))
        return signals
