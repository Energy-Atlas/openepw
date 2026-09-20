from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from ..jobs.worker import JobRunner
from ..models import FutureRequest, OpenEPWError, WeatherPlan, WeatherRequest
from ..service import WeatherService


def create_server(service=None):
    service = service or WeatherService()
    runner = JobRunner(service)

    @asynccontextmanager
    async def lifespan(server):
        runner.recover()
        yield {"runner": runner}
        runner.close()

    # Streamable HTTP is loopback-only in v0.1. Use authenticated REST remotely.
    server = FastMCP(
        "openepw",
        host="127.0.0.1",
        port=8001,
        lifespan=lifespan,
        instructions="Plan before fetching. Weather artifacts are resources, not inline hourly tables. Explicitly inspect QC and limitations.",
    )

    def call(function, *args, **kwargs):
        try:
            result = function(*args, **kwargs)
            return result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        except OpenEPWError as exc:
            return {"error": exc.issue.model_dump()}
        except ValidationError:
            return {
                "error": {"code": "INVALID_REQUEST", "message": "Request schema validation failed"}
            }

    @server.tool()
    def weather_geocode(query: str, mode: str = "point") -> dict:
        """Resolve a name; multiple candidates require an explicit selection."""
        return call(service.geocode, query, mode=mode)

    @server.tool()
    def weather_discover(request: dict) -> dict:
        """Find source alternatives with actual capabilities and limitations."""
        return call(lambda: service.discover(WeatherRequest.model_validate(request)))

    @server.tool()
    def weather_plan(request: dict, kind: str = "weather") -> dict:
        """Build an inspectable plan. Future baseline/signals must be artifact IDs."""

        def action():
            if kind == "future":
                future = FutureRequest.model_validate(request)
                service.artifacts.resolve(future.baseline)
                if future.signals:
                    service.artifacts.resolve(future.signals)
                return service.plan_future(future)
            if kind != "weather":
                raise OpenEPWError("INVALID_REQUEST", "Unknown plan kind")
            return service.plan(WeatherRequest.model_validate(request))

        return call(action)

    @server.tool()
    def weather_fetch(plan: dict, idempotency_key: str | None = None) -> dict:
        """Submit a weather plan as a durable job; inspect its status afterwards."""

        def action():
            p = WeatherPlan.model_validate(plan)
            if p.kind != "weather":
                raise OpenEPWError(
                    "INVALID_REQUEST", "Use weather_generate_future for future plans"
                )
            return runner.submit(p, idempotency_key)

        return call(action)

    @server.tool()
    def weather_inspect(job_id: str | None = None, artifact_id: str | None = None) -> dict:
        """Return compact job state or artifact metadata and a resource URI."""

        def action():
            if job_id:
                return runner.store.get(job_id)
            if artifact_id:
                ref, _ = service.artifacts.resolve(artifact_id)
                return {**ref.model_dump(), "uri": "weather://artifacts/" + ref.id}
            raise OpenEPWError("INVALID_REQUEST", "Provide job_id or artifact_id")

        return call(action)

    @server.tool()
    def weather_generate_future(
        request: dict | None = None, plan: dict | None = None, idempotency_key: str | None = None
    ) -> dict:
        """Submit future generation using a baseline artifact and explicit climate semantics."""

        def action():
            if bool(request) == bool(plan):
                raise OpenEPWError("INVALID_REQUEST", "Provide exactly one request or plan")
            p = WeatherPlan.model_validate(plan) if plan else None
            r = p.request if p else FutureRequest.model_validate(request)
            if p and p.kind != "future":
                raise OpenEPWError("INVALID_REQUEST", "Expected a future plan")
            service.artifacts.resolve(r.baseline)
            if r.signals:
                service.artifacts.resolve(r.signals)
            return runner.submit(p or service.plan_future(r), idempotency_key)

        return call(action)

    @server.resource("weather://artifacts/{artifact_id}")
    def artifact(artifact_id: str) -> bytes:
        """Read a checksummed EPW, manifest or QC artifact."""
        _, path = service.artifacts.resolve(artifact_id)
        return path.read_bytes()

    return server
