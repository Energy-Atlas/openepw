"""Optional direct CDS access; bounded monthly jobs and explicit accumulated units."""

import hashlib
import io
import json
import time
import zipfile
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from ..dataset import WeatherDataset
from ..models import Candidate, Location, OpenEPWError, SourceRef, VariableLineage
from .base import ProviderResult
from .openmeteo import interval_bounds

ROOT = "https://cds.climate.copernicus.eu/api/retrieve/v1"


def decode_cds(raw, lat, lon):
    import xarray as xr

    bodies = [raw]
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if sum(m.file_size for m in members) > 100_000_000 or any(
                not m.filename.endswith(".nc") for m in members
            ):
                raise ValueError("Unsupported or oversized CDS archive")
            bodies = [archive.read(m) for m in members]
    points = []
    for body in bodies:
        with xr.open_dataset(io.BytesIO(body), engine="h5netcdf") as ds:
            points.append(ds.sel(latitude=lat, longitude=lon, method="nearest").load())
    return xr.merge(points, join="exact", compat="no_conflicts")


def normalize_era5(ds, land=False):
    time_name = "valid_time" if "valid_time" in ds.coords else "time"
    times = pd.DatetimeIndex(pd.to_datetime(ds[time_name].values, utc=True))
    frame = pd.DataFrame(index=times)
    for original, name, offset in [
        ("t2m", "dry_bulb", -273.15),
        ("d2m", "dew_point", -273.15),
        ("sp", "pressure", 0),
    ]:
        frame[name] = np.asarray(ds[original].values).reshape(-1) + offset
    u = np.asarray(ds.u10.values).reshape(-1)
    v = np.asarray(ds.v10.values).reshape(-1)
    frame["wind_speed"] = np.hypot(u, v)
    frame["wind_direction"] = (np.degrees(np.arctan2(-u, -v)) + 360) % 360
    frame["relative_humidity"] = 100 * np.exp(
        17.625 * frame.dew_point / (243.04 + frame.dew_point)
        - 17.625 * frame.dry_bulb / (243.04 + frame.dry_bulb)
    )
    energy = pd.Series(np.asarray(ds.ssrd.values).reshape(-1), index=times)
    if land:
        diff = energy.diff()
        diff.loc[times.hour == 1] = energy.loc[times.hour == 1]
        energy = diff
    frame["ghi"] = energy / 3600
    return frame


def result_href(value):
    if isinstance(value, dict):
        if isinstance(value.get("href"), str):
            yield value["href"]
        for v in value.values():
            yield from result_href(v)
    elif isinstance(value, list):
        for v in value:
            yield from result_href(v)


