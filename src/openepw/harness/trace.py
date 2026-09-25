"""Optional, compact LangSmith tracing for the local console harness."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langsmith import Client
from langsmith.run_trees import RunTree

from .agent import AgentIntent, IntentParser, MCPPort, safe_prompt

_IDENTIFIERS = ("plan_hash", "job_id", "artifact_id")
_RESULT_FIELDS = ("plan_hash", "id", "artifact_id", "kind", "state",
                  "status", "output_count", "completed", "failed",
                  "simulation_ready", "qc_issue_codes")


class ArtifactPort(MCPPort, Protocol):
    async def upload_file(self, path: str) -> str: ...

    async def read_artifact(self, artifact_id: str) -> bytes: ...


def _identifiers(data: dict[str, Any]) -> dict[str, str]:
    return {key: data[key] for key in _IDENTIFIERS
            if isinstance(data.get(key), str)}


def _result_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data[key] for key in _RESULT_FIELDS
            if isinstance(data.get(key), (str, int, bool, list))}


class LangSmithTrace:
    """Record one hierarchy per console turn using only deliberate fields."""

    def __init__(self, api_key: str, *, project: str = "openepw-local-chat",
                 client: Any = None):
        self.client = client or Client(api_key=api_key, auto_batch_tracing=False,
                                       timeout_ms=(2000, 5000))
        self.project = project
        self.active: RunTree | None = None
        self.failed = False

    def _post(self, run: RunTree) -> bool:
        if self.failed:
            return False
        try:
            run.post()
        except Exception:
            self.failed = True
            return False
        return True

    def _end(self, run: RunTree | None, *, outputs: dict[str, Any] | None = None,
             error: str | None = None) -> None:
        if run is None or self.failed:
            return
        try:
            run.end(outputs=outputs, error=error)
            run.patch()
        except Exception:
            self.failed = True

    def start_step(self, name: str, run_type: str,
                   inputs: dict[str, Any]) -> RunTree | None:
        if self.active is None or self.failed:
            return None
        child = self.active.create_child(name=name, run_type=run_type,
                                         inputs=inputs)
        return child if self._post(child) else None

    def end_step(self, run: RunTree | None, *, outputs: dict[str, Any] | None = None,
                 error: str | None = None) -> None:
        self._end(run, outputs=outputs, error=error)

    def close(self) -> None:
        try:
            self.client.flush(timeout=5)
            self.client.close()
        except Exception:
            self.failed = True

    async def run_turn(self, line: str,
                       action: Callable[[str], Awaitable[str]]) -> str:
        root = RunTree(
            name="openepw.chat.turn", run_type="chain",
            inputs={"request": (safe_prompt(line) if not line.startswith("/")
                                else line.partition(" ")[0])},
            project_name=self.project, ls_client=self.client,
        )
        self.active = root if self._post(root) else None
        try:
            answer = await action(line)
        except Exception as exc:
            self._end(self.active, error=type(exc).__name__)
            raise
        else:
            status = (answer[1:answer.index("]")] if answer.startswith("[")
                      and "]" in answer else "command_completed")
            self._end(self.active, outputs={"status": status})
            return answer
        finally:
            self.active = None


class TracingIntentParser:
    def __init__(self, model: IntentParser, tracer: LangSmithTrace):
        self.model = model
        self.tracer = tracer

    def parse(self, prompt: str) -> AgentIntent:
        run = self.tracer.start_step("openepw.intent", "llm", {})
        try:
            intent = self.model.parse(prompt)
        except Exception as exc:
            self.tracer.end_step(run, error=type(exc).__name__)
            raise
        self.tracer.end_step(run, outputs={
            key: value for key, value in intent.model_dump(mode="json").items()
            if key in ("kind", "product", "years", "provider", "method",
                       "climate_scenario", "climate_period", "reference_period")
            and value not in (None, [], "")
        })
        return intent


class TracingMCPPort:
    def __init__(self, port: ArtifactPort, tracer: LangSmithTrace):
        self.port = port
        self.tracer = tracer

    async def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        run = self.tracer.start_step("mcp." + name, "tool", _identifiers(arguments))
        try:
            result = await self.port.call(name, **arguments)
        except Exception as exc:
            self.tracer.end_step(run, error=type(exc).__name__)
            raise
        self.tracer.end_step(run, outputs=_result_summary(result))
        return result

    async def upload_file(self, path: str) -> str:
        run = self.tracer.start_step("mcp.baseline_upload", "tool", {})
        try:
            artifact_id = await self.port.upload_file(path)
        except Exception as exc:
            self.tracer.end_step(run, error=type(exc).__name__)
            raise
        self.tracer.end_step(run, outputs={"artifact_id": artifact_id})
        return artifact_id

    async def read_artifact(self, artifact_id: str) -> bytes:
        run = self.tracer.start_step("mcp.artifact_read", "tool",
                                     {"artifact_id": artifact_id})
        try:
            data = await self.port.read_artifact(artifact_id)
        except Exception as exc:
            self.tracer.end_step(run, error=type(exc).__name__)
            raise
        self.tracer.end_step(run, outputs={"bytes": len(data)})
        return data
