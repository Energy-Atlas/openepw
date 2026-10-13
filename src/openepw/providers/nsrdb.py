import csv
import hashlib
import io
import re
from typing import Any

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


# The NSRDB API datasets the adapter downloads. Each one's hourly CSV labels the centre of its
# interval at :30: documented for GOES aggregated v4, and checked for the others on 2026-10-13
# (a year of GHI centres on solar noon only with centre labels). Himawari-8 ("himawari",
# 2016-2020) labels hours at :00, so its intervals cannot become EPW's hour-ending rows
# without a temporal transform; it stays unsupported.
ACTUAL_DATASETS = ("nsrdb-GOES-aggregated-v4-0-0", "himawari7", "nsrdb-msg-v1-0-0", "msg-iodc")
PUBLISHED_DATASETS = ("nsrdb-GOES-tmy-v4-0-0", "himawari-tmy", "nsrdb-msg-v1-0-0-tmy",
                      "nsrdb-msg-v1-0-0-tdy", "nsrdb-msg-v1-0-0-tgy")
DATASETS = ACTUAL_DATASETS + PUBLISHED_DATASETS


def parse_nsrdb(raw, *, synthetic=False):
    try:
        lines = raw.decode("utf-8-sig").splitlines()
        meta: dict[str, Any] = dict(zip(next(csv.reader([lines[0]])), next(csv.reader([lines[1]]))))
        table = pd.read_csv(io.StringIO("\n".join(lines[2:])))
        if table.empty:
            raise ValueError("empty")
        meta["source_years"] = table.Year.astype(int).tolist() if synthetic else []
        dates = table[["Year", "Month", "Day", "Hour", "Minute"]].copy()
        if synthetic:
            dates["Year"] = 2001
        stamps = pd.DatetimeIndex(
            pd.to_datetime(
                dates.rename(columns=str.lower),
                utc=True,
            )
        )
        # The 60-minute CSV of each adapted dataset labels the centre of its interval, at :30.
        if not (stamps.minute == 30).all():
            raise ValueError("unsupported timestamp convention")
        frame = table[list(NAMES)].rename(columns=NAMES).astype(float)
        offset = round(float(meta.get("Time Zone", 0)) * 60)
        frame.index = stamps + pd.Timedelta(minutes=30 - offset)
        frame["pressure"] *= 100
        loc = Location(
            lat=float(meta["Latitude"]),
            lon=float(meta["Longitude"]),
            elevation=float(meta.get("Elevation", 0)),
            standard_offset_minutes=offset,
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
            max_retries=0,
            params={
                "api_key": key.get_secret_value() if key else "DEMO_KEY",
                "wkt": f"POINT({location.lon} {location.lat})",
            },
        )
        candidates = []
        for row in data.get("outputs", []):
            name = row["name"]
            published = request.product in ("tmy", "published")
            if request.dataset and request.dataset != name:
                continue
            # Without a named dataset the GOES products stay the default, as before.
            if not request.dataset and name != ("nsrdb-GOES-tmy-v4-0-0" if published
                                                else "nsrdb-GOES-aggregated-v4-0-0"):
                continue
            if name not in (PUBLISHED_DATASETS if published else ACTUAL_DATASETS):
                continue
            years = [int(y) for y in row.get("availableYears", []) if str(y).isdigit()]
            product_id = None
            if published:
                available = [str(y) for y in row.get("availableYears", [])]
                dated = [y for y in available if re.fullmatch(r"(?:tmy|tdy|tgy)-[0-9]{4}", y)]
                choices = [y for y in dated if y.startswith("tmy-")] or dated
                product_id = request.product_id or (max(choices) if choices else None)
                if product_id not in available:
                    continue
            elif not set(request.years or [request.start.year]) <= set(years):
                continue
            candidates.append(
                Candidate(
                    id=f"nsrdb:{name}:{product_id or 'actual'}:{location.key}",
                    product_id=product_id,
                    location_id=location.key,
                    source=SourceRef(
                        provider=self.name,
                        dataset=name,
                        resolution_km=4,
                        license="NLR NSRDB data terms; attribute NSRDB",
                        citation="https://nsrdb.nlr.gov",
                    ),
                    weather_types=["tmy", "published"] if published else ["historical", "amy"],
                    variables=list(VARIABLES.values()),
                    available_years=years,
                    interval_minutes=60,
                    requires_credentials=["OPENEPW_NLR_API_KEY", "OPENEPW_NLR_EMAIL"],
                    warnings=[
                        "Satellite/model data; hourly values labelled at their interval centre",
                        "UTC calendar-year files require neighboring year for nonzero standard-time offsets",
                    ],
                )
            )
        return candidates

    def fetch(self, task, http):
        if not http.config.nlr_api_key or not http.config.nlr_email:
            raise OpenEPWError("AUTH_REQUIRED", "NSRDB requires runtime API key and email")
        if task.source.dataset not in DATASETS:
            raise OpenEPWError("PLAN_STALE", "Unsupported NSRDB product")
        loc = Location.model_validate(task.parameters["location"])
        published = task.source.dataset in PUBLISHED_DATASETS
        start, end = interval_bounds(task.parameters) if not published else (None, None)
        if published and not re.fullmatch(
            r"(?:tmy|tdy|tgy)-[0-9]{4}", task.parameters.get("product_id") or ""
        ):
            raise OpenEPWError("INVALID_REQUEST", "Invalid published NSRDB product")
        frames = []
        raws = []
        # Annual endpoints only; retrieve edge year when it contains an interval needed locally.
        if published:
            names = [task.parameters["product_id"]]
        else:
            assert start is not None and end is not None
            names = list(range(start.year, (end - pd.Timedelta(seconds=1)).year + 1))
        for year in names:
            params = {
                "api_key": http.config.nlr_api_key.get_secret_value(),
                "email": http.config.nlr_email.get_secret_value(),
                "wkt": f"POINT({loc.lon} {loc.lat})",
                "names": str(year),
                "interval": 60,
                "utc": "false" if published else "true",
                "leap_day": "false" if published else "true",
                "mailing_list": "false",
                "attributes": "air_temperature,dew_point,relative_humidity,surface_pressure,ghi,dni,dhi,wind_speed,wind_direction",
            }
            raw = http.get(
                "https://developer.nlr.gov/api/nsrdb/v2/solar/"
                + task.source.dataset
                + "-download.csv",
                params=params,
            )
            frame, resolved, meta = parse_nsrdb(raw, synthetic=published)
            frames.append(frame)
            raws.append(raw)
        frame = pd.concat(frames)
        if not published:
            assert start is not None and end is not None
            frame = frame.loc[(frame.index > start) & (frame.index <= end)]
            if not frame.index.equals(pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")):
                raise OpenEPWError(
                    "UNAVAILABLE_PERIOD", "NSRDB does not cover all requested local intervals"
                )
            resolved.standard_offset_minutes = loc.standard_offset_minutes
        elif len(frame) != 8760 or not frame.index.is_unique:
            raise OpenEPWError(
                "MALFORMED_RESPONSE", "Published NSRDB product lacks 8760 unique intervals"
            )
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
                data=frame,
                location=resolved,
                lineage=lineage,
                metadata={"source_metadata": safe, "product_id": task.parameters.get("product_id")},
                calendar="synthetic" if published else "gregorian",
                source_years=meta["source_years"],
            ),
            source,
            raw,
        )
