"""Serial, resumable HTTP collection with conservative crash accounting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx
import truststore


def now():
    return datetime.now(UTC).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def public_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.hostname or "", p.path, "", ""))


SAFE_PARAMS = {
    "lat",
    "lon",
    "latitude",
    "longitude",
    "start_date",
    "end_date",
    "models",
    "timezone",
    "hourly",
    "wkt",
    "dataset",
    "stations",
    "startDate",
    "endDate",
    "format",
    "dataTypes",
    "units",
    "outputformat",
}

# Owner-approved 2026-10-13 (availability gaps, P1): five PVGIS v5_3 TMY probes and one
# justified revision, 1.5 MB each. A small 4xx body is kept for these only (no credentials).
PVGIS_GAP_PROBES = frozenset(
    ("pvgis-ithaca", "pvgis-atlantic", "pvgis-northsea", "pvgis-svalbard", "pvgis-lake-victoria")
)
PVGIS_GAP_PROBE_BYTES = 1_500_000
# Owner-approved 2026-10-13 (availability gaps, N1): ten NSRDB data-query probes at grid edges
# and one justified revision; NSRDB probe cap 17 and the overall probe ceiling 23, for these only.
NSRDB_EDGE_PROBES = frozenset(
    ("nsrdb-honolulu", "nsrdb-recife", "nsrdb-juneau", "nsrdb-buenos-aires", "nsrdb-cape-town",
     "nsrdb-oslo", "nsrdb-dakar", "nsrdb-auckland", "nsrdb-sapporo", "nsrdb-almaty")
)
ERROR_BODY_BYTES = 16_384

# Owner-approved 2026-10-27 (availability follow-ups, item 7): these exact IDs, URLs and kinds,
# and one justified -r1 revision each, may use metadata 100, probes 25, 240 MB in total and
# OneBuilding attempts 55. Other requests keep the earlier ceilings.
_OB = "https://climate.onebuilding.org/sources/"
FOLLOWUP_WORKBOOKS = (
    "NORCERRA", "Region4_Canada_CWEC", "INMET_TRY", "CTZ", "CTZRV2", "CTZ2010", "CTZ2016", "CTZ2022",
    "CTZ2025", "JGMY", "TurTMY", "IMGW", "PHIKO", "NIWA", "ArgTMY", "TMY", "ITMY", "AMTUes", "IMS",
    "CityUHK", "CSWD", "RMY2012", "RMY2024", "NIWA2024", "MetEireann", "BBSR",
)
FOLLOWUP_2026_10_27 = {
    "onebuilding-sources-r20261027": ("documentation", _OB + "default.html"),
    **{f"onebuilding-{name.lower().replace('_', '-')}-xlsx":
       ("inventory", f"{_OB}{name}_EPW_Processing_locations.xlsx") for name in FOLLOWUP_WORKBOOKS},
    "cds-era5-doc": ("documentation", "https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation"),
    "cds-era5land-doc": ("documentation",
                         "https://confluence.ecmwf.int/display/CKB/ERA5-Land%3A+data+documentation"),
    "noaa-inventory-r20261027": ("inventory", "https://www.ncei.noaa.gov/pub/data/noaa/isd-inventory.csv"),
    "naturalearth-10m-land": ("inventory", "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"),
    "pvgis-coast-land": ("probe", "https://re.jrc.ec.europa.eu/api/v5_3/tmy"),
    "pvgis-coast-sea": ("probe", "https://re.jrc.ec.europa.eu/api/v5_3/tmy"),
    "nsrdb-doc-himawari": ("documentation", "https://developer.nlr.gov/docs/solar/nsrdb/himawari-download/"),
}
FOLLOWUP_LIMITS = {"metadata": 100, "probe": 25, "total_bytes": 240_000_000, "onebuilding": 55,
                   "pvgis": 10, "naturalearth_bytes": 10_000_000}


@dataclass(frozen=True)
class Limits:
    metadata_requests: int = 60
    probe_requests: int = 12
    total_bytes: int = 200_000_000
    ordinary_bytes: int = 5_000_000


@dataclass(frozen=True)
class Request:
    id: str
    provider: str
    url: str
    kind: str
    purpose: str
    headers: dict = field(default_factory=dict)
    limit: int = 5_000_000
    allowed_hosts: tuple = ()
    archive: str | None = None
    parent: str | None = None
    depth: int = 0
    revision_of: str | None = None
    correction: str | None = None

    def public(self):
        return {
            "id": self.id,
            "provider": self.provider,
            "url": public_url(self.url),
            "kind": self.kind,
            "purpose": self.purpose,
            "parameters": {
                k: v for k, v in parse_qsl(urlsplit(self.url).query) if k in SAFE_PARAMS
            },
            "range": self.headers.get("Range"),
            "limit": self.limit,
            "archive": self.archive,
            "parent": self.parent,
            "depth": self.depth,
            "revision_of": self.revision_of,
            "correction": self.correction,
        }


class Collector:
    """One process owns the ledger. Reservations survive abrupt process termination.

    An interrupted transfer retains its full byte reservation. This can stop the
    investigation early but cannot reset the budget. Limits are persisted and cannot
    be raised by a later invocation. No automatic retry of any attempted request.
    """

    def __init__(self, root, *, limits=None, transport=None, spacing=2, deadline=60):
        self.root = Path(root)
        self.limits = limits or Limits()
        self.transport = transport
        self.spacing = spacing
        self.deadline = deadline

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True)
        self.lock = (self.root / "collector.lock").open("a+b")
        self.lock.seek(0)
        if os.name == "nt":
            import msvcrt

            if self.lock.read(1) == b"":
                self.lock.write(b"0")
                self.lock.flush()
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = self.root / "ledger.json"
        self.ledger = (
            json.loads(path.read_text())
            if path.exists()
            else {
                "schema_version": "mcp-research-1",
                "created_at": now(),
                "limits": asdict(self.limits),
                "counts": {"metadata": 0, "probe": 0},
                "charged_bytes": 0,
                "blocked_providers": [],
                "last_host_attempt": {},
                "records": [],
                "archive_bytes": {},
            }
        )
        self.limits = Limits(**self.ledger["limits"])
        self.save()
        return self

    def __exit__(self, *_):
        self.lock.close()

    def save(self):
        atomic_json(self.root / "ledger.json", self.ledger)

    def collect(self, request):
        if any(key not in {"Range", "If-Match", "If-None-Match", "Accept"} for key in request.headers):
            raise ValueError("Only public research headers Range, If-Match, If-None-Match and Accept "
                             "are allowed")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,95}", request.id):
            raise ValueError("Invalid research request identifier")
        if request.kind not in ("documentation", "inventory", "metadata", "probe"):
            raise ValueError("Invalid research request category")
        p = urlsplit(request.url)
        if p.scheme != "https" or p.username or p.password or p.fragment or p.port:
            raise ValueError("Only public HTTPS research endpoints are allowed")
        identity = hashlib.sha256(json.dumps(asdict(request), sort_keys=True).encode()).hexdigest()
        previous = [r for r in self.ledger["records"] if r["id"] == request.id]
        if previous:
            if previous[-1]["identity"] != identity:
                raise ValueError("Request ID already used with different inputs")
            return previous[-1]
        record = {
            **request.public(),
            "identity": identity,
            "started_at": now(),
            "outcome": "pending",
            "bytes_read": 0,
            "charged_bytes": 0,
            "hops": [],
        }
        self.ledger["records"].append(record)
        if request.revision_of:
            originals = [r for r in self.ledger["records"] if r["id"] == request.revision_of]
            revisions = [
                r for r in self.ledger["records"] if r.get("revision_of") == request.revision_of
            ]
            if (
                not originals
                or originals[0]["outcome"] == "saved"
                or not request.correction
                or originals[0].get("revision_of")
                or len(revisions) > 1
            ):
                return self.finish(record, "revision_rejected")
        if request.provider in self.ledger["blocked_providers"]:
            return self.finish(record, "provider_backoff")
        if request.provider == "onebuilding":
            count = sum(
                len(r["hops"]) for r in self.ledger["records"] if r["provider"] == "onebuilding"
            )
            if (
                count >= self.onebuilding_request_limit(request)
                or request.depth > 2
                or p.path.lower().endswith(".zip")
            ):
                return self.finish(record, "provider_limit")
        if request.kind == "probe":
            caps = {"openmeteo": 3, "pvgis": self.pvgis_probe_limit(request), "noaa": 2,
                    "nsrdb": self.nsrdb_probe_limit(request)}
            count = sum(
                len(r["hops"])
                for r in self.ledger["records"]
                if r["provider"] == request.provider and r["kind"] == "probe"
            )
            if count >= caps.get(request.provider, 0):
                return self.finish(record, "provider_limit")
        cap = self.limits.ordinary_bytes
        # Owner-authorized 2026-09-23 follow-up; no other NOAA/response limit changes.
        if (
            request.provider == "noaa"
            and p.hostname == "www.ncei.noaa.gov"
            and p.path == "/pub/data/noaa/isd-inventory.csv"
            and request.kind == "inventory"
        ):
            cap = 20_000_000
        if request.provider == "cmip6" and p.path == "/cmip6/pangeo-cmip6.csv":
            cap = 100_000_000
        # Owner-approved 2026-10-13 (E4): ECMWF's published ERA5-Land land-sea mask, GRIB only.
        if (request.id in ("era5land-lsm", "era5land-lsm-r1") and request.kind == "inventory"
                and p.hostname == "confluence.ecmwf.int"
                and p.path == "/download/attachments/140385202/lsm_1279l4_0.1x0.1.grb"):
            cap = 20_000_000
        if self.pvgis_gap_probe(request) or (self.followup(request) and request.provider == "pvgis"):
            cap = PVGIS_GAP_PROBE_BYTES
        if self.followup(request) and request.id.startswith("naturalearth-"):
            cap = FOLLOWUP_LIMITS["naturalearth_bytes"]
        if request.archive:
            cap = self.archive_limit(request) - self.ledger["archive_bytes"].get(request.archive, 0)
        cap = min(cap, request.limit, self.total_bytes(request) - self.ledger["charged_bytes"])
        if cap <= 0:
            return self.finish(record, "byte_budget")
        try:
            asyncio.run(self.fetch(request, record, cap))
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self.finish(record, "transport_error")
        return record

    def finish(self, record, outcome):
        record.update(outcome=outcome, finished_at=now())
        self.save()
        return record

    @staticmethod
    def followup(request):
        """True for an exact 2026-10-27 follow-up request (or its one -r1 revision)."""
        base = request.revision_of if request.id.endswith("-r1") and request.revision_of else request.id
        if request.id not in (base, base + "-r1") or base not in FOLLOWUP_2026_10_27:
            return False
        kind, url = FOLLOWUP_2026_10_27[base]
        address = request.url if kind != "probe" else public_url(request.url)
        return request.kind == kind and address == url

    def total_bytes(self, request):
        return FOLLOWUP_LIMITS["total_bytes"] if self.followup(request) else self.limits.total_bytes

    @classmethod
    def onebuilding_request_limit(cls, request):
        if cls.followup(request) and request.provider == "onebuilding":
            return FOLLOWUP_LIMITS["onebuilding"]
        return cls._onebuilding_request_limit(request)

    @staticmethod
    def _onebuilding_request_limit(request):
        approved = {
            "onebuilding-au-coordinate-xlsx": "Region5_Southwest_Pacific_TMYx",
            "onebuilding-normals-coordinate-xlsx": "Normals",
            "onebuilding-tmy3-coordinate-xlsx": "TMY3a",
        }
        # Owner-approved 2026-10-13 (E1): the seven other TMYx regional workbooks, attempts 16-22.
        regions = {
            "onebuilding-region1-xlsx": "Region1_Africa_TMYx",
            "onebuilding-region2-xlsx": "Region2_Asia_TMYx",
            "onebuilding-region2-6-russia-xlsx": "Region2_Region6_Russia_TMYx",
            "onebuilding-region3-xlsx": "Region3_South_America_TMYx",
            "onebuilding-region4-canada-xlsx": "Region4_Canada_TMYx",
            "onebuilding-region4-caribbean-xlsx": "Region4_NA_CA_Caribbean_TMYx",
            "onebuilding-region7-xlsx": "Region7_Antarctica_TMYx",
        }
        filename = regions.get(request.id)
        if (
            request.kind == "inventory"
            and filename
            and request.url
            == f"https://climate.onebuilding.org/sources/{filename}_EPW_Processing_locations.xlsx"
        ):
            return 22
        filename = approved.get(request.id)
        if (
            request.provider == "onebuilding"
            and request.kind == "inventory"
            and filename
            and request.url
            == f"https://climate.onebuilding.org/sources/{filename}_EPW_Processing_locations.xlsx"
        ):
            return 15
        return 12

    @staticmethod
    def pvgis_gap_probe(request):
        base = request.revision_of if request.id.endswith("-r1") else request.id
        p = urlsplit(request.url)
        return (
            request.provider == "pvgis"
            and request.kind == "probe"
            and base in PVGIS_GAP_PROBES
            and request.id in (base, base + "-r1")
            and p.hostname == "re.jrc.ec.europa.eu"
            and p.path == "/api/v5_3/tmy"
        )

    @classmethod
    def pvgis_probe_limit(cls, request):
        """Stage 1 allowed 2; the 2026-10-13 gaps plan (P1) allows 7 for its exact probes."""
        if cls.followup(request):
            return FOLLOWUP_LIMITS["pvgis"]
        return 7 if cls.pvgis_gap_probe(request) else 2

    @staticmethod
    def nsrdb_edge_probe(request):
        base = request.revision_of if request.id.endswith("-r1") else request.id
        p = urlsplit(request.url)
        return (
            request.provider == "nsrdb"
            and request.kind == "probe"
            and base in NSRDB_EDGE_PROBES
            and request.id in (base, base + "-r1")
            and p.hostname == "developer.nlr.gov"
            and p.path == "/api/solar/nsrdb_data_query.json"
        )

    @classmethod
    def nsrdb_probe_limit(cls, request):
        """Owner-approved 2026-10-13 (E2): three more data-query probes at named points; (N1) ten
        edge probes and one revision."""
        if cls.nsrdb_edge_probe(request):
            return 17
        if request.id in ("nsrdb-singapore", "nsrdb-nairobi", "nsrdb-london", "nsrdb-nairobi-r1",
                          "nsrdb-london-r1") and urlsplit(
            request.url
        ).path == "/api/solar/nsrdb_data_query.json":
            return 6
        return 3

    @staticmethod
    def archive_limit(request):
        """Owner-approved follow-up only for the two existing scenario archives."""
        approved = {
            "rcp45": "https://data.openei.org/files/5974/RCP4.5_v1.1.zip",
            "rcp85": "https://data.openei.org/files/5974/RCP8.5_v1.1.zip",
        }
        if request.provider == "oedi" and approved.get(request.archive) == request.url:
            return 17_000_000
        return 10_000_000

    async def fetch(self, request, record, cap):
        started = time.monotonic()
        url = request.url
        headers = {
            "User-Agent": "OpenEPW-MCP-availability/1 (bounded metadata research)",
            "Accept-Encoding": "identity",
            **request.headers,
        }
        allowed = set(request.allowed_hosts) | {urlsplit(url).hostname}
        category = "probe" if request.kind == "probe" else "metadata"
        ceiling = (
            self.limits.probe_requests if category == "probe" else self.limits.metadata_requests
        )
        if self.nsrdb_edge_probe(request):
            ceiling = 23                                   # owner-approved N1 extension
        if self.followup(request):
            ceiling = FOLLOWUP_LIMITS[category]            # owner-approved 2026-10-27 budget

        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        for _ in range(4):
            if request.kind == "probe":
                provider_cap = {"openmeteo": 3, "pvgis": self.pvgis_probe_limit(request), "noaa": 2,
                                "nsrdb": self.nsrdb_probe_limit(request)}.get(request.provider, 0)
                used = sum(
                    len(r["hops"])
                    for r in self.ledger["records"]
                    if r["provider"] == request.provider and r["kind"] == "probe"
                )
                if used >= provider_cap:
                    self.finish(record, "provider_limit")
                    return
            if request.provider == "cmip6" and urlsplit(url).path.endswith("/.zmetadata"):
                used = sum(
                    len(r["hops"])
                    for r in self.ledger["records"]
                    if r["provider"] == "cmip6" and r["url"].endswith("/.zmetadata")
                )
                if used >= 4:
                    self.finish(record, "provider_limit")
                    return
            if self.ledger["counts"][category] >= ceiling:
                self.finish(record, "request_budget")
                return
            if request.provider == "onebuilding" and sum(
                len(r["hops"]) for r in self.ledger["records"] if r["provider"] == "onebuilding"
            ) >= self.onebuilding_request_limit(request):
                self.finish(record, "provider_limit")
                return
            host = urlsplit(url).hostname
            last = self.ledger["last_host_attempt"].get(host, 0)
            wait = max(0, self.spacing - (time.time() - last))
            remaining = self.deadline - (time.monotonic() - started)
            if wait >= remaining:
                self.finish(record, "deadline")
                return
            await asyncio.sleep(wait)
            cap = min(cap, self.total_bytes(request) - self.ledger["charged_bytes"])
            if request.archive:
                cap = min(
                    cap,
                    self.archive_limit(request)
                    - self.ledger["archive_bytes"].get(request.archive, 0),
                )
            if cap <= 0:
                self.finish(record, "byte_budget")
                return
            self.ledger["counts"][category] += 1
            self.ledger["last_host_attempt"][host] = time.time()
            self.ledger["charged_bytes"] += cap
            record["charged_bytes"] += cap
            if request.archive:
                self.ledger["archive_bytes"][request.archive] = (
                    self.ledger["archive_bytes"].get(request.archive, 0) + cap
                )
            hop = {"url": public_url(url), "reserved_bytes": cap, "bytes_read": 0}
            record["hops"].append(hop)
            record["outcome"] = "in_flight"
            self.save()
            outcome, location, body = "transport_error", None, bytearray()
            try:
                async with httpx.AsyncClient(
                    transport=self.transport, verify=context, timeout=30, follow_redirects=False
                ) as client:
                    async with asyncio.timeout(
                        max(0, self.deadline - (time.monotonic() - started))
                    ):
                        async with client.stream("GET", url, headers=headers) as response:
                            hop["status"] = response.status_code
                            record["status"] = response.status_code
                            record["headers"] = {
                                k: response.headers[k][:256]
                                for k in ("content-type", "last-modified", "etag", "content-range")
                                if k in response.headers
                            }
                            if response.status_code == 429:
                                self.ledger["blocked_providers"].append(request.provider)
                                retry = response.headers.get("retry-after", "")
                                record["retry_after_seconds"] = (
                                    int(retry) if retry.isdigit() else None
                                )
                                outcome = "rate_limited"
                            elif response.status_code == 304:
                                outcome = "not_modified"          # a conditional request: unchanged
                            elif response.is_redirect:
                                location = urljoin(url, response.headers.get("location", ""))
                                q = urlsplit(location)
                                if (
                                    q.scheme != "https"
                                    or q.hostname not in allowed
                                    or q.username
                                    or q.password
                                    or q.port
                                    or q.fragment
                                    or any(k not in SAFE_PARAMS for k, _ in parse_qsl(q.query))
                                ):
                                    outcome, location = "redirect_rejected", None
                                else:
                                    outcome = "redirect"
                            elif not response.is_success:
                                outcome = "http_error"
                                if self.pvgis_gap_probe(request) and 400 <= response.status_code < 500:
                                    async for chunk in response.aiter_bytes(chunk_size=4096):
                                        hop["bytes_read"] += len(chunk)
                                        body.extend(chunk)
                                        if len(body) >= min(cap, ERROR_BODY_BYTES):
                                            break
                                    del body[min(cap, ERROR_BODY_BYTES):]
                            elif "Range" in headers and not self.valid_range(response, headers):
                                outcome = "range_rejected"
                            elif response.headers.get("content-encoding", "identity") != "identity":
                                outcome = "encoding_rejected"
                            elif (
                                response.headers.get("content-length", "").isdigit()
                                and int(response.headers["content-length"]) > cap
                            ):
                                outcome = "byte_limit"
                            else:
                                outcome = "saved"
                                length = response.headers.get("content-length", "")
                                known_length = int(length) if length.isdigit() else None
                                # Divide the allowance exactly for unknown-length streams.
                                # At the exact cap, reject conservatively without another read.
                                chunk_size = math.gcd(cap, 65536)
                                async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                                    hop["bytes_read"] += len(chunk)
                                    if hop["bytes_read"] > cap:
                                        outcome = "byte_limit"
                                        break
                                    body.extend(chunk)
                                    if hop["bytes_read"] == cap:
                                        outcome = "saved" if known_length == cap else "byte_limit"
                                        break
                                if (
                                    outcome == "saved"
                                    and known_length is not None
                                    and len(body) != known_length
                                ):
                                    outcome = "truncated_response"
                                if "Range" in headers and outcome == "saved":
                                    span = re.fullmatch(
                                        r"bytes (\d+)-(\d+)/(\d+)",
                                        response.headers["content-range"],
                                    )
                                    if len(body) != int(span[2]) - int(span[1]) + 1:
                                        outcome = "range_rejected"
            except TimeoutError:
                outcome = "deadline"
            except httpx.HTTPError:
                outcome = "transport_error"
            # A crash before here intentionally retains the full reservation.
            actual = hop["bytes_read"]
            charge = actual
            self.ledger["charged_bytes"] += charge - cap
            record["charged_bytes"] += charge - cap
            if request.archive:
                self.ledger["archive_bytes"][request.archive] += charge - cap
            record["bytes_read"] += actual
            if outcome == "saved" or (outcome == "http_error" and body):
                secret_values = [
                    v
                    for k, v in parse_qsl(urlsplit(request.url).query)
                    if k not in SAFE_PARAMS and v != "DEMO_KEY"
                ]
                # An error body is kept apart from snapshots, so analysis never reads it as one.
                saved = outcome == "saved"
                if any(v.encode() in body for v in secret_values if v):
                    outcome = "sensitive_response"
                else:
                    path = self.root / "raw" / (request.id + (".body" if saved else ".error.body"))
                    temp = path.with_suffix(".tmp")
                    temp.write_bytes(body)
                    temp.replace(path)
                    prefix = "" if saved else "error_"
                    record[prefix + "sha256"] = hashlib.sha256(body).hexdigest()
                    record[prefix + "snapshot"] = "raw/" + path.name
            self.finish(record, outcome)
            if location is None:
                return
            if urlsplit(location).hostname != host:
                headers = {
                    k: v
                    for k, v in headers.items()
                    if k.lower() not in ("authorization", "cookie", "x-api-key")
                }
            url = location
        self.finish(record, "redirect_limit")

    @staticmethod
    def valid_range(response, headers):
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
        if response.status_code != 206 or not match or not response.headers.get("etag"):
            return False
        start, end, total = map(int, match.groups())
        wanted = headers["Range"]
        if wanted.startswith("bytes=-"):
            valid = start == max(0, total - int(wanted[7:])) and end == total - 1
        else:
            valid = wanted == f"bytes={start}-{end}"
        return valid and (
            "If-Match" not in headers or headers["If-Match"] == response.headers["etag"]
        )
