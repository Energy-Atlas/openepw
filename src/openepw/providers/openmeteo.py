import hashlib
import json

import pandas as pd

from ..dataset import WeatherDataset
from ..models import Candidate, Location, OpenEPWError, SourceRef, VariableLineage
from .base import ProviderResult

VARIABLES = {
    "temperature_2m": "dry_bulb",
    "dew_point_2m": "dew_point",
    "relative_humidity_2m": "relative_humidity",
    "surface_pressure": "pressure",
    "shortwave_radiation": "ghi",
    "direct_normal_irradiance": "dni",
    "diffuse_radiation": "dhi",
    "wind_speed_10m": "wind_speed",
    "wind_direction_10m": "wind_direction",
}


def interval_bounds(parameters):
    location = Location.model_validate(parameters["location"])
    start = pd.Timestamp(parameters["start"], tz="UTC") - pd.Timedelta(
        minutes=location.standard_offset_minutes
    )
    end = (
        pd.Timestamp(parameters["end"], tz="UTC")
        + pd.Timedelta(days=1)
        - pd.Timedelta(minutes=location.standard_offset_minutes)
    )
    return start, end


class OpenMeteoProvider:
    name = "openmeteo"

    def discover(self, request, location, http):
        if request.product not in ("historical", "amy"):
            return []
        dataset = request.dataset or "era5"
        if dataset not in ("era5", "era5_land"):
            return []
        variables = (
            list(VARIABLES.values())
            if dataset == "era5"
            else ["dry_bulb", "dew_point", "relative_humidity", "pressure"]
        )
        return [
            Candidate(
                id=f"openmeteo:{dataset}:{location.key}",
                location_id=location.key,
                source=SourceRef(
                    provider=self.name,
                    dataset=dataset,
                    resolution_km=25 if dataset == "era5" else 11,
                    license="CC BY 4.0",
                    citation="https://open-meteo.com/en/docs/historical-weather-api",
                ),
                weather_types=["historical", "amy"],
                variables=variables,
                interval_minutes=60,
                missing_fields=[v for v in request.required_variables if v not in variables],
                warnings=[
                    "Hosted free endpoint is noncommercial only",
                    "Source cell and elevation resolved at fetch; no inferred cell deduplication",
                ],
            )
        ]

    def fetch(self, task, http):
        p = task.parameters
        loc = Location.model_validate(p["location"])
        start, end = interval_bounds(p)
        key = http.config.openmeteo_api_key
        url = (
            "https://customer-archive-api.open-meteo.com/v1/archive"
            if key
            else "https://archive-api.open-meteo.com/v1/archive"
        )
        params = dict(
            latitude=loc.lat,
            longitude=loc.lon,
            start_date=(start - pd.Timedelta(days=1)).date().isoformat(),
            end_date=end.date().isoformat(),
            models=task.source.dataset,
            timezone="GMT",
            wind_speed_unit="ms",
            hourly=",".join(VARIABLES),
        )
        if loc.elevation is not None:
            params["elevation"] = loc.elevation
        if key:
            params["apikey"] = key.get_secret_value()
        raw = http.get(url, params=params)
        try:
            response = json.loads(raw)
            hourly = response["hourly"]
            if not hourly["time"]:
                raise ValueError("empty")
            times = pd.DatetimeIndex(pd.to_datetime(hourly["time"], utc=True))
            frame = pd.DataFrame(
                {v: hourly.get(k, [None] * len(times)) for k, v in VARIABLES.items()},
                index=times,
                dtype=float,
            )
            units = response["hourly_units"]
            expected = {
                "surface_pressure": "hPa",
                "wind_speed_10m": "m/s",
                "temperature_2m": "°C",
                "shortwave_radiation": "W/m²",
                "direct_normal_irradiance": "W/m²",
                "diffuse_radiation": "W/m²",
            }
            if any(units.get(k) != v for k, v in expected.items()):
                raise ValueError("unexpected units")
            frame["pressure"] *= 100
            frame = frame.loc[(frame.index > start) & (frame.index <= end)]
            wanted = pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
            if not frame.index.equals(wanted) or frame.dry_bulb.isna().all():
                raise ValueError("missing time coverage")
            resolved = Location(
                lat=response["latitude"],
                lon=response["longitude"],
                elevation=response.get("elevation"),
                standard_offset_minutes=loc.standard_offset_minutes,
                name=loc.name,
            )
        except (ValueError, KeyError, TypeError):
            raise OpenEPWError(
                "MALFORMED_RESPONSE", "Open-Meteo has empty, incomplete or unexpected weather/units"
            ) from None
        source = task.source.model_copy(update={"location": resolved, "provisional": False})
        checksum = hashlib.sha256(raw).hexdigest()
        lineage = {
            v: VariableLineage(
                variable=v,
                source=source,
                raw_sha256=checksum,
                transforms=["hPa to Pa"]
                if v == "pressure"
                else ["preceding-hour mean W/m2 to hourly Wh/m2"]
                if v in ("ghi", "dni", "dhi")
                else ["instantaneous state at interval end"],
                derived=v in ("dni", "dew_point", "relative_humidity"),
            )
            for v in frame
        }
        data = WeatherDataset(
            data=frame,
            location=resolved,
            lineage=lineage,
            metadata={
                "requested_location": loc.model_dump(),
                "interval_semantics": "Solar: preceding-hour mean; meteorology: instantaneous at interval end",
                "reference_period": [start.year, end.year],
            },
        )
        return ProviderResult(data, source, raw)
