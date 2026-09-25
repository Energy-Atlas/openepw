import json
import uuid
from pathlib import Path

from ..epw import read_epw
from ..models import (
    BaselineRef,
    FetchTask,
    FutureRequest,
    Issue,
    OpenEPWError,
    OutputSpec,
    SourceRef,
    VariableLineage,
    WeatherPlan,
    digest,
)
from ..qc import validate
from .output_identity import filename, location_label, output_id


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


def resolve_baseline(service, value):
    ref, path = snapshot(service, value, "baseline")
    if ref.role not in ("baseline", "weather"):
        raise OpenEPWError("INVALID_BASELINE", "Artifact is not a weather baseline")
    try:
        baseline = read_epw(path)
    except OpenEPWError:
        raise OpenEPWError("INVALID_BASELINE", "Baseline EPW is not readable") from None
    checks = validate(baseline, "annual")
    missing = sorted({issue.field or "unknown" for issue in checks
                      if issue.code == "MISSING_CRITICAL_VARIABLE"})
    if missing:
        raise OpenEPWError("MISSING_CRITICAL_VARIABLE",
                           "Baseline lacks required hourly values: " + ", ".join(missing))
    if any(issue.severity == "error" for issue in checks):
        codes = sorted({issue.code for issue in checks if issue.severity == "error"})
        raise OpenEPWError("INVALID_BASELINE", "Baseline annual QC failed: " +
                           ", ".join(codes))
    related = BaselineRef(artifact_id=ref.id, sha256=ref.sha256,
                          origin="weather_output" if ref.role == "weather"
                          else "user_provided", input_qc=checks,
                          registration_route=ref.registration_route)
    params = {"baseline_sha256": ref.sha256}
    if ref.role == "weather":
        manifest_ref = service.artifacts.sibling(ref, "manifest.json", "manifest")
        qc_ref = service.artifacts.sibling(ref, "qc.json", "qc")
        _, manifest_path = service.artifacts.resolve(manifest_ref.id)
        try:
            prior = json.loads(manifest_path.read_bytes())
        except ValueError:
            raise OpenEPWError("INVALID_BASELINE", "Input manifest is malformed") from None
        linked = next((item for item in prior.get("outputs", [])
                       if item.get("artifact_id") == ref.id), None)
        if linked is None:
            raise OpenEPWError("INVALID_BASELINE", "Input manifest does not describe baseline")
        related.source_output_id = linked.get("output_id")
        related.source_manifest_id = manifest_ref.id
        related.source_qc_id = qc_ref.id
        params.update(baseline_manifest_id=manifest_ref.id,
                      baseline_manifest_sha256=manifest_ref.sha256,
                      baseline_qc_id=qc_ref.id, baseline_qc_sha256=qc_ref.sha256)
    return ref, path, baseline, related, params


