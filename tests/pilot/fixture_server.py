"""Synthetic stdio server for cross-stage pilot journeys. No provider network."""

import argparse
import hashlib
import io
import json
import sys
import zipfile
from calendar import isleap
from pathlib import Path

import httpx

from openepw.config import RuntimeConfig
from openepw.dataset import without_feb_29
from openepw.epw.writer import epw_bytes
from openepw.generation.hourly_archive import LOCATIONS, ROOT
from openepw.mcp.server import create_server
from openepw.models import (
    Candidate,
    DiscoveryResult,
    Location,
    SourceRef,
    VariableLineage,
    WeatherRequest,
)
from openepw.providers.base import ProviderResult
from openepw.providers.http import HttpClient
from openepw.providers.noaa_isd import NOAAProvider
from openepw.service import WeatherService

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic


class CompleteStation:
    name = "station"

    def discover(self, request, location, http):
        if request.product not in ("historical", "amy"):
            return []
        source = SourceRef(
            provider=self.name, dataset="complete-synthetic",
            identity="ithaca-station", location=location, provisional=False)
        return [Candidate(
            id="station:ithaca", source=source, location_id=location.key,
            weather_types=["historical", "amy"])]

    def fetch(self, task, http):
        data = synthetic(2024, 8784)
        data.location = task.source.location
        data.lineage = {
            variable: VariableLineage(
                variable=variable, source=task.source,
                raw_sha256=hashlib.sha256(b"pilot-complete").hexdigest())
            for variable in data.data
        }
        return ProviderResult(data, task.source, b"pilot-complete")


class AlternativeStation:
    name = "alternative"

    def discover(self, request, location, http):
        if request.product not in ("historical", "amy"):
            return []
        source = SourceRef(
            provider=self.name, dataset="unverified-synthetic",
            identity="alternative", location=location, provisional=True)
        return [Candidate(
            id="alternative:unknown", source=source, location_id=location.key,
            weather_types=["historical", "amy"],
            missing_fields=["geographic coverage unverified"])]

    def fetch(self, task, http):
        raise AssertionError("Unverified alternative must never be fetched")


class PublishedProvider:
    name = "onebuilding"
    product_id = "USA/NY/Ithaca.zip"

    def discover(self, request, location, http):
        if request.product != "tmyx" or not (
            41.5 <= location.lat <= 43.5 and -77.5 <= location.lon <= -75.5
        ):
            return []
        if request.product_id and request.product_id != self.product_id:
            return []
        source = SourceRef(
            provider=self.name, dataset="OneBuilding published EPW",
            identity="/" + self.product_id,
            citation="https://climate.onebuilding.org/" + self.product_id,
            location=Location(lat=42.44, lon=-76.5), provisional=False)
        return [Candidate(
            id="published:ithaca", location_id=location.key,
            product_id=self.product_id, source=source,
            weather_types=["tmyx"])]

    def fetch(self, task, http):
        data = synthetic(2023, 8760)
        data.location = task.source.location
        data.lineage = {
            variable: VariableLineage(
                variable=variable, source=task.source,
                raw_sha256=hashlib.sha256(b"pilot-published").hexdigest())
            for variable in data.data
        }
        return ProviderResult(data, task.source, b"pilot-published")


def noaa_service(root):
    row = {"DATE": "2024-01-01T01:00:00", "TMP": "+0200,1",
           "DEW": "+0100,1", "WND": "180,1,N,0020,1"}
    complete_rows = [
        {**row, "DATE": f"2024-01-01T{hour:02}:00:00"}
        for hour in range(1, 24)
    ] + [{**row, "DATE": "2024-01-02T00:00:00"}]
    config = RuntimeConfig(data_root=root)
    http = HttpClient(config, transport=httpx.MockTransport(
        lambda request: httpx.Response(
            200, json=complete_rows if request.url.params.get("stations") == "B00002"
            else [row])))
    service = WeatherService(config, http=http, providers=[NOAAProvider()])
    location = Location(lat=42, lon=-76)
    source = SourceRef(provider="noaa", dataset="ISD global-hourly",
                       identity="A00002", location=location, provisional=False)
    candidate = Candidate(
        id="noaa:A00002", location_id=location.key, product_id="A00002",
        source=source, weather_types=["historical", "amy"],
        variables=["dry_bulb"])
    discovery = DiscoveryResult(
        locations=[location], candidates=[candidate],
        selected_candidate_ids=[candidate.id])
    hashes = {}
    for policy in ("warn", "error"):
        request = WeatherRequest(
            locations=location, start="2024-01-01", end="2024-01-01",
            providers=["noaa"], required_variables=["dry_bulb"],
            missing_policy=policy)
        hashes[policy] = service.plan(request, discovery=discovery).plan_hash
    other = Location(lat=43, lon=-76)
    other_source = source.model_copy(update={"identity": "B00002", "location": other})
    other_candidate = candidate.model_copy(update={
        "id": "noaa:B00002", "location_id": other.key,
        "product_id": "B00002", "source": other_source,
    })
    batch_request = WeatherRequest(
        locations=[location, other], start="2024-01-01", end="2024-01-01",
        providers=["noaa"], required_variables=["dry_bulb"],
        missing_policy="error")
    batch_discovery = DiscoveryResult(
        locations=[location, other], candidates=[candidate, other_candidate],
        selected_candidate_ids=[candidate.id, other_candidate.id])
    hashes["batch_error"] = service.plan(
        batch_request, discovery=batch_discovery).plan_hash
    (root / "noaa-hashes.json").write_text(json.dumps(hashes), encoding="utf-8")
    return service


def puma_service(root):
    site = "G01000100"
    scenario = "RCP8.5"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for year in range(2045, 2055):
            data = synthetic(year, 8784 if isleap(year) else 8760)
            if isleap(year):
                data = without_feb_29(data)
            data.location = Location(lat=42.1, lon=-76.1)
            data.data["dry_bulb"] = 10 + year - 2045
            archive.writestr(
                f"future/{site}_{scenario}_{year}_lat42.epw", epw_bytes(data))
    raw = buffer.getvalue()
    locations = ("PUMA Number,Latitude,Longitude,Elevation,Time Zone,PUMA Name\n"
                 f"{site},42.1,-76.1,100,-5,Synthetic site\n").encode()

    def handler(request):
        if str(request.url) == LOCATIONS:
            return httpx.Response(200, content=locations)
        if str(request.url) != ROOT + "RCP8.5_v1.1.zip":
            raise AssertionError("Unexpected archive URL")
        span = request.headers["Range"].removeprefix("bytes=")
        if span.startswith("-"):
            start, end = max(0, len(raw) + int(span)), len(raw) - 1
        else:
            start, end = map(int, span.split("-"))
        return httpx.Response(
            206, content=raw[start:end + 1],
            headers={"ETag": "synthetic-v1",
                     "Content-Range": f"bytes {start}-{end}/{len(raw)}"})

    config = RuntimeConfig(data_root=root)
    return WeatherService(config, http=HttpClient(
        config, transport=httpx.MockTransport(handler)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--mode", choices=["general", "noaa", "puma"], default="general")
    args = parser.parse_args()
    args.data_root.mkdir(parents=True, exist_ok=True)
    if args.mode == "noaa":
        service = noaa_service(args.data_root)
    elif args.mode == "puma":
        service = puma_service(args.data_root)
    else:
        service = WeatherService(
            RuntimeConfig(data_root=args.data_root),
            providers=[CompleteStation(), AlternativeStation(), PublishedProvider()])
    create_server(service).run(transport="stdio")


if __name__ == "__main__":
    main()
