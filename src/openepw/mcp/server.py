"""Local MCP adapter over the shared service, job and artifact stores."""

from __future__ import annotations

import base64
import binascii
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import TypeAdapter, ValidationError

from ..availability import AvailabilityQuery
from ..epw import read_epw
from ..jobs.worker import JobRunner
from ..models import FutureRequest, OpenEPWError, WeatherPlan, WeatherRequest
from ..qc import validate
from ..service import WeatherService

MAX_UPLOAD = 5_000_000
MAX_RESOURCE = 10_000_000
MAX_RESULT = 160_000


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _bounded(value: Any) -> Any:
    result = _json(value)
    if len(json.dumps(result, allow_nan=False)) > MAX_RESULT:
        raise OpenEPWError("RESOURCE_LIMIT", "Result is too large; narrow the request")
    return result


def _plan_summary(plan: WeatherPlan) -> dict[str, Any]:
    request = plan.request.model_dump(mode="json")
    if plan.kind == "weather":
        request = {key: request.get(key) for key in (
            "product", "years", "start", "end", "missing_policy", "dataset_selections"
        )}
    return _bounded({
        "plan_hash": plan.plan_hash, "kind": plan.kind, "request": request,
        "baseline_ref": _json(plan.baseline_ref) if plan.baseline_ref else None,
        "outputs": [{"id": row.id, "name": row.name,
                     "occurrence_index": row.occurrence_index,
                     "requested_location_id": row.requested_location_id}
                    for row in plan.outputs[:50]],
        "output_count": len(plan.outputs),
        "batch_rows": [row.model_dump(mode="json") for row in plan.batch_rows[:50]],
        "batch_row_count": len(plan.batch_rows),
        "issues": [issue.model_dump(mode="json") for issue in plan.issues[:50]],
        "warnings": plan.warnings[:50],
        "estimated_calls": plan.estimated_calls,
        "estimated_bytes": plan.estimated_bytes,
        "truncated": len(plan.outputs) > 50 or len(plan.batch_rows) > 50,
    })


def _job_summary(job: Any) -> dict[str, Any]:
    raw = job.model_dump(mode="json")
    bundle = raw.pop("bundle", None)
    raw["error_count"] = len(raw["errors"])
    raw["errors"] = raw["errors"][:50]
    if bundle:
        raw["artifacts"] = {
            "weather": [item["id"] for item in bundle["weather"][:50]],
            "weather_count": len(bundle["weather"]),
            **{name: bundle[name]["id"] for name in ("request", "plan", "manifest", "qc")},
            "additional": [item["id"] for item in bundle["additional"][:50]],
        }
    return _bounded(raw)


