import json
import uuid
from pathlib import Path

from ..epw import read_epw
from ..models import (
    FetchTask,
    FutureRequest,
    OpenEPWError,
    OutputSpec,
    SourceRef,
    WeatherPlan,
    digest,
)


def snapshot(service, value, role):
    if len(value) == 32 and value.isalnum():
        return service.artifacts.resolve(value)
    path = Path(value)
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise OpenEPWError("INVALID_BASELINE", "Baseline/signal file missing or exceeds 5 MB")
    body = path.read_bytes()
    ref = service.artifacts.write(
        uuid.uuid4().hex,
        "baseline.epw" if role == "baseline" else "signals.json",
        body,
        role,
        "application/vnd.energyplus.epw" if role == "baseline" else "application/json",
    )
    return ref, service.config.data_root / ref.path


def plan_future(service, request: FutureRequest):
    from ..generation.cmip6 import CMIP6Backend
    from ..generation.morph import MonthlySignal

    if request.profile == "sampled":
        raise OpenEPWError(
            "UNSUPPORTED_FUTURE_METHOD",
            "Sampled weather is reserved experimental capability in v0.1",
        )
    baseline_ref, path = snapshot(service, request.baseline, "baseline")
    baseline = read_epw(path)
    raw_request = request.model_dump(mode="json")
    raw_request["baseline"] = baseline_ref.id
    params = {"baseline_sha256": baseline_ref.sha256}
    warnings = [
        "Future outputs represent climate windows, not forecasts",
        "Review QC before simulation; unchanged variables remain explicit",
    ]
    estimate = None
    count = 1
    if request.method == "morph":
        if not request.reference_period:
            raise OpenEPWError(
                "INVALID_BASELINE",
                "Specify reliable reference_period; mixed TMY row years are not a reference climate",
            )
        if not request.climate_scenario.startswith("ssp") or request.extreme.get(
            "mode", "warming"
        ) not in ("warming", "sensitivity"):
            raise OpenEPWError(
                "UNSUPPORTED_FUTURE_METHOD",
                "Monthly morphing supports SSP climate signals and warming sensitivity, not hourly shock/persistence",
            )
        if request.signals:
            signal_ref, signal_path = snapshot(service, request.signals, "signals")
            try:
                records = json.loads(signal_path.read_bytes())
                signals = [MonthlySignal.model_validate(s) for s in records]
            except (ValueError, TypeError):
                raise OpenEPWError(
                    "INVALID_CLIMATE_SIGNAL", "Invalid monthly signal JSON"
                ) from None
            if not signals or any(
                s.scenario != request.climate_scenario
                or s.reference_period != request.reference_period
                or s.climate_period != request.climate_period
                for s in signals
            ):
                raise OpenEPWError(
                    "INVALID_SCENARIO_PERIOD", "Local signal scenario/windows do not match request"
                )
            if request.profile == "extreme" and any(s.profile_year is None for s in signals):
                raise OpenEPWError(
                    "INVALID_CLIMATE_SIGNAL",
                    "Extreme local signals must identify the ranked model year",
                )
            if request.profile == "typical" and len(signals) != 1:
                raise OpenEPWError(
                    "INVALID_CLIMATE_SIGNAL", "Typical profile requires exactly one coherent signal"
                )
            params["signals_sha256"] = signal_ref.sha256
            raw_request["signals"] = signal_ref.id
            count = len(signals)
        else:
            backend = CMIP6Backend(service.http)
            pairs = backend.select(request)
            estimate = backend.estimate(pairs, request)
            if estimate > service.config.max_climate_bytes:
                raise OpenEPWError(
                    "RESOURCE_LIMIT",
                    f"Conservative CMIP6 decoded-byte estimate {estimate} exceeds max_climate_bytes; configure an explicit larger budget",
                )
            params["cmip6_pairs"] = pairs
            count = len(pairs)
            warnings.append(
                f"Conservative source decoded-byte estimate: {estimate}; compressed transfer usually smaller; point access still reads spatial chunks"
            )
    else:
        from ..generation.hourly_archive import HourlyArchive

        info = HourlyArchive(service.http).plan(request, baseline.location)
        params.update(info)
        count = 10 if request.profile == "ensemble" else 1
        warnings.extend(info["warnings"])
    normalized = FutureRequest.model_validate(raw_request)
    key = digest({"request": normalized.model_dump(mode="json"), "parameters": params})
    task = FetchTask(
        id=key[:20],
        source=SourceRef(
            provider=request.method, dataset="future climate", license="See per-variable sources"
        ),
        parameters=params,
        cache_key=key,
    )
    outputs = [
        OutputSpec(
            requested_location_id=baseline.location.key,
            task_ids=[task.id],
            name=f"future-{key[:16]}-{i}.epw",
        )
        for i in range(count)
    ]
    return WeatherPlan(
        kind="future",
        request=normalized,
        tasks=[task],
        outputs=outputs,
        warnings=warnings,
        estimated_calls=0 if request.signals else 14 * count if request.method == "morph" else 25,
        estimated_bytes=estimate,
    )


def execute_future(service, plan, *, cancelled, progress):
    from ..epw.writer import epw_bytes
    from ..generation.cmip6 import CMIP6Backend
    from ..generation.morph import MonthlySignal, morph
    from ..qc import validate

    request = plan.request
    params = plan.tasks[0].parameters
    ref, path = service.artifacts.resolve(request.baseline)
    if ref.sha256 != params["baseline_sha256"]:
        raise OpenEPWError("PLAN_STALE", "Baseline changed since planning")
    baseline = read_epw(path)
    if cancelled():
        raise OpenEPWError("CANCELLED", "Future execution cancelled")
    if request.method == "morph":
        if request.signals:
            sig_ref, sig_path = service.artifacts.resolve(request.signals)
            if sig_ref.sha256 != params["signals_sha256"]:
                raise OpenEPWError("PLAN_STALE", "Signals changed since planning")
            signals = [MonthlySignal.model_validate(s) for s in json.loads(sig_path.read_bytes())]
        else:
            signals = CMIP6Backend(service.http).signals(
                params["cmip6_pairs"], request, baseline.location
            )
        datasets = [morph(baseline, s) for s in signals]
    else:
        from ..generation.hourly_archive import HourlyArchive

        datasets = HourlyArchive(service.http).generate(request, params, baseline)
    bundle_id = uuid.uuid4().hex
    weather = []
    manifests = []
    issues = []
    qc = []
    for i, data in enumerate(datasets):
        if cancelled():
            raise OpenEPWError("CANCELLED", "Future execution cancelled")
        checks = validate(data, "annual")
        if any(x.severity == "error" for x in checks):
            raise OpenEPWError("EPW_CONVERSION_FAILED", "Future output failed structural annual QC")
        ref = service.artifacts.write(
            bundle_id,
            plan.outputs[i].name,
            epw_bytes(data),
            "weather",
            "application/vnd.energyplus.epw",
        )
        weather.append(ref)
        manifests.append(
            {
                "artifact_id": ref.id,
                "lineage": {k: v.model_dump(mode="json") for k, v in data.lineage.items()},
                "metadata": data.metadata,
                "baseline_sha256": params["baseline_sha256"],
                "profile": request.profile,
                "climate_period": request.climate_period,
                "reference_period": request.reference_period,
                "scenario": request.climate_scenario,
            }
        )
        issues.extend(checks)
        qc.append({"artifact_id": ref.id, "issues": [x.model_dump() for x in checks]})
        progress(ref.id, None)
    return service._bundle(plan, bundle_id, weather, [], issues, manifests, qc)
