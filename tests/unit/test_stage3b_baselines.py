"""Future baselines are registered artifacts with explicit QC and provenance."""

import json

import pytest
from test_epw import synthetic
from test_future import signal

from openepw.config import RuntimeConfig
from openepw.epw import read_epw, write_epw
from openepw.models import FutureRequest, Location, OpenEPWError, SourceRef, VariableLineage
from openepw.service import WeatherService


def _service_and_signals(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps([signal().model_dump(mode="json")]))
    return service, signals


def _request(baseline, signals):
    return FutureRequest(baseline=str(baseline), signals=str(signals),
                         reference_period=(1985, 2014), climate_period=(2036, 2065),
                         climate_scenario="ssp245")


def test_registered_user_file_is_idempotent_and_has_unknown_provider(tmp_path):
    service, signals = _service_and_signals(tmp_path)
    file = tmp_path / "user.epw"
    write_epw(synthetic(2023, 8760), file)
    first = service.register_baseline(file)
    second = service.register_baseline(file)
    assert first.id == second.id
    plan = service.plan_future(_request(first.id, signals))
    assert plan.baseline_ref.artifact_id == first.id
    assert plan.baseline_ref.sha256 == first.sha256
    assert plan.baseline_ref.origin == "user_provided"
    assert plan.baseline_ref.registration_route == "allowlisted_path"
    assert plan.baseline_ref.source_manifest_id is None
    assert plan.baseline_ref.input_qc == []
    _, registered_path = service.artifacts.resolve(first.id)
    assert read_epw(registered_path).lineage["dry_bulb"].source.provider == "input_epw"


def test_fetched_weather_id_links_verified_manifest_and_qc(tmp_path):
    service, signals = _service_and_signals(tmp_path)
    from openepw.epw.writer import epw_bytes

    bundle_id = "a" * 32
    weather = service.artifacts.write(bundle_id, "weather.epw",
                                      epw_bytes(synthetic(2023, 8760)), "weather",
                                      "application/vnd.energyplus.epw")
    observed_source = SourceRef(provider="station", dataset="known observation",
                                identity="source-station",
                                location=Location(lat=40, lon=-75), provisional=False)
    lineage = VariableLineage(variable="dry_bulb", source=observed_source,
                              raw_sha256="1" * 64)
    manifest = service.artifacts.json(bundle_id, "manifest.json", {
        "outputs": [{"artifact_id": weather.id, "output_id": "b" * 64,
                     "lineage": {"dry_bulb": lineage.model_dump(mode="json")}}]}, "manifest")
    qc = service.artifacts.json(bundle_id, "qc.json", [], "qc")
    plan = service.plan_future(_request(weather.id, signals))
    assert plan.baseline_ref.origin == "weather_output"
    assert plan.baseline_ref.artifact_id == weather.id
    assert plan.baseline_ref.source_output_id == "b" * 64
    assert plan.baseline_ref.source_manifest_id == manifest.id
    assert plan.baseline_ref.source_qc_id == qc.id
    result = service.execute(plan)
    _, output_manifest = service.artifacts.resolve(result.manifest.id)
    output = json.loads(output_manifest.read_text())["outputs"][0]
    assert output["metadata"]["baseline_lineage"]["dry_bulb"]["source"][
        "location"]["lat"] == 40
    (tmp_path / "store" / qc.path).write_bytes(b"corrupt")
    with pytest.raises(OpenEPWError, match="INVALID_ARTIFACT|PLAN_STALE"):
        service.execute(plan)


@pytest.mark.parametrize("change", ["short", "missing", "corrupt"])
def test_invalid_annual_baseline_is_rejected_before_plan(tmp_path, change):
    service, signals = _service_and_signals(tmp_path)
    file = tmp_path / "bad.epw"
    data = synthetic(2023, 24 if change == "short" else 8760)
    if change == "missing":
        data.data.loc[data.data.index[1], "dry_bulb"] = float("nan")
    write_epw(data, file)
    ref = service.register_baseline(file)
    if change == "corrupt":
        (tmp_path / "store" / ref.path).write_bytes(b"corrupt")
    with pytest.raises(OpenEPWError, match="INVALID_BASELINE|MISSING_CRITICAL_VARIABLE|INVALID_ARTIFACT") as error:
        service.plan_future(_request(ref.id, signals))
    if change == "missing":
        assert "dry_bulb" in error.value.issue.message
    if change == "short":
        assert "INCOMPLETE_YEAR" in error.value.issue.message


def test_mismatched_fetched_manifest_is_not_silently_ignored(tmp_path):
    service, signals = _service_and_signals(tmp_path)
    from openepw.epw.writer import epw_bytes

    bundle_id = "c" * 32
    weather = service.artifacts.write(bundle_id, "weather.epw",
                                      epw_bytes(synthetic(2023, 8760)), "weather")
    service.artifacts.json(bundle_id, "manifest.json", {
        "outputs": [{"artifact_id": "other"}]}, "manifest")
    service.artifacts.json(bundle_id, "qc.json", [], "qc")
    with pytest.raises(OpenEPWError, match="INVALID_BASELINE"):
        service.plan_future(_request(weather.id, signals))


def test_noaa_sentinel_weather_artifact_is_not_an_annual_future_baseline(tmp_path):
    from test_noaa_gap_output import _execute

    bundle = _execute(tmp_path / "store", "warn")
    assert len(bundle.weather) == 1
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps([signal().model_dump(mode="json")]))
    with pytest.raises(OpenEPWError, match="MISSING_CRITICAL_VARIABLE"):
        service.plan_future(_request(bundle.weather[0].id, signals))