class CDSProvider:
    name = "cds"

    def discover(self, request, location, http):
        if request.product not in ("historical", "amy"):
            return []
        dataset = request.dataset or "reanalysis-era5-single-levels"
        if dataset not in ("reanalysis-era5-single-levels", "reanalysis-era5-land"):
            return []
        variables = [
            "dry_bulb",
            "dew_point",
            "relative_humidity",
            "pressure",
            "wind_speed",
            "wind_direction",
            "ghi",
        ]
        return [
            Candidate(
                id=f"cds:{dataset}:{location.key}",
                location_id=location.key,
                source=SourceRef(
                    provider=self.name,
                    dataset=dataset,
                    license="Copernicus license; accepted dataset terms required",
                    citation="https://cds.climate.copernicus.eu",
                ),
                weather_types=["historical", "amy"],
                variables=variables,
                missing_fields=[v for v in request.required_variables if v not in variables],
                interval_minutes=60,
                requires_credentials=["OPENEPW_CDS_KEY"],
                warnings=[
                    "Optional climate/CDS dependencies required; queued requests may take minutes",
                    "Direct adapter provides GHI only; no invented DNI/DHI",
                    "Monthly requests bounded to 10-minute polling each; rerun later if queued",
                ],
            )
        ]

    def fetch(self, task, http):
        try:
            import xarray  # noqa: F401 -- check optional backend before issuing a CDS job
        except ImportError:
            raise OpenEPWError(
                "OPTIONAL_DEPENDENCY", "Install openepw[cds] for direct CDS"
            ) from None
        if not http.config.cds_key:
            raise OpenEPWError(
                "AUTH_REQUIRED", "CDS requires runtime token and accepted dataset terms"
            )
        loc = Location.model_validate(task.parameters["location"])
        start, end = interval_bounds(task.parameters)
        dates = pd.date_range((start - pd.Timedelta(days=1)).normalize(), end.normalize(), freq="D")
        frames = []
        raws = []
        for period in sorted(set((d.year, d.month) for d in dates)):
            days = [f"{d.day:02}" for d in dates if (d.year, d.month) == period]
            inputs = {
                "variable": [
                    "2m_temperature",
                    "2m_dewpoint_temperature",
                    "surface_pressure",
                    "10m_u_component_of_wind",
                    "10m_v_component_of_wind",
                    "surface_solar_radiation_downwards",
                ],
                "year": [str(period[0])],
                "month": [f"{period[1]:02}"],
                "day": days,
                "time": [f"{h:02}:00" for h in range(24)],
                "area": [
                    min(90, loc.lat + 0.15),
                    max(-180, loc.lon - 0.15),
                    max(-90, loc.lat - 0.15),
                    min(180, loc.lon + 0.15),
                ],
                "data_format": "netcdf",
                "download_format": "unarchived",
            }
            land = task.source.dataset.endswith("land")
            if not land:
                inputs["product_type"] = ["reanalysis"]
            header = {"PRIVATE-TOKEN": http.config.cds_key.get_secret_value()}
            response = http.request(
                "POST",
                ROOT + "/processes/" + task.source.dataset + "/execution",
                headers=header,
                json_body={"inputs": inputs},
            )[0]
            record = json.loads(response)
            jobid = record.get("jobID") or record.get("job_id")
            if not jobid or not all(c in "0123456789abcdef-" for c in jobid):
                raise OpenEPWError(
                    "MALFORMED_RESPONSE", "CDS did not return a valid job identifier"
                )
            for _ in range(60):
                status = http.get_json(ROOT + "/jobs/" + jobid, headers=header)
                if status.get("status") == "successful":
                    break
                if status.get("status") in ("failed", "dismissed"):
                    raise OpenEPWError(
                        "PROVIDER_UNAVAILABLE", "CDS retrieval failed or was dismissed"
                    )
                time.sleep(10)
            else:
                raise OpenEPWError(
                    "PROVIDER_UNAVAILABLE",
                    "CDS request still queued after polling limit",
                    retryable=True,
                )
            results = http.get_json(ROOT + "/jobs/" + jobid + "/results", headers=header)
            hrefs = [
                u
                for u in result_href(results)
                if urlparse(u).hostname == "object-store.os-api.cci2.ecmwf.int"
                and urlparse(u).scheme == "https"
            ]
            if not hrefs:
                raise OpenEPWError(
                    "MALFORMED_RESPONSE", "CDS result lacks approved object-store download"
                )
            for href in hrefs:
                raw = http.get(href)
                raws.append(raw)
                try:
                    point = decode_cds(raw, loc.lat, loc.lon)
                    resolved = Location(
                        lat=float(point.latitude),
                        lon=float(point.longitude),
                        standard_offset_minutes=loc.standard_offset_minutes,
                    )
                    frames.append(normalize_era5(point, land=land))
                except (ValueError, KeyError, OSError):
                    raise OpenEPWError(
                        "MALFORMED_RESPONSE", "CDS NetCDF variables or dimensions are unsupported"
                    ) from None
        frame = pd.concat(frames).sort_index()
        frame = frame.loc[(frame.index > start) & (frame.index <= end)]
        if not frame.index.equals(pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")):
            raise OpenEPWError("UNAVAILABLE_PERIOD", "CDS intervals do not cover requested period")
        source = task.source.model_copy(update={"location": resolved, "provisional": False})
        raw = b"".join(raws)
        sha = hashlib.sha256(raw).hexdigest()
        lineage = {
            v: VariableLineage(
                variable=v,
                source=source,
                raw_sha256=sha,
                transforms=[
                    "ERA5-Land accumulation differenced with 01 UTC reset"
                    if land
                    else "ERA5 hourly accumulation",
                    "K to Celsius; J/m2 to Wh/m2; vector wind; Magnus RH",
                ],
                derived=v in ("relative_humidity", "wind_direction", "wind_speed"),
            )
            for v in frame
        }
        return ProviderResult(
            WeatherDataset(
                data=frame,
                location=resolved,
                lineage=lineage,
                metadata={
                    "missing_solar": "DNI and DHI not derived",
                    "dataset": task.source.dataset,
                },
            ),
            source,
            raw,
        )
