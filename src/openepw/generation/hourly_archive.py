import hashlib
import io
import re
import zipfile
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

from ..artifacts.store import atomic_write
from ..epw import read_epw
from ..models import Issue, Location, OpenEPWError, SourceRef, VariableLineage, digest
from .climate_profile import select_profile

ROOT = "https://data.openei.org/files/5974/"
LOCATIONS = ROOT + "PUMA%20information%20%281%29.csv"


class RemoteZip(io.RawIOBase):
    def __init__(self, url, http, *, expected_etag=None, budget=30_000_000):
        self.url = url
        self.http = http
        self.pos = 0
        self.transferred = 0
        self.budget = budget
        raw, headers, status = http.request(
            "GET", url, headers={"Range": "bytes=-65536"}, limit=65536
        )
        if status != 206 or "content-range" not in headers or not headers.get("etag"):
            raise OpenEPWError(
                "PROVIDER_UNAVAILABLE", "Archive server ignored Range or lacks stable ETag"
            )
        self.size = int(headers["content-range"].split("/")[-1])
        self.etag = headers["etag"]
        if expected_etag and self.etag != expected_etag:
            raise OpenEPWError("PLAN_STALE", "Hourly archive ETag changed since planning")
        self.tail_start = self.size - len(raw)
        self.tail = raw
        self.transferred = len(raw)
        self.cache = (
            Path(http.config.data_root)
            / "cache"
            / "ranges"
            / digest({"url": url, "etag": self.etag})
        )

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        target = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        if target < 0 or target > self.size:
            raise OpenEPWError("MALFORMED_RESPONSE", "Archive offset out of bounds")
        self.pos = target
        return target

    def tell(self):
        return self.pos

    def read(self, size=-1):
        size = min(self.size - self.pos, self.size if size < 0 else size)
        if size <= 0:
            return b""
        if self.pos >= self.tail_start:
            body = self.tail[self.pos - self.tail_start : self.pos - self.tail_start + size]
        else:
            path = self.cache / f"{self.pos}-{size}.bin"
            checksum = path.with_suffix(".sha256")
            if (
                path.is_file()
                and checksum.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == checksum.read_text()
            ):
                body = path.read_bytes()
            else:
                if self.transferred + size > self.budget:
                    raise OpenEPWError("RESOURCE_LIMIT", "Hourly archive range budget exceeded")
                body, headers, status = self.http.request(
                    "GET",
                    self.url,
                    headers={
                        "Range": f"bytes={self.pos}-{self.pos + size - 1}",
                        "If-Match": self.etag,
                    },
                    limit=size,
                )
                if (
                    status != 206
                    or headers.get("etag") != self.etag
                    or headers.get("content-range")
                    != f"bytes {self.pos}-{self.pos + size - 1}/{self.size}"
                    or len(body) != size
                ):
                    raise OpenEPWError(
                        "PLAN_STALE", "Changed, truncated or ignored archive byte range"
                    )
                self.transferred += len(body)
                atomic_write(path, body)
                atomic_write(checksum, hashlib.sha256(body).hexdigest().encode())
        self.pos += len(body)
        return body


