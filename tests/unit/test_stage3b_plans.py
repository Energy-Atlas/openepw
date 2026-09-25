"""Future plans retain scientific selectors and durable integrity references."""

import json
from datetime import datetime, timezone

import pytest
from test_epw import synthetic
from test_future import signal

from openepw.availability import (
    AvailabilityEntry,
    CatalogBundle,
    CatalogSnapshotRef,
    EvidenceRef,
    FutureAvailabilityQuery,
    FutureWindowScope,
    ProductRecord,
)
from openepw.availability.evaluate import evaluate
from openepw.availability.store import CatalogView
from openepw.config import RuntimeConfig
from openepw.epw import write_epw
from openepw.jobs.worker import JobRunner
from openepw.models import FutureRequest, Location, OpenEPWError, WeatherPlan
from openepw.service import WeatherService


def _request(tmp_path, service, baseline=None):
    file = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), file)
    baseline_ref = service.register_baseline(file)
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps([signal().model_dump(mode="json")]))
    return FutureRequest(baseline=baseline or baseline_ref.id, signals=str(signals),
                         reference_period=(1985, 2014), target_year=2050,
                         climate_scenario="ssp245"), baseline_ref


def test_stored_future_plan_survives_service_restart_and_hash_job_submit(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    request, _ = _request(tmp_path, service)
    plan = service.plan_future(request)
    assert plan.request.climate_period == (2036, 2065)
    assert plan.request.reference_period == (1985, 2014)
    assert plan.request.climate_scenario == "ssp245"
    restarted = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    stored = restarted.plan_store.get(plan.plan_hash)
    assert stored.model_dump(mode="json") == plan.model_dump(mode="json")
    runner = JobRunner(restarted)
    runner.enqueue = lambda _: None
    job = runner.submit(plan.plan_hash)
    assert job.kind == "future" and job.plan_hash == plan.plan_hash
    runner.close()


def test_legacy_future_plan_without_baseline_link_remains_executable(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    request, _ = _request(tmp_path, service)
    modern = service.plan_future(request)
    raw = modern.model_dump(mode="json", exclude={"plan_hash", "baseline_ref"})
    legacy = WeatherPlan.model_validate(raw)
    assert legacy.baseline_ref is None
    service.plan_store.put(legacy)
    stored = service.plan_store.get(legacy.plan_hash)
    assert len(service.execute(stored).weather) == 1


def test_equivalent_baseline_bytes_retain_distinct_origins(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    request, user = _request(tmp_path, service)
    bundle_id = "d" * 32
    fetched = service.artifacts.write(bundle_id, "fetched.epw",
                                      (tmp_path / "baseline.epw").read_bytes(), "weather")
    service.artifacts.json(bundle_id, "manifest.json", {
        "outputs": [{"artifact_id": fetched.id, "output_id": "e" * 64,
                     "lineage": {}}]}, "manifest")
    service.artifacts.json(bundle_id, "qc.json", [], "qc")
    uploaded_plan = service.plan_future(request)
    fetched_plan = service.plan_future(request.model_copy(update={"baseline": fetched.id}))
    assert uploaded_plan.baseline_ref.sha256 == fetched_plan.baseline_ref.sha256
    assert uploaded_plan.baseline_ref.origin == "user_provided"
    assert fetched_plan.baseline_ref.origin == "weather_output"
    assert uploaded_plan.baseline_ref.artifact_id == user.id
    assert fetched_plan.baseline_ref.artifact_id == fetched.id
    assert uploaded_plan.outputs[0].id != fetched_plan.outputs[0].id


@pytest.mark.parametrize("method,scenario", [("morph", "rcp85"),
                                                ("climate_profile", "ssp245")])
def test_method_and_scenario_conflicts_fail_before_job(tmp_path, method, scenario):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    request, _ = _request(tmp_path, service)
    invalid = request.model_copy(update={"method": method,
                                         "climate_scenario": scenario})
    with pytest.raises(OpenEPWError, match="UNSUPPORTED_FUTURE_METHOD|INVALID_SCENARIO_PERIOD"):
        service.plan_future(invalid)


def test_allowed_model_license_keeps_unverified_window_unknown():
    checked = datetime.now(timezone.utc)
    product = ProductRecord(id="cmip6:model", provider="cmip6", dataset="monthly",
                            temporal_kind="future_window", license_effective="CC BY 4.0",
                            license_original="CC BY-SA 4.0", evidence_ids=["registry"])
    bundle = CatalogBundle(
        evidence=[EvidenceRef(id="registry", sha256="a" * 64,
                              retrieved_at=checked, basis="inventory")],
        products=[product],
        entries=[AvailabilityEntry(id="combination", product_id=product.id,
                                   scope=FutureWindowScope(scenario="ssp245",
                                                           model="ACCESS-CM2",
                                                           member="r1i1p1f1"),
                                   evidence_basis="inventory", evidence_ids=["registry"])],
    )
    view = CatalogView(CatalogSnapshotRef(generation_id="synthetic",
                                          created_at=checked), bundle)
    result = evaluate(FutureAvailabilityQuery(
        location=Location(lat=42, lon=-76), method="morph", scenario="ssp245",
        climate_period=(2036, 2065), reference_period=(1985, 2014),
        model="ACCESS-CM2", member="r1i1p1f1"), view)
    option = result.options[0]
    assert option.product.license_effective == "CC BY 4.0"
    assert option.product.license_original == "CC BY-SA 4.0"
    assert option.eligibility.status == "unknown"
    assert "REFERENCE_WINDOW_UNVERIFIED" in option.eligibility.unknowns
