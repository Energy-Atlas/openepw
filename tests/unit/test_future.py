import numpy as np
import pytest
from test_epw import synthetic

from openepw.generation.morph import MonthlySignal, morph
from openepw.models import OpenEPWError


def signal(**kwargs):
    return MonthlySignal(
        model="synthetic-model",
        member="r1",
        scenario="ssp245",
        reference_period=(1985, 2014),
        climate_period=(2036, 2065),
        license="synthetic test data",
        source_uri="synthetic://test",
        source_checksums=["0" * 64],
        temperature_delta=[0.0] * 12,
        **kwargs,
    )


def test_identity_and_two_degree_shift():
    base = synthetic(2023, 8760)
    result = morph(base, signal())
    assert np.allclose(result.data.dry_bulb, base.data.dry_bulb)
    assert np.allclose(result.data.dew_point, base.data.dew_point)
    sig = signal()
    sig.temperature_delta = [2.0] * 12
    result = morph(base, sig)
    assert result.data.groupby(result.data.index.month).dry_bulb.mean().tolist() == [22.0] * 12
    assert (result.data.dew_point <= result.data.dry_bulb).all()
    assert not np.allclose(result.data.dew_point, base.data.dew_point)


def test_dtr_zero_warns_and_solar_scaling_conserves_ratio():
    base = synthetic(2023, 8760)
    base.data["ghi"] = 100.0
    base.data["dni"] = 50.0
    base.data["dhi"] = 50.0
    result = morph(base, signal(dtr_delta=[1.0] * 12, solar_ratio=[1.2] * 12))
    assert result.data.ghi.sum() == 8760 * 120
    assert result.data.dni.sum() == 8760 * 60
    assert any(i.code == "ZERO_BASELINE_DTR" for i in result.issues)


def test_signal_months_are_validated():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        signal(wind_ratio=[-1.0] * 12)


def test_local_signal_service_bundle_and_scenario_mismatch(tmp_path):
    import json

    from openepw.config import RuntimeConfig
    from openepw.epw import read_epw, write_epw
    from openepw.models import FutureRequest
    from openepw.service import WeatherService

    baseline = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), baseline)
    signals = tmp_path / "signals.json"
    sig = signal()
    sig.temperature_delta = [2.0] * 12
    signals.write_text(json.dumps([sig.model_dump(mode="json")]))
    s = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    r = FutureRequest(
        baseline=str(baseline),
        signals=str(signals),
        reference_period=(1985, 2014),
        target_year=2050,
        climate_scenario="ssp245",
    )
    p = s.plan_future(r)
    b = s.execute(p)
    assert len(b.weather) == 1
    assert read_epw(s.config.data_root / b.weather[0].path).data.dry_bulb.mean() == 22
    bad = r.model_copy(update={"climate_scenario": "ssp585"})
    with pytest.raises(OpenEPWError):
        s.plan_future(bad)


def test_morph_retains_provenance_for_unchanged_native_fields(tmp_path):
    from openepw.epw import read_epw, write_epw

    p = tmp_path / "baseline.epw"
    write_epw(synthetic(2023, 8760), p)
    baseline = read_epw(p)
    result = morph(baseline, signal())
    assert result.lineage["wind_direction"].unchanged
    assert (
        result.lineage["wind_direction"].raw_sha256
        == __import__("hashlib").sha256(p.read_bytes()).hexdigest()
    )
    assert result.metadata["baseline_lineage"]["dry_bulb"]["raw_sha256"]


def test_future_cancellation_preserves_completed_outputs(tmp_path):
    import json

    from openepw.config import RuntimeConfig
    from openepw.epw import write_epw
    from openepw.models import FutureRequest
    from openepw.service import WeatherService

    p = tmp_path / "base.epw"
    write_epw(synthetic(2023, 8760), p)
    signals = tmp_path / "signals.json"
    signals.write_text(
        json.dumps(
            [
                signal().model_dump(mode="json"),
                signal().model_copy(update={"member": "r2"}).model_dump(mode="json"),
            ]
        )
    )
    s = WeatherService(RuntimeConfig(data_root=tmp_path / "store"))
    plan = s.plan_future(
        FutureRequest(
            baseline=str(p),
            signals=str(signals),
            target_year=2050,
            reference_period=(1985, 2014),
            climate_scenario="ssp245",
            profile="ensemble",
        )
    )
    stopped = [False]

    def progress(*args):
        stopped[0] = True

    b = s.execute(plan, cancelled=lambda: stopped[0], progress=progress)
    assert len(b.weather) == 1
    assert any(i.code == "CANCELLED" for i in b.issues)


def test_known_baseline_artifact_keeps_original_variable_sources(tmp_path):
    import json

    from openepw.config import RuntimeConfig
    from openepw.epw.writer import epw_bytes
    from openepw.models import FutureRequest, SourceRef, VariableLineage
    from openepw.service import WeatherService

    s = WeatherService(RuntimeConfig(data_root=tmp_path))
    ref = s.artifacts.write("a" * 32, "source.epw", epw_bytes(synthetic(2023, 8760)), "weather")
    lineage = VariableLineage(
        variable="wind_direction",
        source=SourceRef(provider="station", dataset="known observation"),
        raw_sha256="1" * 64,
    )
    s.artifacts.json(
        "a" * 32,
        "manifest.json",
        {
            "outputs": [
                {
                    "artifact_id": ref.id,
                    "lineage": {"wind_direction": lineage.model_dump(mode="json")},
                }
            ]
        },
        "manifest",
    )
    signals = tmp_path / "signals.json"
    signals.write_text(json.dumps([signal().model_dump(mode="json")]))
    p = s.plan_future(
        FutureRequest(
            baseline=ref.id,
            signals=str(signals),
            target_year=2050,
            reference_period=(1985, 2014),
            climate_scenario="ssp245",
        )
    )
    b = s.execute(p)
    output = json.loads((tmp_path / b.manifest.path).read_text())["outputs"][0]
    assert output["lineage"]["wind_direction"]["source"]["provider"] == "station"
