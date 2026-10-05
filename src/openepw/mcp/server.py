"""Local MCP adapter over the shared service, job and artifact stores."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter, ValidationError

from ..availability import AvailabilityQuery
from ..epw import read_epw
from ..jobs.worker import JobRunner
from ..models import OpenEPWError, WeatherPlan, WeatherRequest
from ..places.models import MAX_PLACES, PlacePreview, PlaceSetQuery
from ..qc import validate
from ..service import WeatherService
from ..visualization import VisualizationRequest
from .approval import confirm_submission
from .descriptions import DESCRIPTIONS, INSTRUCTIONS
from .schemas import (
    AvailabilityQueryArg,
    GeographyArg,
    PlaceSetQueryArg,
    VisualizationRequestArg,
    WeatherRequestArg,
)
from .summaries import summarize

MAX_UPLOAD = 5_000_000
MAX_RESOURCE = 10_000_000
MAX_RESULT = 160_000
logger = logging.getLogger("openepw.mcp")


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _bounded(value: Any) -> Any:
    result = _json(value)
    if len(json.dumps(result, allow_nan=False)) > MAX_RESULT:
        raise OpenEPWError("RESOURCE_LIMIT", "Result is too large; narrow the request")
    return result


def _preview_summary(preview: PlacePreview) -> dict[str, Any]:
    """Compact preview: rows carry the points, so the GeoJSON and location copies are dropped."""
    rows = [row.model_dump(mode="json", exclude_none=True, exclude_defaults=True, exclude={"region"})
            | {"index": row.index, "input": row.input, "status": row.status} for row in preview.rows]
    return {"digest": preview.digest, "count": len(rows), "resolved": len(preview.locations), "rows": rows,
            "issues": [issue.model_dump(mode="json") for issue in preview.issues],
            "attribution": preview.attribution}


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


def validation_details(error: ValidationError) -> list[dict[str, str]]:
    """Field paths and messages only; pydantic messages do not echo the input value."""
    return [{"loc": ".".join(str(part) for part in item["loc"]), "msg": item["msg"]}
            for item in error.errors()[:20]]


def tool_error(exc: Exception) -> ToolError:
    """A safe JSON error for any failure inside a tool."""
    if isinstance(exc, ToolError):
        return exc
    payload: dict[str, Any]
    if isinstance(exc, OpenEPWError):
        payload = exc.issue.model_dump(mode="json")
    elif isinstance(exc, ValidationError):
        payload = {"code": "INVALID_REQUEST", "message": "Request schema validation failed",
                   "retryable": False, "details": validation_details(exc)}
    elif isinstance(exc, (ValueError, TypeError)):
        payload = {"code": "INVALID_REQUEST", "message": "Request schema validation failed",
                   "retryable": False}
    else:
        correlation = uuid.uuid4().hex[:12]
        logger.error("MCP internal error %s: %s", correlation, type(exc).__name__)
        payload = {"code": "INTERNAL_ERROR", "message": "Local operation failed",
                   "retryable": False, "correlation_id": correlation}
    return ToolError(json.dumps(payload))


def respond(name: str, data: Any) -> CallToolResult:
    """Short summary text for model context; bounded full data for renderers."""
    bounded = _bounded(data)
    return CallToolResult(content=[TextContent(type="text", text=summarize(name, bounded))],
                          structuredContent=bounded)


def call(name: str, function: Callable[..., Any], *args: Any) -> CallToolResult:
    try:
        return respond(name, function(*args))
    except Exception as exc:
        raise tool_error(exc) from None


async def acall(name: str, function: Callable[..., Any], *args: Any) -> CallToolResult:
    try:
        return respond(name, await function(*args))
    except Exception as exc:
        raise tool_error(exc) from None


def create_server(service=None, *, allowed_roots: list[str | Path] | None = None,
                  runner: JobRunner | None = None):
    """Build the MCP server; a supplied runner is shared and left to its owner to close.

    The SDK enters the lifespan once per client session, so an owned runner recovers on the
    first session and stays open across sessions; the process closes it at exit through
    ``server.openepw_runner.close()`` (as the ``openepw mcp`` command does).
    """
    service = service or WeatherService()
    roots = [Path(root).resolve() for root in (allowed_roots or [])]
    owns_runner = runner is None
    runner = runner or JobRunner(service)
    recovered = False

    @asynccontextmanager
    async def lifespan(server):
        nonlocal recovered
        if owns_runner and not recovered:
            runner.recover()
            recovered = True
        yield {"runner": runner}

    server = FastMCP("openepw", host="127.0.0.1", port=8001, lifespan=lifespan,
                     instructions=INSTRUCTIONS)
    server.openepw_runner = runner  # type: ignore[attr-defined]

    def tool(function):
        return server.tool(description=DESCRIPTIONS[function.__name__])(function)

    def weather_request(raw):
        request = WeatherRequest.model_validate(raw)
        # Owner decision 2026-09-27: a full place preview (up to MAX_PLACES points) can be planned.
        if isinstance(request.locations, list) and len(request.locations) > MAX_PLACES:
            raise OpenEPWError("RESOURCE_LIMIT", f"MCP request exceeds {MAX_PLACES} locations")
        return request

    async def submit(plan, idempotency_key, ctx):
        if plan.kind == "future":
            raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
        if plan.kind != "weather":
            raise OpenEPWError("INVALID_REQUEST", "Expected a weather plan")
        if not plan.outputs:  # never ask the person to approve a plan that cannot run
            raise OpenEPWError("NO_EXECUTABLE_OUTPUTS", "Weather plan has no executable outputs")
        approved_via = await confirm_submission(ctx, plan.plan_hash)
        return _job_summary(runner.submit(plan, idempotency_key, approved_via=approved_via))

    @tool
    def weather_geocode(query: str, mode: str = "point") -> CallToolResult:
        def action():
            if not query.strip() or len(query) > 150:
                raise OpenEPWError("INVALID_REQUEST", "Place name must be 1–150 characters")
            return service.geocode(query, mode=mode)
        return call("weather_geocode", action)

    @tool
    def weather_places_interpret(text: str, draft: dict | None = None) -> CallToolResult:
        def action():
            if not text.strip() or len(text) > 4000:
                raise OpenEPWError("INVALID_REQUEST", "Place text must be 1–4000 characters")
            return service.interpret_places(text, draft)
        return call("weather_places_interpret", action)

    @tool
    def weather_places_preview(places: list[str | dict]) -> CallToolResult:
        def action():
            texts = [item if isinstance(item, str) else str(item.get("input", "")) for item in places]
            if not places or any(not text.strip() or len(text) > 150 for text in texts):
                raise OpenEPWError("INVALID_REQUEST", "Each place must be 1–150 characters")
            return _preview_summary(service.preview_places(places))
        return call("weather_places_preview", action)

    @tool
    def weather_place_set(query: PlaceSetQueryArg) -> CallToolResult:
        return call("weather_place_set",
                    lambda: _preview_summary(service.place_set(PlaceSetQuery.model_validate(query))))

    @tool
    def weather_locations_review(locations: GeographyArg) -> CallToolResult:
        return call("weather_locations_review", service.review_locations, locations)

    @tool
    def weather_product_offers(locations: GeographyArg, product: str | None = None,
                               provider: str | None = None,
                               years: list[int] | None = None) -> CallToolResult:
        def action():
            if product not in (None, "historical", "amy", "tmy", "tmyx", "published"):
                raise OpenEPWError("INVALID_REQUEST", "Unknown product type")
            return service.product_offers(locations, product=product, provider=provider, years=years)
        return call("weather_product_offers", action)

    @tool
    def weather_assess(query: AvailabilityQueryArg) -> CallToolResult:
        def action():
            if query.get("kind") == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
            return service.assess_availability(
                TypeAdapter(AvailabilityQuery).validate_python(query))
        return call("weather_assess", action)

    @tool
    def weather_discover(request: WeatherRequestArg) -> CallToolResult:
        return call("weather_discover", lambda: service.discover(weather_request(request)))

    @tool
    def weather_plan(request: WeatherRequestArg, kind: str = "weather") -> CallToolResult:
        def action():
            if kind == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
            if kind != "weather":
                raise OpenEPWError("INVALID_REQUEST", "Unknown plan kind")
            return _plan_summary(service.plan(weather_request(request)))
        return call("weather_plan", action)

    @tool
    def plan_inspect(plan_hash: str, offset: int = 0, limit: int = 50) -> CallToolResult:
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
        return call("plan_inspect", action)

    @tool
    def epw_upload(content_base64: str, filename: str | None = None) -> CallToolResult:
        def action():
            if len(content_base64) > 6_666_672:
                raise OpenEPWError("RESOURCE_LIMIT", "EPW upload exceeds 5 MB")
            try:
                body = base64.b64decode(content_base64, validate=True)
            except (ValueError, binascii.Error):
                raise OpenEPWError("INVALID_BASELINE", "Invalid base64 EPW content") from None
            if not body or len(body) > MAX_UPLOAD:
                raise OpenEPWError("RESOURCE_LIMIT", "EPW upload exceeds 5 MB")
            data = read_epw(body)
            ref = service.register_baseline(body)
            return {"artifact_id": ref.id, "sha256": ref.sha256, "bytes": ref.bytes,
                    "rows": len(data.data), "input_qc": [i.model_dump(mode="json")
                    for i in validate(data)[:20]],
                    "filename": Path(filename).name if filename else None}
        return call("epw_upload", action)

    @tool
    def epw_register_path(path: str) -> CallToolResult:
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
        return call("epw_register_path", action)

    @tool
    async def weather_submit(plan_hash: str, ctx: Context,
                             idempotency_key: str | None = None) -> CallToolResult:
        async def action():
            return await submit(service.plan_store.get(plan_hash), idempotency_key, ctx)
        return await acall("weather_submit", action)

    @tool
    def job_inspect(job_id: str) -> CallToolResult:
        def action():
            job = runner.store.get(job_id)
            result = _job_summary(job)
            result["completed_output_ids"] = list(runner.store.items(job_id))[:50]
            if job.bundle:
                _, path = service.artifacts.resolve(job.bundle.manifest.id)
                manifest = json.loads(path.read_text(encoding="utf-8"))
                result["batch_rows"] = [
                    {"occurrence_index": row.get("occurrence_index"),
                     "period_start": row.get("period_start"),
                     "period_end": row.get("period_end"),
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
        return call("job_inspect", action)

    @tool
    def job_cancel(job_id: str) -> CallToolResult:
        return call("job_cancel", lambda: _job_summary(runner.store.cancel(job_id)))

    @tool
    async def job_retry_failed(job_id: str, ctx: Context,
                               idempotency_key: str | None = None) -> CallToolResult:
        async def action():
            job = runner.store.get(job_id)
            if job.kind == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP retry is suspended")
            runner.retry_plan(job_id)  # finished, with something to retry, before asking
            # The person confirms the original reviewed plan; the retry runs a subset of it.
            approved_via = await confirm_submission(ctx, job.plan_hash)
            return _job_summary(runner.retry_failed(job_id, idempotency_key,
                                                    approved_via=approved_via))
        return await acall("job_retry_failed", action)

    @tool
    def artifact_inspect(artifact_id: str) -> CallToolResult:
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
        return call("artifact_inspect", action)

    @tool
    def weather_visualization_capabilities() -> CallToolResult:
        return call("weather_visualization_capabilities", service.visualization_capabilities)

    @tool
    def weather_data_describe(artifact_ids: list[str]) -> CallToolResult:
        return call("weather_data_describe", service.describe_weather_data, artifact_ids)

    @tool
    def weather_visualize(request: VisualizationRequestArg) -> CallToolResult:
        return call("weather_visualize",
                    lambda: service.visualize_weather(VisualizationRequest.model_validate(request)))

    @tool
    def weather_data_page(view_id: str, offset: int = 0, limit: int = 100) -> CallToolResult:
        return call("weather_data_page", service.page_weather_data, view_id, offset, limit)

    @tool
    def weather_export_compact(job_id: str) -> CallToolResult:
        def action():
            ref = runner.export_compact(job_id)
            return {"artifact_id": ref.id, "bytes": ref.bytes, "sha256": ref.sha256,
                    "uri": "weather://artifacts/" + ref.id}
        return call("weather_export_compact", action)

    # v0.1 aliases remain available during migration.
    @tool
    async def weather_fetch(plan: dict, ctx: Context,
                            idempotency_key: str | None = None) -> CallToolResult:
        async def action():
            selected = WeatherPlan.model_validate(plan)
            if selected.kind == "weather":
                service.plan_store.put(selected)
            return await submit(selected, idempotency_key, ctx)
        return await acall("weather_fetch", action)

    @tool
    def weather_inspect(job_id: str | None = None, artifact_id: str | None = None) -> CallToolResult:
        if job_id:
            return job_inspect(job_id)
        if artifact_id:
            return artifact_inspect(artifact_id)
        raise ToolError(json.dumps({"code": "INVALID_REQUEST", "retryable": False,
                                    "message": "Provide job_id or artifact_id"}))

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
