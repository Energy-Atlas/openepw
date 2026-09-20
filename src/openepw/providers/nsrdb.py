import csv
import hashlib
import io
import re

import pandas as pd

from ..dataset import WeatherDataset
from ..models import Candidate, Location, OpenEPWError, SourceRef, VariableLineage
from .base import ProviderResult
from .openmeteo import VARIABLES, interval_bounds

NAMES = {
    "Temperature": "dry_bulb",
    "Dew Point": "dew_point",
    "Relative Humidity": "relative_humidity",
    "Pressure": "pressure",
    "GHI": "ghi",
    "DNI": "dni",
    "DHI": "dhi",
    "Wind Speed": "wind_speed",
    "Wind Direction": "wind_direction",
}


def parse_nsrdb(raw):
    try:
        lines = raw.decode("utf-8-sig").splitlines()
        meta = dict(zip(next(csv.reader([lines[0]])), next(csv.reader([lines[1]]))))
        table = pd.read_csv(io.StringIO("\n".join(lines[2:])))
        if table.empty:
            raise ValueError("empty")
        stamps = pd.DatetimeIndex(
            pd.to_datetime(
                table[["Year", "Month", "Day", "Hour", "Minute"]].rename(columns=str.lower),
                utc=True,
            )
        )
        # Aggregated v4 60-minute CSV labels center of interval, observed at :30.
        if not (stamps.minute == 30).all():
            raise ValueError("unsupported timestamp convention")
        frame = table[list(NAMES)].rename(columns=NAMES).astype(float)
        frame.index = stamps + pd.Timedelta(minutes=30)
        frame["pressure"] *= 100
        loc = Location(
            lat=float(meta["Latitude"]),
            lon=float(meta["Longitude"]),
            elevation=float(meta.get("Elevation", 0)),
            standard_offset_minutes=0,
        )
        return frame, loc, meta
    except (ValueError, KeyError, IndexError, TypeError):
        raise OpenEPWError(
            "MALFORMED_RESPONSE", "NSRDB response lacks supported hourly CSV metadata/fields"
        ) from None


class NSRDBProvider:
    name = "nsrdb"

    def discover(self, request, location, http):
        if request.product not in ("historical", "amy", "tmy", "published"):
            return []
        key = http.config.nlr_api_key
        data = http.get_json(
            "https://developer.nlr.gov/api/solar/nsrdb_data_query.json",
            params={
                "api_key": key.get_secret_value() if key else "DEMO_KEY",
                "wkt": f"POINT({location.lon} {location.lat})",
            },
        )
        candidates = []
        for row in data.get("outputs", []):
            name = row["name"]
            # Current v0.1 supports observed interval-center convention for aggregate v4 only.
            if name != "nsrdb-GOES-aggregated-v4-0-0" or request.product not in (
                "historical",
                "amy",
            ):
                continue
            years = [int(y) for y in row.get("availableYears", []) if str(y).isdigit()]
            requested = request.years or [request.start.year]
            if not set(requested) <= set(years):
                continue
            candidates.append(
                Candidate(
                    id=f"nsrdb:{name}:{location.key}",
                    location_id=location.key,
                    source=SourceRef(
                        provider=self.name,
                        dataset=name,
                        resolution_km=4,
                        license="NLR NSRDB data terms; attribute NSRDB",
                        citation="https://nsrdb.nlr.gov",
                    ),
                    weather_types=["historical", "amy"],
                    variables=list(VARIABLES.values()),
                    available_years=years,
                    interval_minutes=60,
                    requires_credentials=["OPENEPW_NLR_API_KEY", "OPENEPW_NLR_EMAIL"],
                    warnings=[
                        "Satellite/model data; aggregate v4 hourly interval-center convention",
                        "UTC calendar-year files require neighboring year for nonzero standard-time offsets",
                    ],
                )
            )
        return candidates

    def fetch(self, task, http):
        if not http.config.nlr_api_key or not http.config.nlr_email:
            raise OpenEPWError("AUTH_REQUIRED", "NSRDB requires runtime API key and email")
        if not re.fullmatch("nsrdb-GOES-aggregated-v4-0-0", task.source.dataset):
            raise OpenEPWError("PLAN_STALE", "Unsupported NSRDB product")
        loc = Location.model_validate(task.parameters["location"])
        start, end = interval_bounds(task.parameters)
        frames = []
        raws = []
        # Annual endpoints only; retrieve edge year when it contains an interval needed locally.
        for year in range(start.year, (end - pd.Timedelta(seconds=1)).year + 1):
            params = {
                "api_key": http.config.nlr_api_key.get_secret_value(),
                "email": http.config.nlr_email.get_secret_value(),
                "wkt": f"POINT({loc.lon} {loc.lat})",
                "names": str(year),
                "interval": 60,
                "utc": "true",
                "leap_day": "true",
                "mailing_list": "false",
                "attributes": "air_temperature,dew_point,relative_humidity,surface_pressure,ghi,dni,dhi,wind_speed,wind_direction",
            }
            raw = http.get(
                "https://developer.nlr.gov/api/nsrdb/v2/solar/"
                + task.source.dataset
                + "-download.csv",
                params=params,
            )
            frame, resolved, meta = parse_nsrdb(raw)
            frames.append(frame)
            raws.append(raw)
        frame = pd.concat(frames)
        frame = frame.loc[(frame.index > start) & (frame.index <= end)]
        if not frame.index.equals(pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")):
            raise OpenEPWError(
                "UNAVAILABLE_PERIOD", "NSRDB does not cover all requested local intervals"
            )
        resolved.standard_offset_minutes = loc.standard_offset_minutes
        source = task.source.model_copy(
            update={
                "location": resolved,
                "identity": str(meta.get("Location ID")),
                "provisional": False,
            }
        )
        raw = b"\n".join(raws)
        sha = hashlib.sha256(raw).hexdigest()
        lineage = {
            v: VariableLineage(
                variable=v,
                source=source,
                raw_sha256=sha,
                transforms=["hourly interval-center labels shifted +30 min to interval ends"]
                + (
                    ["hPa to Pa"]
                    if v == "pressure"
                    else ["hourly mean W/m2 to Wh/m2"]
                    if v in ("ghi", "dni", "dhi")
                    else []
                ),
            )
            for v in frame
        }
        # Whitelist source metadata: never serialize an echoed key/email from a provider.
        safe = {
            k: meta[k]
            for k in ("Source", "Location ID", "Latitude", "Longitude", "Elevation", "Time Zone")
            if k in meta
        }
        return ProviderResult(
            WeatherDataset(
                data=frame, location=resolved, lineage=lineage, metadata={"source_metadata": safe}
            ),
            source,
            raw,
        )
