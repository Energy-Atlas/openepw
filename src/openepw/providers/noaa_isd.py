import hashlib
import io
import json

import numpy as np
import pandas as pd

from .. import pressure as station_pressure
from ..dataset import WeatherDataset
from ..models import Candidate, Location, OpenEPWError, SourceRef, VariableLineage
from .base import ProviderResult
from .openmeteo import interval_bounds

ACCEPTED_QC = ("0", "1", "4", "5")
# Where each hour's station pressure came from (normalize_isd with pressure_elevation).
PRESSURE_METHODS = ("reported", "altimeter", "sea_level")


def _pressure(text):
    """A pressure field "10132,1" in tenths of hPa, or NaN when missing (99999) or rejected."""
    parts = str(text or "").split(",")
    if len(parts) < 2 or parts[1] not in ACCEPTED_QC or not parts[0].strip().lstrip("+-").isdigit():
        return np.nan
    raw = float(parts[0])
    return np.nan if raw >= 99999 else raw / 10


def _station_pressure(row, dry_bulb, elevation):
    """One report's station pressure (Pa) and how it was obtained, best first: the reported
    station pressure (MA1), the altimeter setting (MA1), then sea-level pressure (SLP)."""
    ma1 = str(row.get("MA1") or "").split(",")
    reported = _pressure(",".join(ma1[2:4])) if len(ma1) == 4 else np.nan
    if np.isfinite(reported):
        return reported * 100, "reported"
    if elevation is None:
        return np.nan, None
    altimeter = _pressure(",".join(ma1[:2])) if len(ma1) == 4 else np.nan
    if np.isfinite(altimeter):
        return float(station_pressure.from_altimeter(altimeter, elevation)) * 100, "altimeter"
    sea_level = _pressure(row.get("SLP"))
    if np.isfinite(sea_level) and np.isfinite(dry_bulb):
        value = float(station_pressure.from_sea_level(sea_level, dry_bulb, elevation)) * 100
        if np.isfinite(value):
            return value, "sea_level"
    return np.nan, None


def normalize_isd(rows, target, *, pressure_elevation=None, derive_pressure=False):
    """Hourly values from ISD reports: the nearest report within 30 minutes of each hour.

    With ``derive_pressure`` each report's station pressure is added from its own pressure
    fields (see _station_pressure; the altimeter and sea-level routes need the station
    elevation), and ``_pressure_method`` names the route per hour for the lineage.
    """
    def field(text, scale=10):
        parts = str(text or "").split(",")
        if len(parts) < 2 or parts[1] not in ACCEPTED_QC or abs(float(parts[0])) >= 9999:
            return np.nan
        return float(parts[0]) / scale

    values = []
    for row in rows:
        wind = str(row.get("WND", "")).split(",")
        value = {
            "time": pd.Timestamp(row["DATE"], tz="UTC"),
            "dry_bulb": field(row.get("TMP")),
            "dew_point": field(row.get("DEW")),
            "wind_direction": field(",".join(wind[:2]), 1)
            if len(wind) == 5 and wind[0] != "999"
            else np.nan,
            "wind_speed": field(",".join(wind[3:])) if len(wind) == 5 else np.nan,
        }
        if derive_pressure:
            value["pressure"], value["_pressure_method"] = _station_pressure(
                row, value["dry_bulb"], pressure_elevation)
        values.append(value)
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
                        "No solar radiation; station pressure only when worked out from the station's own "
                        "pressure reports (a data-gap choice), never sea-level pressure as is",
                        "GHCNh successor is not this adapter",
                    ],
                )
            )
        return candidates

    def fetch(self, task, http):
        start, end = interval_bounds(task.parameters)
        # A plan asks for station pressure from the station's own reports (planning/gaps.py).
        derive_pressure = "pressure" in (task.parameters.get("derived") or [])
        elevation = task.source.location.elevation if task.source.location else None
        params = {
            "dataset": "global-hourly",
            "stations": task.source.identity,
            "startDate": (start - pd.Timedelta(days=1)).date().isoformat(),
            "endDate": end.date().isoformat(),
            "format": "json",
            "dataTypes": "TMP,DEW,WND" + (",SLP,MA1" if derive_pressure else ""),
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
                json.loads(raw), pd.date_range(start + pd.Timedelta(hours=1), end, freq="h"),
                pressure_elevation=elevation, derive_pressure=derive_pressure,
            )
        except (ValueError, KeyError, TypeError):
            raise OpenEPWError("MALFORMED_RESPONSE", "Malformed NOAA station reports") from None
        methods = frame.pop("_pressure_method") if "_pressure_method" in frame else None
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
        metadata = {"station": task.source.identity,
                    "missing_policy": "No fill; solar and station pressure absent"}
        if methods is not None:
            counts = {method: int((methods == method).sum()) for method in PRESSURE_METHODS}
            lineage["pressure"] = VariableLineage(
                variable="pressure", source=task.source, raw_sha256=sha,
                transforms=[
                    "QC flags 0/1/4/5 accepted; nearest report within 30 minutes",
                    pressure_note(counts, elevation),
                ],
                dependencies=["MA1", "SLP"] + (["dry_bulb"] if counts["sea_level"] else []),
                derived=bool(counts["altimeter"] or counts["sea_level"]),
            )
            metadata.update(missing_policy="No fill; solar absent; station pressure from the station's reports",
                            pressure_hours=counts)
        return ProviderResult(
            WeatherDataset(
                data=frame,
                location=task.source.location,
                lineage=lineage,
                metadata=metadata,
            ),
            task.source,
            raw,
        )


def pressure_note(counts, elevation):
    """The lineage line for station pressure taken from a station's reports."""
    where = f"station elevation {elevation:g} m" if elevation is not None else "station elevation unknown"
    return (f"station pressure from the station's reports: {counts['reported']} h reported (MA1), "
            f"{counts['altimeter']} h from the altimeter setting (ICAO standard atmosphere, {where}), "
            f"{counts['sea_level']} h from sea-level pressure (hypsometric, 6.5 K/km column, stations "
            f"up to {station_pressure.SLP_MAX_ELEVATION_M:g} m); hours without a usable report stay missing")
