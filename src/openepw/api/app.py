import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ValidationError, model_validator

from ..availability import AvailabilityQuery
from ..chat.coordinator import ChatActionError, ChatCoordinator, OfflineParser, StaleSession
from ..epw import read_epw
from ..jobs.worker import JobRunner
from ..models import FutureRequest, OpenEPWError, WeatherPlan, WeatherRequest
from ..service import WeatherService
from ..visualization.models import VisualizationRequest
from .site_gate import SiteGate


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
    plan: WeatherPlan | None = None
    plan_hash: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def exactly_one_plan(self):
        if (self.plan is None) == (self.plan_hash is None):
            raise ValueError("Specify exactly one of plan or plan_hash")
        return self


class RetrySubmission(BaseModel):
    idempotency_key: str | None = None


class GeocodeQuery(BaseModel):
    query: str
    mode: str = "point"


class ChatTurn(BaseModel):
    text: str
    revision: int
    idempotency_key: str


class ChatChoice(BaseModel):
    revision: int
    choice_id: str
    idempotency_key: str


class ChatAction(BaseModel):
    revision: int
    idempotency_key: str


class ChatProducts(ChatAction):
    product_ids: list[str]


class ChatGeography(ChatAction):
    geography: dict | list


class ChatUpload(ChatAction):
    artifact_id: str


class ChatView(ChatAction):
    request: VisualizationRequest
    prompt: str | None = None


