import hashlib
import io
import json

import numpy as np
import pandas as pd

from ..dataset import WeatherDataset
from ..models import Candidate, Location, OpenEPWError, SourceRef, VariableLineage
from .base import ProviderResult
from .openmeteo import interval_bounds


def normalize_isd(rows, target):
    def field(text, scale=10):
        parts = str(text or "").split(",")
        if len(parts) < 2 or parts[1] not in ("0", "1", "4", "5") or abs(float(parts[0])) >= 9999:
            return np.nan
        return float(parts[0]) / scale

    values = []
    for row in rows:
        wind = str(row.get("WND", "")).split(",")
        values.append(
            {
                "time": pd.Timestamp(row["DATE"], tz="UTC"),
                "dry_bulb": field(row.get("TMP")),
                "dew_point": field(row.get("DEW")),
                "wind_direction": field(",".join(wind[:2]), 1)
                if len(wind) == 5 and wind[0] != "999"
                else np.nan,
                "wind_speed": field(",".join(wind[3:])) if len(wind) == 5 else np.nan,
            }
        )
    if not values:
        raise OpenEPWError("UNAVAILABLE_PERIOD", "NOAA returned no station reports")
    frame = pd.DataFrame(values).sort_values("time", kind="stable")
    frame = frame.drop_duplicates("time", keep="first").set_index("time")
    # A deterministic nearest report within 30 min. Missing intervals stay missing.
    frame = frame.reindex(target, method="nearest", tolerance=pd.Timedelta(minutes=30))
    frame["relative_humidity"] = 100 * np.exp(
        17.625 * frame.dew_point / (243.04 + frame.dew_point)
        - 17.625 * frame.dry_bulb / (243.04 + frame.dry_bulb)
    )
    return frame


class NOAAProvider:
    name = "noaa"

    def discover(self, request, location, http):
        if request.product not in ("historical", "amy"):
            return []
        raw = http.get("https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv")
        stations = pd.read_csv(io.BytesIO(raw), dtype={"USAF": str, "WBAN": str})
        stations = stations.dropna(subset=["LAT", "LON"])
        lat = np.deg2rad(stations.LAT.to_numpy())
        dlat = lat - np.deg2rad(location.lat)
        dlon = np.deg2rad(stations.LON.to_numpy() - location.lon)
        stations["distance"] = (
            6371
            * 2
            * np.arcsin(
                np.sqrt(
                    np.sin(dlat / 2) ** 2
                    + np.cos(lat) * np.cos(np.deg2rad(location.lat)) * np.sin(dlon / 2) ** 2
                )
            )
        )
        if request.product_id:
            stations = stations[(stations.USAF + stations.WBAN) == request.product_id]
        else:
            stations = stations[stations.distance <= 100]
        year = min(request.years) if request.years else request.start.year
        stations = stations[
            (stations.END >= year * 10000 + 101) & (stations.BEGIN <= (year + 1) * 10000)
        ]
        candidates = []
        for _, row in stations.sort_values("distance").head(5).iterrows():
            station = row.USAF + row.WBAN
            loc = Location(
                lat=row.LAT,
                lon=row.LON,
                elevation=None if pd.isna(row["ELEV(M)"]) else row["ELEV(M)"],
                name=row["STATION NAME"],
                standard_offset_minutes=location.standard_offset_minutes,
            )
            variables = [
                "dry_bulb",
                "dew_point",
                "relative_humidity",
                "wind_speed",
                "wind_direction",
            ]
            candidates.append(
                Candidate(
                    id=f"noaa:{station}:{location.key}",
                    location_id=location.key,
                    product_id=station,
                    source=SourceRef(
                        provider=self.name,
                        dataset="ISD global-hourly",
                        identity=station,
                        location=loc,
                        provisional=False,
                        license="US government public data",
                        citation="https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database",
                    ),
                    weather_types=["historical", "amy"],
                    variables=variables,
                    available_years=list(range(int(row.BEGIN) // 10000, int(row.END) // 10000 + 1)),
                    missing_fields=[v for v in request.required_variables if v not in variables],
                    warnings=[
                        "Station inventory coverage is not a guarantee of hourly completeness",
                        "Solar and station pressure unavailable; sea-level pressure never substituted",
                        "GHCNh successor is not this adapter",
                    ],
                )
            )
        return candidates

    def fetch(self, task, http):
        start, end = interval_bounds(task.parameters)
        params = {
            "dataset": "global-hourly",
            "stations": task.source.identity,
            "startDate": (start - pd.Timedelta(days=1)).date().isoformat(),
            "endDate": end.date().isoformat(),
            "format": "json",
            "dataTypes": "TMP,DEW,WND",
            "units": "metric",
        }
        rows = []
        for year in range((start - pd.Timedelta(days=1)).year, end.year + 1):
            lo = max(start - pd.Timedelta(days=1), pd.Timestamp(f"{year}-01-01", tz="UTC"))
            hi = min(end, pd.Timestamp(f"{year}-12-31", tz="UTC"))
            part = http.get_json(
                "https://www.ncei.noaa.gov/access/services/data/v1",
                params={
                    **params,
                    "startDate": lo.date().isoformat(),
                    "endDate": hi.date().isoformat(),
                },
            )
            rows.extend(part)
        raw = json.dumps(rows).encode()
        try:
            frame = normalize_isd(
                json.loads(raw), pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
            )
        except (ValueError, KeyError, TypeError):
            raise OpenEPWError("MALFORMED_RESPONSE", "Malformed NOAA station reports") from None
        sha = hashlib.sha256(raw).hexdigest()
        lineage = {
            v: VariableLineage(
                variable=v,
                source=task.source,
                raw_sha256=sha,
                transforms=["QC flags 0/1/4/5 accepted; nearest report within 30 minutes"]
                + (["Magnus RH from dry/dew"] if v == "relative_humidity" else []),
                derived=v == "relative_humidity",
            )
            for v in frame
        }
        return ProviderResult(
            WeatherDataset(
                data=frame,
                location=task.source.location,
                lineage=lineage,
                metadata={
                    "station": task.source.identity,
                    "missing_policy": "No fill; solar and station pressure absent",
                },
            ),
            task.source,
            raw,
        )