def plan_future(service, request: FutureRequest):
    from ..generation.cmip6 import CMIP6Backend
    from ..generation.morph import MonthlySignal

    if request.profile == "sampled":
        raise OpenEPWError(
            "UNSUPPORTED_FUTURE_METHOD",
            "Sampled weather is reserved experimental capability in v0.1",
        )
    baseline_ref, path, baseline, baseline_link, params = resolve_baseline(
        service, request.baseline)
    raw_request = request.model_dump(mode="json")
    raw_request["baseline"] = baseline_ref.id
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
            if (request.models and set(request.models) != {s.model for s in signals}) or (
                request.members and set(request.members) != {s.member for s in signals}
            ):
                raise OpenEPWError(
                    "INVALID_CLIMATE_SIGNAL",
                    "Local signal model/member selectors do not match records",
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
    outputs = []
    assert request.climate_period is not None
    # Storage artifact handles are random snapshots; output content identity is not.
    scientific_request = normalized.model_dump(mode="json", exclude={"baseline", "signals"})
    scientific_params = {k: v for k, v in params.items()
                         if k not in ("baseline_manifest_id", "baseline_qc_id")}
    for i in range(count):
        member = (
            signals[i].member
            if request.method == "morph" and request.signals
            else f"member-{i + 1}"
        )
        identity = output_id(
            {
                "kind": "future",
                "location_id": baseline.location.key,
                "request": scientific_request,
                "parameters": scientific_params,
                "method": request.method,
                "scenario": request.climate_scenario,
                "profile": request.profile,
                "window": request.climate_period,
                "member": member,
                "index": i,
            }
        )
        outputs.append(
            OutputSpec(
                id=identity,
                index=i,
                requested_location_id=baseline.location.key,
                task_ids=[task.id],
                name=filename(
                    [
                        location_label(baseline.location),
                        request.method,
                        request.climate_scenario,
                        request.profile,
                        f"{request.climate_period[0]}-{request.climate_period[1]}",
                        member,
                    ],
                    identity,
                ),
            )
        )
    return WeatherPlan(
        kind="future",
        request=normalized,
        tasks=[task],
        outputs=outputs,
        baseline_ref=baseline_link,
        warnings=warnings,
        estimated_calls=0 if request.signals else 14 * count if request.method == "morph" else 25,
        estimated_bytes=estimate,
    )


def execute_future(service, plan, *, cancelled, progress, source_results=None):
    from ..epw.writer import epw_bytes
    from ..generation.cmip6 import CMIP6Backend
    from ..generation.morph import MonthlySignal, morph
    from ..qc import validate

    request = plan.request
    if len(plan.tasks) != 1:
        raise OpenEPWError("INVALID_REQUEST", "Future plans require one coherent source task")
    params = plan.tasks[0].parameters
    expected = digest({"request": request.model_dump(mode="json"), "parameters": params})
    if plan.tasks[0].cache_key != expected or plan.tasks[0].id != expected[:20]:
        raise OpenEPWError("PLAN_STALE", "Future task identity does not match its request")
    ref, path = service.artifacts.resolve(request.baseline)
    if ref.sha256 != params["baseline_sha256"]:
        raise OpenEPWError("PLAN_STALE", "Baseline changed since planning")
    baseline = read_epw(path)
    if plan.baseline_ref is not None:
        if (plan.baseline_ref.artifact_id != ref.id or
                plan.baseline_ref.sha256 != ref.sha256):
            raise OpenEPWError("PLAN_STALE", "Baseline reference changed since planning")
        preflight = validate(baseline, "annual")
        missing = sorted({issue.field or "unknown" for issue in preflight
                          if issue.code == "MISSING_CRITICAL_VARIABLE"})
        if missing:
            raise OpenEPWError("MISSING_CRITICAL_VARIABLE",
                               "Baseline lacks required hourly values: " +
                               ", ".join(missing))
        if any(issue.severity == "error" for issue in preflight):
            codes = sorted({issue.code for issue in preflight if issue.severity == "error"})
            raise OpenEPWError("INVALID_BASELINE", "Baseline annual QC failed: " +
                               ", ".join(codes))
    if params.get("baseline_manifest_id"):
        manifest_ref, manifest_path = service.artifacts.resolve(params["baseline_manifest_id"])
        if manifest_ref.sha256 != params["baseline_manifest_sha256"]:
            raise OpenEPWError("PLAN_STALE", "Baseline provenance changed")
        prior = json.loads(manifest_path.read_bytes())
        linked = next((o for o in prior.get("outputs", []) if o.get("artifact_id") == ref.id), None)
        if linked is None:
            raise OpenEPWError("INVALID_BASELINE", "Input manifest does not describe this baseline")
        baseline.lineage.update(
            {k: VariableLineage.model_validate(v) for k, v in linked.get("lineage", {}).items()}
        )
    if params.get("baseline_qc_id"):
        qc_ref, _ = service.artifacts.resolve(params["baseline_qc_id"])
        if qc_ref.sha256 != params["baseline_qc_sha256"]:
            raise OpenEPWError("PLAN_STALE", "Baseline QC changed")
    if cancelled():
        raise OpenEPWError("CANCELLED", "Future execution cancelled")
    source_results = source_results if source_results is not None else {}
    task_id = plan.tasks[0].id
    if task_id in source_results:
        source = source_results[task_id]
        if isinstance(source, OpenEPWError):
            raise source
    else:
        try:
            if request.method == "morph":
                if request.signals:
                    sig_ref, sig_path = service.artifacts.resolve(request.signals)
                    if sig_ref.sha256 != params["signals_sha256"]:
                        raise OpenEPWError("PLAN_STALE", "Signals changed since planning")
                    signals = [MonthlySignal.model_validate(s)
                               for s in json.loads(sig_path.read_bytes())]
                    if (
                        not signals
                        or any(
                            s.scenario != request.climate_scenario
                            or s.reference_period != request.reference_period
                            or s.climate_period != request.climate_period
                            or (request.models and s.model not in request.models)
                            or (request.members and s.member not in request.members)
                            or (request.profile == "extreme" and s.profile_year is None)
                            for s in signals
                        )
                        or (request.profile == "typical" and len(signals) != 1)
                    ):
                        raise OpenEPWError("INVALID_CLIMATE_SIGNAL",
                                           "Signals disagree with future request")
                else:
                    signals = CMIP6Backend(service.http).signals(
                        params["cmip6_pairs"], request, baseline.location)
                source = ("morph", signals)
            else:
                from ..generation.hourly_archive import HourlyArchive

                source = ("climate_profile",
                          HourlyArchive(service.http).generate(request, params, baseline))
        except OpenEPWError as exc:
            source_results[task_id] = exc
            raise
        source_results[task_id] = source
    method, members = source
    if any(output.index is None for output in plan.outputs) and len(members) != len(plan.outputs):
        raise OpenEPWError(
            "INVALID_REQUEST", "Future output count does not match coherent source profiles"
        )
    indices = [
        output.index if output.index is not None else i for i, output in enumerate(plan.outputs)
    ]
    if len(set(indices)) != len(indices) or any(i >= len(members) for i in indices):
        raise OpenEPWError("INVALID_REQUEST", "Future output index is invalid")
    bundle_id = uuid.uuid4().hex
    weather = []
    manifests = []
    issues = []
    qc = []
    for output, index in zip(plan.outputs, indices, strict=True):
        identity = output.id or output.name
        if cancelled():
            issues.append(
                Issue(
                    code="CANCELLED",
                    message="Future execution cancelled; completed outputs retained",
                    severity="error",
                )
            )
            break
        try:
            data = morph(baseline, members[index]) if method == "morph" else members[index]
            checks = validate(data, "annual")
            if any(x.code == "MISSING_CRITICAL_VARIABLE" for x in checks):
                raise OpenEPWError("MISSING_CRITICAL_VARIABLE",
                                   "Future output has missing required weather values")
            if any(x.severity == "error" for x in checks):
                raise OpenEPWError("EPW_CONVERSION_FAILED",
                                   "Future output failed structural annual QC")
            ref = service.artifacts.write(
                bundle_id, output.name, epw_bytes(data), "weather",
                "application/vnd.energyplus.epw")
            weather.append(ref)
            manifests.append({
                "artifact_id": ref.id,
                "output_id": output.id,
                "index": output.index,
                "requested_locations": [output.requested_location_id],
                "lineage": {k: v.model_dump(mode="json") for k, v in data.lineage.items()},
                "metadata": data.metadata,
                "method": request.method,
                "model": members[index].model if method == "morph" else None,
                "member": members[index].member if method == "morph" else None,
                "baseline_artifact_id": request.baseline,
                "baseline_origin": plan.baseline_ref.origin if plan.baseline_ref else None,
                "baseline_manifest_id": (plan.baseline_ref.source_manifest_id
                                         if plan.baseline_ref else None),
                "baseline_qc_id": (plan.baseline_ref.source_qc_id
                                   if plan.baseline_ref else None),
                "baseline_sha256": params["baseline_sha256"],
                "profile": request.profile,
                "climate_period": request.climate_period,
                "reference_period": request.reference_period,
                "scenario": request.climate_scenario,
            })
            issues.extend(x.model_copy(update={"task_id": identity}) for x in checks)
            qc.append({"artifact_id": ref.id, "issues": [x.model_dump() for x in checks]})
            progress(identity, None)
        except OpenEPWError as exc:
            issue = exc.issue.model_copy(update={"task_id": identity})
            issues.append(issue)
            progress(identity, issue)
    return service._bundle(plan, bundle_id, weather, [], issues, manifests, qc)
