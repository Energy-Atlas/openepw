import hmac
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, model_validator

from ..availability import AvailabilityQuery
from ..epw import read_epw
from ..jobs.worker import JobRunner
from ..models import FutureRequest, OpenEPWError, WeatherPlan, WeatherRequest
from ..service import WeatherService


class JobSubmission(BaseModel):
    plan: WeatherPlan | None = None
    plan_hash: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def exactly_one_plan(self):
        if (self.plan is None) == (self.plan_hash is None):
            raise ValueError("Specify exactly one of plan or plan_hash")
        return self


class FutureJobSubmission(BaseModel):
    plan: WeatherPlan
    idempotency_key: str | None = None


class RetrySubmission(BaseModel):
    idempotency_key: str | None = None


class GeocodeQuery(BaseModel):
    query: str
    mode: str = "point"


def create_app(service=None, *, remote=False):
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
        title="OpenEPW", version="0.1.0", lifespan=lifespan, dependencies=[Depends(authenticate)]
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

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/v1/geocode")
    def geocode(query: GeocodeQuery):
        return service.geocode(query.query, mode=query.mode)

    @app.post("/v1/weather/discover")
    def discover(request: WeatherRequest):
        return service.discover(request)

    @app.post("/v1/availability")
    def availability(query: AvailabilityQuery):
        return service.assess_availability(query)

    @app.post("/v1/weather/plan")
    def plan(request: WeatherRequest):
        return service.plan(request)

    def safe_future(request):
        # Wire clients use registered artifacts; Python callers may use paths.
        service.artifacts.resolve(request.baseline)
        if request.signals:
            service.artifacts.resolve(request.signals)

    @app.post("/v1/future/plan")
    def future_plan(request: FutureRequest):
        safe_future(request)
        return service.plan_future(request)

    def submit(payload, kind):
        selected_plan = (service.plan_store.get(payload.plan_hash)
                         if payload.plan_hash is not None else payload.plan)
        if selected_plan.kind != kind:
            raise OpenEPWError("INVALID_REQUEST", "Plan kind does not match endpoint")
        if kind == "future":
            safe_future(selected_plan.request)
        return runner.submit(selected_plan, payload.idempotency_key)

    @app.post("/v1/weather/jobs", status_code=202)
    def weather_job(payload: JobSubmission):
        return submit(payload, "weather")

    @app.post("/v1/future/jobs", status_code=202)
    def future_job(payload: FutureJobSubmission):
        return submit(payload, "future")

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str):
        return runner.store.get(job_id)

    @app.post("/v1/jobs/{job_id}/retry", status_code=202)
    def retry(job_id: str, payload: RetrySubmission | None = None):
        return runner.retry_failed(job_id, payload.idempotency_key if payload else None)

    @app.post("/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return runner.store.cancel(job_id)

    @app.get("/v1/jobs/{job_id}/artifacts")
    def artifacts(job_id: str):
        return runner.store.get(job_id).bundle

    @app.post("/v1/jobs/{job_id}/export/compact")
    def compact_export(job_id: str):
        return runner.export_compact(job_id)

    @app.post("/v1/artifacts", status_code=201)
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

    return app