def create_server(service=None, *, allowed_roots: list[str | Path] | None = None):
    service = service or WeatherService()
    roots = [Path(root).resolve() for root in (allowed_roots or [])]
    runner = JobRunner(service)

    @asynccontextmanager
    async def lifespan(server):
        runner.recover()
        yield {"runner": runner}
        runner.close()

    server = FastMCP(
        "openepw", host="127.0.0.1", port=8001, lifespan=lifespan,
        instructions=("Inspect availability before planning. Supported means eligible "
                      "to try, not quality assured. Inspect QC before simulation. "
                      "Submit stored plan hashes. Keep EPW bytes outside prompts."),
    )

    def call(function, *args, **kwargs):
        try:
            return _bounded(function(*args, **kwargs))
        except OpenEPWError as exc:
            raise ToolError(json.dumps(exc.issue.model_dump(mode="json"))) from None
        except (ValidationError, ValueError, TypeError):
            raise ToolError(json.dumps({"code": "INVALID_REQUEST",
                                        "message": "Request schema validation failed",
                                        "retryable": False})) from None
        except Exception:
            raise ToolError(json.dumps({"code": "INTERNAL_ERROR",
                                        "message": "Local operation failed",
                                        "retryable": False})) from None

    def weather_request(raw):
        request = WeatherRequest.model_validate(raw)
        if isinstance(request.locations, list) and len(request.locations) > 50:
            raise OpenEPWError("RESOURCE_LIMIT", "MCP request exceeds 50 locations")
        return request

    def safe_future(raw):
        request = FutureRequest.model_validate(raw)
        service.artifacts.resolve(request.baseline)
        if request.signals:
            service.artifacts.resolve(request.signals)
        return request

    def submit(plan_hash, kind, idempotency_key):
        plan = service.plan_store.get(plan_hash)
        if plan.kind != kind:
            raise OpenEPWError("INVALID_REQUEST", "Plan kind does not match submit tool")
        if kind == "future":
            safe_future(plan.request.model_dump(mode="json"))
        return _job_summary(runner.submit(plan, idempotency_key))

    @server.tool(structured_output=True)
    def weather_geocode(query: str, mode: str = "point") -> dict[str, Any]:
        """Resolve a short place name; ambiguous names require explicit selection."""
        def action():
            if not query.strip() or len(query) > 150:
                raise OpenEPWError("INVALID_REQUEST", "Place name must be 1–150 characters")
            return service.geocode(query, mode=mode)
        return call(action)

    @server.tool(structured_output=True)
    def weather_assess(query: dict) -> dict[str, Any]:
        """Compare catalog eligibility, evidence dates and unknowns without retrieval."""
        return call(lambda: service.assess_availability(
            TypeAdapter(AvailabilityQuery).validate_python(query)))

    @server.tool(structured_output=True)
    def weather_discover(request: dict) -> dict[str, Any]:
        """Discover alternatives; source support means retrieval eligibility only."""
        return call(lambda: service.discover(weather_request(request)))

    @server.tool(structured_output=True)
    def weather_plan(request: dict, kind: str = "weather") -> dict[str, Any]:
        """Store a weather plan; return hash, occurrence rows and estimates."""
        def action():
            if kind == "future":  # v0.1 compatibility
                return _plan_summary(service.plan_future(safe_future(request)))
            if kind != "weather":
                raise OpenEPWError("INVALID_REQUEST", "Unknown plan kind")
            return _plan_summary(service.plan(weather_request(request)))
        return call(action)

    @server.tool(structured_output=True)
    def future_plan(request: dict) -> dict[str, Any]:
        """Store a future plan from a registered baseline ID and explicit climate windows."""
        return call(lambda: _plan_summary(service.plan_future(safe_future(request))))

    @server.tool(structured_output=True)
    def plan_inspect(plan_hash: str, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Inspect stored plan choices and paged occurrence/output rows by hash."""
        def action():
            if offset < 0 or not 1 <= limit <= 50:
                raise OpenEPWError("INVALID_REQUEST", "Invalid plan page")
            plan = service.plan_store.get(plan_hash)
            return {
                **_plan_summary(plan),
                "outputs": [row.model_dump(mode="json")
                            for row in plan.outputs[offset:offset + limit]],
                "batch_rows": [row.model_dump(mode="json")
                               for row in plan.batch_rows[offset:offset + limit]],
                "selected_candidates": [
                    {"id": candidate.id, "source": candidate.source.model_dump(mode="json"),
                     "product_id": candidate.product_id,
                     "selection_reasons": candidate.selection_reasons}
                    for candidate in plan.selected_candidates[offset:offset + limit]
                ],
                "offset": offset, "limit": limit,
            }
        return call(action)

    @server.tool(structured_output=True)
    def baseline_upload(content_base64: str, filename: str | None = None) -> dict[str, Any]:
        """Register a user EPW; client encodes bytes outside model context (5 MB maximum)."""
        def action():
            if len(content_base64) > 6_666_672:
                raise OpenEPWError("RESOURCE_LIMIT", "Baseline upload exceeds 5 MB")
            try:
                body = base64.b64decode(content_base64, validate=True)
            except (ValueError, binascii.Error):
                raise OpenEPWError("INVALID_BASELINE", "Invalid base64 EPW content") from None
            if not body or len(body) > MAX_UPLOAD:
                raise OpenEPWError("RESOURCE_LIMIT", "Baseline upload exceeds 5 MB")
            data = read_epw(body)
            ref = service.register_baseline(body)
            return {"artifact_id": ref.id, "sha256": ref.sha256, "bytes": ref.bytes,
                    "rows": len(data.data), "input_qc": [i.model_dump(mode="json")
                    for i in validate(data)[:20]],
                    "filename": Path(filename).name if filename else None}
        return call(action)

    @server.tool(structured_output=True)
    def baseline_register_path(path: str) -> dict[str, Any]:
        """Register a local EPW under a configured allowed root (5 MB maximum)."""
        def action():
            target = Path(path).resolve()
            if not any(target.is_relative_to(root) for root in roots):
                raise OpenEPWError("ACCESS_DENIED", "Path is outside allowed local roots")
            if not target.is_file() or target.stat().st_size > MAX_UPLOAD:
                raise OpenEPWError("INVALID_BASELINE", "Baseline path missing or too large")
            data = read_epw(target)
            ref = service.register_baseline(target)
            return {"artifact_id": ref.id, "sha256": ref.sha256, "bytes": ref.bytes,
                    "rows": len(data.data), "input_qc": [i.model_dump(mode="json")
                    for i in validate(data)[:20]]}
        return call(action)

    @server.tool(structured_output=True)
    def weather_submit(plan_hash: str, idempotency_key: str | None = None) -> dict[str, Any]:
        """Submit an inspected weather plan; retrieval may yield gaps or partial failure."""
        return call(submit, plan_hash, "weather", idempotency_key)

    @server.tool(structured_output=True)
    def future_submit(plan_hash: str, idempotency_key: str | None = None) -> dict[str, Any]:
        """Submit an inspected future plan using its verified baseline ID."""
        return call(submit, plan_hash, "future", idempotency_key)

    @server.tool(structured_output=True)
    def job_inspect(job_id: str) -> dict[str, Any]:
        """Inspect durable state, per-output counts, error codes and artifact IDs."""
        def action():
            job = runner.store.get(job_id)
            result = _job_summary(job)
            result["completed_output_ids"] = list(runner.store.items(job_id))[:50]
            if job.bundle:
                _, path = service.artifacts.resolve(job.bundle.manifest.id)
                manifest = json.loads(path.read_text(encoding="utf-8"))
                result["batch_rows"] = [
                    {"occurrence_index": row.get("occurrence_index"),
                     "output_id": row.get("output_id"), "status": row.get("status"),
                     "issue_codes": row.get("issue_codes", [])}
                    for row in manifest.get("batch_rows", [])[:50]
                ]
                result["future_rows"] = [
                    {"output_id": row.get("output_id"), "status": row.get("status"),
                     "issue_codes": row.get("issue_codes", [])}
                    for row in manifest.get("future_rows", [])[:50]
                ]
            return result
        return call(action)

    @server.tool(structured_output=True)
    def job_cancel(job_id: str) -> dict[str, Any]:
        """Request cancellation; completed artifacts remain available."""
        return call(lambda: _job_summary(runner.store.cancel(job_id)))

    @server.tool(structured_output=True)
    def job_retry_failed(job_id: str, idempotency_key: str | None = None) -> dict[str, Any]:
        """Retry only missing or failed outputs of a finished job."""
        return call(lambda: _job_summary(runner.retry_failed(job_id, idempotency_key)))

    @server.tool(structured_output=True)
    def artifact_inspect(artifact_id: str) -> dict[str, Any]:
        """Verify checksum and inspect bounded metadata; read bytes by resource URI."""
        def action():
            ref, path = service.artifacts.resolve(artifact_id)
            result = {"artifact_id": ref.id, "role": ref.role, "media_type": ref.media_type,
                      "bytes": ref.bytes, "sha256": ref.sha256,
                      "uri": "weather://artifacts/" + ref.id,
                      "registration_route": ref.registration_route}
            def summarize_json(item_ref, item_path):
                if item_ref.bytes > 1_000_000:
                    return {"summary_truncated": True}
                value = json.loads(item_path.read_text(encoding="utf-8"))
                if item_ref.role == "manifest" and isinstance(value, dict):
                    return {
                        "simulation_ready": value.get("simulation_ready"),
                        "batch_rows": [{"occurrence_index": row.get("occurrence_index"),
                                        "status": row.get("status"),
                                        "issue_codes": row.get("issue_codes", [])}
                                       for row in value.get("batch_rows", [])[:50]],
                        "output_count": len(value.get("outputs", [])),
                    }
                if item_ref.role == "qc" and isinstance(value, list):
                    return {"qc_issue_codes": sorted({
                        issue["code"] for row in value[:50]
                        for issue in row.get("issues", []) if "code" in issue
                    })}
                return {}
            if ref.role in ("manifest", "qc"):
                result.update(summarize_json(ref, path))
            if ref.role == "weather":
                try:
                    manifest = service.artifacts.sibling(ref, "manifest.json", "manifest")
                    qc = service.artifacts.sibling(ref, "qc.json", "qc")
                    result.update({"manifest_artifact_id": manifest.id,
                                   "qc_artifact_id": qc.id})
                    _, manifest_path = service.artifacts.resolve(manifest.id)
                    _, qc_path = service.artifacts.resolve(qc.id)
                    result.update(summarize_json(manifest, manifest_path))
                    result.update(summarize_json(qc, qc_path))
                except OpenEPWError:
                    pass
            return result
        return call(action)

    @server.tool(structured_output=True)
    def weather_export_compact(job_id: str) -> dict[str, Any]:
        """Create a checksummed compact ZIP; inspect mapping and QC first."""
        def action():
            ref = runner.export_compact(job_id)
            return {"artifact_id": ref.id, "bytes": ref.bytes, "sha256": ref.sha256,
                    "uri": "weather://artifacts/" + ref.id}
        return call(action)

    # v0.1 aliases remain available during migration.
    @server.tool(structured_output=True)
    def weather_fetch(plan: dict, idempotency_key: str | None = None) -> dict[str, Any]:
        """Compatibility alias for inline weather plan submission. Prefer weather_submit."""
        def action():
            selected = WeatherPlan.model_validate(plan)
            if selected.kind != "weather":
                raise OpenEPWError("INVALID_REQUEST", "Expected a weather plan")
            return _job_summary(runner.submit(selected, idempotency_key))
        return call(action)

    @server.tool(structured_output=True)
    def weather_inspect(job_id: str | None = None, artifact_id: str | None = None) -> dict[str, Any]:
        """Compatibility alias for inspecting a job or artifact ID."""
        if job_id:
            return job_inspect(job_id)
        if artifact_id:
            return artifact_inspect(artifact_id)
        raise ToolError(json.dumps({"code": "INVALID_REQUEST",
                                    "message": "Provide job_id or artifact_id"}))

    @server.tool(structured_output=True)
    def weather_generate_future(
        request: dict | None = None, plan: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility alias for inline future submission. Prefer future_submit."""
        def action():
            if (request is None) == (plan is None):
                raise OpenEPWError("INVALID_REQUEST", "Provide request or plan")
            selected = (WeatherPlan.model_validate(plan) if plan
                        else service.plan_future(safe_future(request)))
            if selected.kind != "future":
                raise OpenEPWError("INVALID_REQUEST", "Expected a future plan")
            safe_future(selected.request.model_dump(mode="json"))
            return _job_summary(runner.submit(selected, idempotency_key))
        return call(action)

    @server.resource("weather://artifacts/{artifact_id}")
    def artifact(artifact_id: str) -> bytes:
        """Read checksum-verified EPW, manifest, QC or export bytes by opaque ID."""
        try:
            ref, path = service.artifacts.resolve(artifact_id)
            if ref.bytes > MAX_RESOURCE:
                raise ValueError("Artifact exceeds MCP resource limit")
            return path.read_bytes()
        except (OpenEPWError, OSError, ValueError):
            raise ValueError("Artifact unavailable or exceeds resource limit") from None

    return server