class HourlyArchive:
    def __init__(self, http):
        self.http = http

    def plan(self, request, location):
        if request.climate_scenario not in ("rcp45", "rcp85") or request.climate_period not in (
            (2045, 2054),
            (2085, 2094),
        ):
            raise OpenEPWError(
                "INVALID_SCENARIO_PERIOD",
                "Hourly archive requires RCP4.5/8.5 and 2045–2054 or 2085–2094",
            )
        data = self.http.get(LOCATIONS)
        table = pd.read_csv(io.BytesIO(data), encoding="latin-1")
        lat = np.deg2rad(table.Latitude.to_numpy())
        a = (
            np.sin((lat - np.deg2rad(location.lat)) / 2) ** 2
            + np.cos(lat)
            * np.cos(np.deg2rad(location.lat))
            * np.sin(np.deg2rad(table.Longitude.to_numpy() - location.lon) / 2) ** 2
        )
        distances = 6371 * 2 * np.arcsin(np.sqrt(a))
        i = int(np.argmin(distances))
        if distances[i] > 150:
            raise OpenEPWError(
                "UNSUPPORTED_GEOGRAPHY",
                "No published PUMA centroid within 150 km; archive does not cover arbitrary sites",
            )
        row = table.iloc[i]
        site = str(row["PUMA Number"])
        scenario = "RCP4.5" if request.climate_scenario == "rcp45" else "RCP8.5"
        url = ROOT + scenario + "_v1.1.zip"
        stream = RemoteZip(url, self.http)
        with zipfile.ZipFile(stream) as archive:
            names = archive.namelist()
        members = {}
        for year in range(request.climate_period[0], request.climate_period[1] + 1):
            matches = [
                n
                for n in names
                if re.search(
                    r"/" + re.escape(site) + "_" + re.escape(scenario) + "_" + str(year) + r"_lat",
                    n,
                )
                and n.endswith(".epw")
            ]
            if len(matches) != 1:
                raise OpenEPWError("UNAVAILABLE_PERIOD", "Archive lacks unique site/year member")
            members[str(year)] = matches[0]
        warnings = [
            "WRF3.3.1/CCSM4, 12 km model at sparse published PUMA centroids; residual bias remains",
            "User baseline supplies site/comparison identity and is not morphed",
            "Ensemble represents temporal years of one driving model, not multiple models",
            f"Resolved PUMA centroid {float(distances[i]):.1f} km from requested site",
        ]
        if request.climate_scenario == "rcp45" and request.climate_period == (2085, 2094):
            warnings.append(
                "Source authors flag anomalous late-century RCP4.5 Great Plains warming"
            )
        return {
            "archive_url": url,
            "archive_etag": stream.etag,
            "members": members,
            "site": site,
            "distance_km": float(distances[i]),
            "site_location": Location(
                lat=float(row.Latitude),
                lon=float(row.Longitude),
                elevation=float(row.Elevation),
                standard_offset_minutes=int(float(row["Time Zone"]) * 60),
                name=str(row["PUMA Name"]),
            ).model_dump(),
            "locations_sha256": hashlib.sha256(data).hexdigest(),
            "warnings": warnings,
        }

    def read_years(self, url, site, members=None, etag=None):
        if url not in (
            ROOT + "RCP4.5_v1.1.zip",
            ROOT + "RCP8.5_v1.1.zip",
            ROOT + "Baseline_v1.1.zip",
        ):
            raise OpenEPWError("INVALID_REQUEST", "Unknown hourly archive URL")
        stream = RemoteZip(url, self.http, expected_etag=etag)
        result = {}
        with zipfile.ZipFile(stream) as archive:
            if members is None:
                members = {}
                for name in archive.namelist():
                    match = re.search(re.escape(site) + r"_.*?_(199[5-9]|200[0-4])_lat", name)
                    if match and name.endswith(".epw"):
                        members[match.group(1)] = name
                if len(members) != 10:
                    raise OpenEPWError(
                        "UNAVAILABLE_PERIOD", "Paired archive baseline is incomplete"
                    )
            for year, name in members.items():
                info = archive.getinfo(name)
                if info.file_size > 3_000_000 or info.compress_size > 3_000_000:
                    raise OpenEPWError("RESOURCE_LIMIT", "Hourly archive member too large")
                try:
                    raw = archive.read(info)
                except (zipfile.BadZipFile, EOFError):
                    raise OpenEPWError(
                        "MALFORMED_RESPONSE", "Hourly archive member failed CRC or decompression"
                    ) from None
                data = read_epw(raw)
                source = SourceRef(
                    provider="oedi",
                    dataset="Argonne WRF/CCSM4",
                    version="1.1",
                    identity=name,
                    location=data.location,
                    provisional=False,
                    resolution_km=12,
                    license="CC BY 4.0",
                    citation="https://doi.org/10.25984/2202668",
                )
                sha = hashlib.sha256(raw).hexdigest()
                data.lineage = {
                    str(v): VariableLineage(variable=v, source=source, raw_sha256=sha)
                    for v in data.data
                    if v != "flags"
                }
                result[int(year)] = data
        return result

    def generate(self, request, params, baseline):
        years = self.read_years(
            params["archive_url"], params["site"], params["members"], params["archive_etag"]
        )
        paired = (
            self.read_years(ROOT + "Baseline_v1.1.zip", params["site"])
            if request.profile == "extreme" and request.extreme.get("mode") == "persistence"
            else {}
        )
        selected = select_profile(years, paired, request.profile, request.extreme)
        results = []
        for year in selected:
            data = deepcopy(years[year])
            data.metadata = {
                "method": "climate_profile",
                "method_version": "0.1",
                "selected_year": year,
                "ensemble_kind": "temporal_years",
                "profile": request.profile,
                "extreme": request.extreme,
                "site": params["site"],
                "distance_km": params["distance_km"],
                "archive_etag": params["archive_etag"],
                "baseline_role": "User EPW: site and comparison identity only; not morphed",
                "user_baseline_location": baseline.location.model_dump(),
                "threshold_reference_period": [1995, 2004] if paired else None,
                "threshold_rule": "calendar-day +/-15 days; hot95/cold5; exclude Feb29 for thresholds"
                if paired
                else None,
                "selection": "full-year monthly-feature medoid"
                if request.profile == "typical"
                else "full coherent trajectory",
                "limitations": params["warnings"],
            }
            data.issues.extend(
                Issue(code="CLIMATE_LIMITATION", message=w) for w in params["warnings"]
            )
            results.append(data)
        return results
