"""`/v2/agent`: the web chat on the agent core (P4). Turns run on ``AgentHost``; events stream as SSE."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

from fastapi import FastAPI, File, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ..agent.model_port import DEFAULT_MODEL, ModelPort, OpenAIModel, load_openai_key
from ..agent.moderation import ModerationPort, OpenAIModeration
from ..agent.policy_config import SecurityPolicy, default_policy, requires_moderation_key
from ..agent.session import MAX_UPLOAD
from ..agent.web import AgentHost, WebInput, WebRefusal

HEARTBEAT_SECONDS = 15.0
STREAM_SECONDS = 600.0            # the browser's EventSource reconnects with Last-Event-ID


def owner_of(request: Request) -> str:
    """The person a session belongs to: the signed-in account, else the client address (the first
    X-Forwarded-For entry behind a proxy, as the account gate reads it)."""
    user = getattr(request.state, "user_id", None)
    if user:
        return f"user:{user}"
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return "ip:" + (forwarded or (request.client.host if request.client else "unknown"))


def build_host(service: Any, runner: Any, mcp_server: Any, *, security: SecurityPolicy | None,
               env_file: str | None, model: Any = "auto") -> AgentHost:
    """The host for `create_app`. ``model`` is "auto" (OpenAI when OPENAI_API_KEY is set), None
    (guided mode only) or a factory returning a model port per turn.

    A profile that refuses input when moderation cannot run needs the key at start-up (owner
    decision Q4, 2026-10-09), as `openepw chat` does.
    """
    security = security or default_policy()
    key = load_openai_key(env_file)
    model_factory: Callable[[], ModelPort | None] | None
    if model == "auto":
        model_factory = (lambda: OpenAIModel(key, model=DEFAULT_MODEL, max_cost_usd=float("inf"))) if key else None
    else:
        model_factory = model
    moderation_factory: Callable[[], ModerationPort | None] | None = None
    if security.moderation.enabled:
        if key:
            moderation_model = security.moderation.model
            moderation_factory = lambda: OpenAIModeration(key, model=moderation_model)  # noqa: E731
        elif requires_moderation_key(security):
            raise ValueError(f"The {security.profile} profile moderates every message and refuses input when "
                             "moderation cannot run, but OPENAI_API_KEY is not set.")
    return AgentHost(service.config.data_root, runner, mcp_server, security=security,
                     model_factory=model_factory, moderation_factory=moderation_factory)


def install(app: FastAPI, host: AgentHost) -> None:
    @app.exception_handler(WebRefusal)
    async def refused(request: Request, exc: WebRefusal) -> JSONResponse:
        return JSONResponse({"code": exc.code, "message": exc.message}, status_code=exc.status)

    @app.post("/v2/agent/sessions", status_code=201)
    def create_session(request: Request) -> dict[str, Any]:
        return host.snapshot(host.create(owner_of(request)))

    @app.get("/v2/agent/sessions/{session_id}")
    def get_session(session_id: str, request: Request) -> dict[str, Any]:
        host.check_owner(session_id, owner_of(request))
        host.follow(session_id)                      # running jobs after a restart
        return host.snapshot(session_id)

    @app.post("/v2/agent/sessions/{session_id}/inputs", status_code=202)
    def send_input(session_id: str, item: WebInput, request: Request) -> dict[str, Any]:
        host.submit(session_id, owner_of(request), item)
        return host.snapshot(session_id, events=0)

    @app.post("/v2/agent/sessions/{session_id}/upload", status_code=202)
    async def upload(session_id: str, request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        content = await file.read(MAX_UPLOAD + 1)
        if not content or len(content) > MAX_UPLOAD:
            raise WebRefusal("RESOURCE_LIMIT", "EPW uploads must be 1 byte to 5 MB.", status=413)
        host.upload(session_id, owner_of(request), content, file.filename)
        return host.snapshot(session_id, events=0)

    @app.get("/v2/agent/sessions/{session_id}/events", response_model=None)
    async def events(session_id: str, request: Request, after: int = Query(0, ge=0), poll: bool = False,
                     until_idle: bool = False,
                     last_event_id: str | None = Header(default=None)) -> Any:
        """Events after ``Last-Event-ID`` (or ``after``) as server-sent events: ``agent`` frames
        carry events, ``state`` frames the session without events whenever a turn ends or the
        form changes. ``poll`` returns the same as JSON once; ``until_idle`` ends the stream
        when the session is idle (tests)."""
        host.check_owner(session_id, owner_of(request))
        if last_event_id and last_event_id.isdigit():
            after = max(after, int(last_event_id))
        if poll:
            new = await asyncio.to_thread(host.store.events, session_id, after)
            return {"events": [event.model_dump(mode="json") for event in new],
                    "cursor": new[-1].seq if new else after,
                    "state": await asyncio.to_thread(host.snapshot, session_id, events=0)}
        return StreamingResponse(_stream(host, session_id, after, request, until_idle),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _stream(host: AgentHost, session_id: str, after: int, request: Request,
                  until_idle: bool) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STREAM_SECONDS
    beat = loop.time()
    was_busy: bool | None = None
    while loop.time() < deadline and not await request.is_disconnected():
        new = await asyncio.to_thread(host.store.events, session_id, after)
        for event in new:
            after = event.seq
            yield f"id: {event.seq}\nevent: agent\ndata: {event.model_dump_json()}\n\n"
        busy = host.busy(session_id)
        if new or busy != was_busy:
            state = await asyncio.to_thread(host.snapshot, session_id, events=0)
            yield f"event: state\ndata: {json.dumps(state)}\n\n"
            beat = loop.time()
        was_busy = busy
        if until_idle and not busy and not new:
            return
        if loop.time() - beat > HEARTBEAT_SECONDS:
            beat = loop.time()
            yield ": keep-alive\n\n"
        await asyncio.sleep(0.25)
