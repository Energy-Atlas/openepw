import hmac
import json
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..epw import read_epw
from ..generation.morph import MonthlySignal
from ..jobs.worker import JobRunner
from ..models import (
    ArtifactBundle,
    ArtifactRef,
    DiscoveryResult,
    FutureRequest,
    GeocodeResult,
    JobListResponse,
    OpenEPWError,
    WeatherJob,
    WeatherPlan,
    WeatherRequest,
)
from ..preview import WeatherPreview
from ..service import WeatherService


class HealthResponse(BaseModel):
    status: str
    version: str


class ErrorResponse(BaseModel):
    code: str | None = None
    message: str | None = None
    severity: str | None = None
    retryable: bool | None = None
    fields: list[list[str | int]] | None = None
    detail: str | None = None


class JobSubmission(BaseModel):
    plan: WeatherPlan
    idempotency_key: str | None = None


class GeocodeQuery(BaseModel):
    query: str
    mode: str = "point"


def create_app(service=None, *, remote=False, ui_dir=None):
    service = service or WeatherService()
    if remote and not service.config.bearer_token:
        raise ValueError("Remote mode requires OPENEPW_BEARER_TOKEN")
    runner = JobRunner(service)

    @asynccontextmanager
    async def lifespan(app):
        runner.recover()
        yield
        runner.close()

    def authenticate(authorization: str | None = Header(default=None)):
        token = service.config.bearer_token
        if token and not hmac.compare_digest(
            authorization or "", "Bearer " + token.get_secret_value()
        ):
            raise HTTPException(401, "Authentication required")

    app = FastAPI(
        title="OpenEPW",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
        responses={code: {"model": ErrorResponse} for code in (400, 401, 404, 413, 422)},
    )
    app.state.service = service
    app.state.runner = runner

    @app.middleware("http")
    async def size_limit(request, call_next):
        # Reading here also caps chunked requests; Starlette reuses the cached body.
        if request.method in ("POST", "PUT", "PATCH"):
            data = bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > 5_000_000:
                    return JSONResponse(
                        {"code": "RESOURCE_LIMIT", "message": "Request exceeds 5 MB"},
                        status_code=413,
                    )
            request._body = bytes(data)
        return await call_next(request)

    @app.exception_handler(OpenEPWError)
    async def domain_error(request, exc):
        return JSONResponse(
            exc.issue.model_dump(), status_code=404 if exc.issue.code == "JOB_NOT_FOUND" else 400
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "code": "INVALID_REQUEST",
                "message": "Request schema validation failed",
                "fields": [list(e["loc"]) for e in exc.errors()],
            },
            status_code=422,
        )

    @app.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/v1/geocode", response_model=GeocodeResult)
    def geocode(query: GeocodeQuery):
        return service.geocode(query.query, mode=query.mode)

    @app.post("/v1/weather/discover", response_model=DiscoveryResult)
    def discover(request: WeatherRequest):
        return service.discover(request)

    @app.post("/v1/weather/plan", response_model=WeatherPlan)
    def plan(request: WeatherRequest):
        return service.plan(request)

    def safe_future(request):
        # Wire clients use registered artifacts; Python callers may use paths.
        service.artifacts.resolve(request.baseline)
        if request.signals:
            service.artifacts.resolve(request.signals)

    @app.post("/v1/future/plan", response_model=WeatherPlan)
    def future_plan(request: FutureRequest):
        safe_future(request)
        return service.plan_future(request)

    def submit(payload, kind):
        if payload.plan.kind != kind:
            raise OpenEPWError("INVALID_REQUEST", "Plan kind does not match endpoint")
        if kind == "future":
            safe_future(payload.plan.request)
        return runner.submit(payload.plan, payload.idempotency_key)

    @app.post("/v1/weather/jobs", status_code=202, response_model=WeatherJob)
    def weather_job(payload: JobSubmission):
        return submit(payload, "weather")

    @app.post("/v1/future/jobs", status_code=202, response_model=WeatherJob)
    def future_job(payload: JobSubmission):
        return submit(payload, "future")

    @app.get("/v1/jobs", response_model=JobListResponse)
    def list_jobs(limit: int = Query(20, ge=1, le=100), cursor: str | None = None):
        return runner.store.list_jobs(limit, cursor)

    @app.post("/v1/artifacts/signals", status_code=201, response_model=ArtifactRef)
    def upload_signals(records: list[MonthlySignal] = Body(min_length=1, max_length=10)):
        return service.artifacts.write(
            uuid.uuid4().hex,
            "signals.json",
            json.dumps([r.model_dump(mode="json") for r in records], allow_nan=False).encode(),
            "signals",
        )

    @app.get("/v1/artifacts/{artifact_id}/preview", response_model=WeatherPreview)
    def preview(
        artifact_id: str,
        start: int = Query(0, ge=0),
        limit: int = Query(168, ge=1, le=168),
        variables: list[str] | None = Query(None),
    ):
        return service.preview_artifact(artifact_id, start, limit, variables)

    @app.get("/v1/jobs/{job_id}", response_model=WeatherJob)
    def job(job_id: str):
        return runner.store.get(job_id)

    @app.post("/v1/jobs/{job_id}/cancel", response_model=WeatherJob)
    def cancel(job_id: str):
        return runner.store.cancel(job_id)

    @app.get("/v1/jobs/{job_id}/artifacts", response_model=ArtifactBundle | None)
    def artifacts(job_id: str):
        return runner.store.get(job_id).bundle

    @app.post("/v1/artifacts", status_code=201, response_model=ArtifactRef)
    async def upload(file: UploadFile = File(...)):
        body = await file.read(5_000_001)
        if len(body) > 5_000_000:
            raise OpenEPWError("RESOURCE_LIMIT", "EPW exceeds upload limit")
        read_epw(body)
        return service.artifacts.write(
            uuid.uuid4().hex, "baseline.epw", body, "baseline", "application/vnd.energyplus.epw"
        )

    @app.get("/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        ref, path = service.artifacts.resolve(artifact_id)
        return FileResponse(path, media_type=ref.media_type, filename=path.name)

    if ui_dir is not None:
        from .static import mount_ui

        mount_ui(app, ui_dir)
    return app