def create_app(service=None, *, remote=False, chat_parser=None):
    service = service or WeatherService()
    if remote and not (service.config.bearer_token or service.config.site_password):
        raise ValueError("Remote mode requires OPENEPW_BEARER_TOKEN or OPENEPW_SITE_PASSWORD")
    runner = JobRunner(service)
    if chat_parser is None:
        try:
            from ..harness.chat import load_model_key
            from ..harness.graph_model import LangChainTurnParser

            chat_parser = LangChainTurnParser(load_model_key(),
                ledger_path=service.config.data_root / "chat" / "model-usage.json")
        except (ImportError, RuntimeError, ValueError):
            chat_parser = OfflineParser()
        except Exception as error:
            # A missing optional model or credential leaves deterministic parsing usable.
            if type(error).__name__ != "ModelUnavailable":
                raise
            chat_parser = OfflineParser()
    chat = ChatCoordinator(service, parser=chat_parser)

    @asynccontextmanager
    async def lifespan(app):
        runner.recover()
        yield
        runner.close()

    def authenticate(request: Request, authorization: str | None = Header(default=None)):
        # A browser signed in through the site password needs no bearer token; health stays open.
        if getattr(request.state, "site_ok", False) or request.url.path == "/health":
            return
        token = service.config.bearer_token
        if token and not hmac.compare_digest(
            authorization or "", "Bearer " + token.get_secret_value()
        ):
            raise HTTPException(401, "Authentication required")

    app = FastAPI(
        title="OpenEPW", version="0.1.0", lifespan=lifespan, dependencies=[Depends(authenticate)]
    )
    app.state.service = service
    if service.config.site_password:
        SiteGate(service.config.site_password.get_secret_value()).install(app)
    app.state.runner = runner
    try:
        from ..mcp.server import create_server
    except ImportError:  # the mcp extra is optional for the REST server
        app.state.mcp_server = None
    else:
        # Agent sessions connect in-process (P4); it never runs a second job runner.
        app.state.mcp_server = create_server(service, runner=runner)
    app.state.chat = chat

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

    @app.exception_handler(StaleSession)
    async def stale_chat(request, exc):
        return JSONResponse({"code": "STALE_SESSION", "message": str(exc),
                             "snapshot": exc.snapshot}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing_chat(request, exc):
        return JSONResponse({"code": "NOT_FOUND", "message": "Session not found"}, status_code=404)

    @app.exception_handler(ChatActionError)
    async def invalid_chat_action(request, exc):
        return JSONResponse({"code": "INVALID_REQUEST", "message": str(exc)}, status_code=400)

    @app.exception_handler(ValidationError)
    async def invalid_chat_geography(request, exc):
        return JSONResponse({"code": "INVALID_REQUEST", "message": "Invalid request fields",
                             "fields": [list(item["loc"]) for item in exc.errors()]}, status_code=422)

    point_cache: dict = {}

    @app.get("/v1/catalog/point")
    def catalog_point(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
                      years: str = Query(default="", max_length=400)):
        """Named-product availability at one point, for the map's hover card (offline catalog)."""
        wanted = sorted({int(item) for item in years.split(",") if item.strip().isdigit()})[:30]
        # Recent places are answered from memory; a newly activated catalog starts afresh.
        view = service.catalog_store.active()
        generation = view.snapshot.generation_id if view else None
        if point_cache.get("generation") != generation:
            point_cache.clear()
            point_cache["generation"] = generation
        key = (round(lat, 3), round(lon, 3), tuple(wanted))
        if key not in point_cache:
            if len(point_cache) > 4096:
                point_cache.clear()
                point_cache["generation"] = generation
            point_cache[key] = service.point_availability(key[0], key[1], wanted)
        return point_cache[key]

    @app.post("/v1/chat/sessions", status_code=201)
    def create_chat():
        return chat.create()

    @app.get("/v1/chat/sessions/{session_id}")
    def get_chat(session_id: str):
        return chat.get(session_id)

    @app.get("/v1/chat/sessions/{session_id}/progress")
    def chat_progress(session_id: str):
        return chat.progress(session_id)

    @app.get("/v1/chat/sessions/{session_id}/events")
    def chat_events(session_id: str, after: int = 0):
        state = chat.get(session_id)
        return {"events": [event for event in state["events"] if event["id"] > after],
                "cursor": len(state["events"]), "revision": state["revision"]}

    @app.post("/v1/chat/sessions/{session_id}/turns/queue", status_code=202)
    def chat_enqueue_turn(session_id: str, payload: ChatTurn):
        return chat.enqueue_turn(session_id, payload.text, payload.idempotency_key)

    @app.get("/v1/chat/turns/{queue_id}")
    def chat_queued_turn(queue_id: str):
        return chat.queued_turn(queue_id)

    @app.delete("/v1/chat/turns/{queue_id}")
    def chat_withdraw_turn(queue_id: str):
        return chat.withdraw_turn(queue_id)

    @app.post("/v1/chat/sessions/{session_id}/turns")
    def chat_turn(session_id: str, payload: ChatTurn):
        return chat.turn(session_id, payload.text, payload.revision, payload.idempotency_key)

    @app.post("/v1/chat/sessions/{session_id}/choices")
    def chat_choice(session_id: str, payload: ChatChoice):
        return chat.answer(session_id, payload.revision, payload.choice_id, payload.idempotency_key)

    @app.post("/v1/chat/sessions/{session_id}/geography")
    def chat_geography(session_id: str, payload: ChatGeography):
        return chat.set_geography(session_id, payload.geography, payload.revision,
                                  payload.idempotency_key)

    @app.post("/v1/chat/sessions/{session_id}/back")
    def chat_back(session_id: str, payload: ChatAction, to_event: int | None = None):
        return chat.back(session_id, payload.revision, payload.idempotency_key, to_event)

    @app.post("/v1/chat/sessions/{session_id}/products")
    def chat_choose_products(session_id: str, payload: ChatProducts):
        return chat.choose_products(session_id, payload.revision, payload.product_ids, payload.idempotency_key)

    @app.post("/v1/chat/sessions/{session_id}/location/approve")
    def chat_approve_location(session_id: str, payload: ChatAction):
        return chat.approve_location(session_id, payload.revision, payload.idempotency_key)

    @app.post("/v1/chat/sessions/{session_id}/prepare")
    def chat_prepare(session_id: str, payload: ChatAction):
        return chat.prepare(session_id, payload.revision, payload.idempotency_key)

    @app.post("/v1/chat/sessions/{session_id}/run", status_code=202)
    def chat_run(session_id: str, payload: ChatAction):
        return chat.run(session_id, payload.revision, payload.idempotency_key, runner)

    @app.post("/v1/chat/sessions/{session_id}/retry", status_code=202)
    def chat_retry(session_id: str, payload: ChatAction):
        return chat.retry(session_id, payload.revision, payload.idempotency_key, runner)

    @app.post("/v1/chat/sessions/{session_id}/export/compact")
    def chat_compact(session_id: str):
        return chat.compact(session_id, runner)

    @app.post("/v1/chat/sessions/{session_id}/uploads")
    def chat_attach_upload(session_id: str, payload: ChatUpload):
        return chat.attach_upload(session_id, payload.revision, payload.idempotency_key,
                                  payload.artifact_id)

    @app.post("/v1/chat/sessions/{session_id}/views")
    def chat_view(session_id: str, payload: ChatView):
        return chat.view(session_id, payload.revision, payload.idempotency_key,
                         runner, payload.request, prompt=payload.prompt)

    @app.get("/v1/views/capabilities")
    def view_capabilities():
        return service.visualization_capabilities()

    @app.post("/v1/views/describe")
    def view_describe(artifact_ids: list[str]):
        return service.describe_weather_data(artifact_ids)

    @app.post("/v1/views/prepare")
    def view_prepare(request: VisualizationRequest):
        return service.visualize_weather(request)

    @app.get("/v1/views/{view_id}/page")
    def view_page(view_id: str, offset: int = 0, limit: int = 100):
        return service.page_weather_data(view_id, offset, min(max(limit, 1), 200))

    @app.post("/v1/geocode")
    def geocode(query: GeocodeQuery):
        return service.geocode(query.query, mode=query.mode)

    @app.post("/v1/weather/discover")
    def discover(request: WeatherRequest):
        return service.discover(request)

    @app.post("/v1/availability")
    def availability(query: AvailabilityQuery):
        return service.assess_availability(query)

    @app.get("/v1/catalog/scopes")
    def catalog_scopes():
        return service.catalog_scopes()

    @app.get("/v1/catalog/map")
    def catalog_map():
        return service.catalog_map()

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
        return runner.submit(selected_plan, payload.idempotency_key, approved_via="api")

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
        return service.register_baseline(body)

    @app.get("/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        ref, path = service.artifacts.resolve(artifact_id)
        return FileResponse(path, media_type=ref.media_type, filename=path.name)

    # The built chat UI, served from the same origin as the API (mounted last, after /v1).
    web_root = service.config.web_root
    if web_root and (Path(web_root) / "index.html").is_file():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
    return app
