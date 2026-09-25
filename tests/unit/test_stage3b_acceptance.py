"""Offline dual-baseline morph and bounded PUMA archive acceptance anchors."""

import hashlib
import io
import json
import zipfile
from calendar import isleap

import httpx
import pytest
from test_epw import synthetic
from test_future import signal

from openepw.config import RuntimeConfig
from openepw.dataset import without_feb_29
from openepw.epw import read_epw
from openepw.epw.writer import epw_bytes
from openepw.generation.hourly_archive import LOCATIONS, ROOT
from openepw.jobs.worker import JobRunner
from openepw.models import (
    Candidate,
    FutureRequest,
    Location,
    OpenEPWError,
    SourceRef,
    VariableLineage,
    WeatherRequest,
)
from openepw.providers.base import ProviderResult
from openepw.providers.http import HttpClient
from openepw.service import WeatherService


def _job(service, plan):
    runner = JobRunner(service)
    runner.enqueue = lambda _: None
    job = runner.submit(plan.plan_hash)
    runner.run(job.id)
    final = runner.store.get(job.id)
    runner.close()
    return final


def test_morph_accepts_uploaded_and_fetched_complete_baselines(tmp_path):
    class CompleteStation:
        name = "station"

        def discover(self, request, location, http):
            source = SourceRef(provider="station", dataset="synthetic",
                               identity="study", location=location, provisional=False)
            return [Candidate(id="station:study", location_id=location.key,
                              source=source, weather_types=["historical"])]

        def fetch(self, task, http):
            data = synthetic(2023, 8760)
            data.location = task.source.location
            data.lineage = {variable: VariableLineage(
                variable=variable, source=task.source,
                raw_sha256=hashlib.sha256(b"complete-synthetic").hexdigest())
                for variable in data.data}
            return ProviderResult(data, task.source, b"complete-synthetic")

    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"),
                             providers=[CompleteStation()])
    location = Location(lat=42, lon=-76)
    weather = _job(service, service.plan(WeatherRequest(
        locations=location, years=[2023], providers=["station"])))
    assert weather.state == "completed"
    fetched = weather.bundle.weather[0]
    uploaded = service.register_baseline(epw_bytes(synthetic(2023, 8760)))
    assert uploaded.registration_route == "upload"
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps([signal().model_dump(mode="json")]))
    for baseline, origin in ((uploaded, "user_provided"), (fetched, "weather_output")):
        plan = service.plan_future(FutureRequest(
            baseline=baseline.id, signals=str(signals),
            reference_period=(1985, 2014), climate_period=(2036, 2065),
            climate_scenario="ssp245"))
        assert plan.baseline_ref.origin == origin
        final = _job(service, plan)
        assert final.state == "completed" and final.completed == 1
        _, path = service.artifacts.resolve(final.bundle.weather[0].id)
        assert len(read_epw(path).data) == 8760
        _, manifest_path = service.artifacts.resolve(final.bundle.manifest.id)
        output = json.loads(manifest_path.read_text())["outputs"][0]
        assert output["method"] == "morph"
        assert output["baseline_artifact_id"] == baseline.id
        assert output["climate_period"] == [2036, 2065]
        assert output["baseline_origin"] == origin
        if origin == "weather_output":
            assert output["baseline_manifest_id"] == plan.baseline_ref.source_manifest_id


def test_climate_profile_reads_bounded_synthetic_puma_archive(tmp_path):
    site = "G01000100"
    scenario = "RCP8.5"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for year in range(2045, 2055):
            data = synthetic(year, 8784 if isleap(year) else 8760)
            if isleap(year):
                data = without_feb_29(data)
            data.location = Location(lat=42.1, lon=-76.1)
            data.data["dry_bulb"] = 10 + (year - 2045)
            read_epw(epw_bytes(data), calendar="noleap")
            archive.writestr(f"future/{site}_{scenario}_{year}_lat42.epw",
                             epw_bytes(data))
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
            start = max(0, len(raw) + int(span))
            end = len(raw) - 1
        else:
            start, end = map(int, span.split("-"))
        return httpx.Response(206, content=raw[start:end + 1],
                              headers={"ETag": "synthetic-v1",
                                       "Content-Range":
                                       f"bytes {start}-{end}/{len(raw)}"})

    config = RuntimeConfig(data_root=tmp_path / "store")
    service = WeatherService(config, http=HttpClient(
        config, transport=httpx.MockTransport(handler)))
    baseline = service.register_baseline(epw_bytes(synthetic(2023, 8760)))
    request = FutureRequest(baseline=baseline.id, method="climate_profile",
                            target_year=2050, climate_scenario="rcp85")
    plan = service.plan_future(request)
    assert plan.request.climate_period == (2045, 2054)
    final = _job(service, plan)
    assert final.state == "completed" and final.completed == 1, [
        issue.model_dump() for issue in final.errors]
    _, path = service.artifacts.resolve(final.bundle.weather[0].id)
    output = read_epw(path)
    assert len(output.data) == 8760
    _, manifest_path = service.artifacts.resolve(final.bundle.manifest.id)
    detail = json.loads(manifest_path.read_text())["outputs"][0]
    assert detail["method"] == "climate_profile"
    assert detail["metadata"]["user_baseline_location"]["lat"] == 42
    assert detail["lineage"]["dry_bulb"]["source"]["provider"] == "oedi"
    with pytest.raises(OpenEPWError, match="UNSUPPORTED_GEOGRAPHY"):
        distant_data = synthetic(2023, 8760)
        distant_data.location = Location(lat=0, lon=0)
        distant = service.register_baseline(epw_bytes(distant_data))
        service.plan_future(request.model_copy(update={"baseline": distant.id}))
