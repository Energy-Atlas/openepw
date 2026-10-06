"""Optional LangSmith tracing for the agent chat and the web chat, switched by the env file.

``LANGSMITH_TRACING=true`` and ``LANGSMITH_API_KEY`` in the ignored ``.env`` (or the process
environment, which wins) turn tracing on; anything else leaves it off, even if LangChain's own
environment variables say otherwise. Traces carry only redacted text, tool names, argument
summaries and result summaries: never keys, local paths, EPW bytes or full tool data.
``langsmith`` (the ``harness`` extra) is imported only when tracing is on.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .text import safe_prompt

logger = logging.getLogger("openepw.tracing")
_TRUE = {"1", "true", "yes", "on"}
_NAMES = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY",
          "LANGSMITH_PROJECT", "LANGSMITH_ENDPOINT")
ARGUMENT_LIMIT = 4000


@dataclass(frozen=True)
class TracingSettings:
    enabled: bool
    project: str
    reason: str                                    # why it is on or off; never contains the key
    endpoint: str | None = None
    api_key: str | None = field(default=None, repr=False)


def _read_env_file(env_file: str | Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(env_file) if env_file else None
    if path is None or not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, _, value = line.partition("=")
        if name.strip() in _NAMES and not line.lstrip().startswith("#"):
            values[name.strip()] = value.strip().strip("\"'")
    return values


def tracing_settings(env_file: str | Path | None = ".env", *, default_project: str) -> TracingSettings:
    """Decide tracing from the env file; an exported environment variable overrides it."""
    values = _read_env_file(env_file)
    values.update({name: os.environ[name] for name in _NAMES if os.environ.get(name)})
    flag = values.get("LANGSMITH_TRACING") or values.get("LANGCHAIN_TRACING_V2") or ""
    key = values.get("LANGSMITH_API_KEY") or values.get("LANGCHAIN_API_KEY") or None
    project = values.get("LANGSMITH_PROJECT") or default_project
    endpoint = values.get("LANGSMITH_ENDPOINT") or None
    if flag.strip().lower() not in _TRUE:
        return TracingSettings(False, project, "LANGSMITH_TRACING is not true")
    if not key:
        return TracingSettings(False, project, "LANGSMITH_TRACING is true but LANGSMITH_API_KEY is missing")
    if importlib.util.find_spec("langsmith") is None:
        return TracingSettings(False, project, "langsmith is not installed (pip install -e \".[harness]\")")
    return TracingSettings(True, project, f"on (project {project})", endpoint, key)


def langsmith_client(settings: TracingSettings) -> Any:
    """A LangSmith client that sends in the background, so tracing never blocks a turn."""
    from langsmith import Client

    return Client(api_key=settings.api_key, api_url=settings.endpoint, auto_batch_tracing=True,
                  timeout_ms=(2000, 5000))


@contextmanager
def langchain_tracing(settings: TracingSettings | None, client: Any = None) -> Iterator[None]:
    """Turn LangChain tracing on or off for the calls inside, overriding its environment variables."""
    if settings is None:
        with nullcontext():
            yield
        return
    from langsmith import tracing_context

    if settings.enabled:
        with tracing_context(enabled=True, client=client, project_name=settings.project):
            yield
    else:
        with tracing_context(enabled=False):
            yield


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Tool arguments for a trace: redacted strings, no file contents, bounded size."""
    def clean(value: Any, depth: int = 0) -> Any:
        if isinstance(value, dict):
            return {key: ("[omitted]" if "base64" in key or key in ("content", "bytes") else clean(item, depth + 1))
                    for key, item in list(value.items())[:30]} if depth < 4 else "{...}"
        if isinstance(value, list):
            items = [clean(item, depth + 1) for item in value[:10]]
            return items + [f"... {len(value) - 10} more"] if len(value) > 10 else items
        if isinstance(value, str):
            return safe_prompt(value, limit=300)
        return value

    summary = clean(arguments)
    if len(json.dumps(summary, default=str)) > ARGUMENT_LIMIT:
        return {"keys": sorted(arguments)}
    return summary


class NullTracer:
    """Tracing off: every call is a no-op."""

    enabled = False
    failed = False

    def start_turn(self, kind: str, inputs: dict[str, Any], **metadata: Any) -> None:
        return None

    def end_turn(self, outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
        return None

    def start(self, name: str, run_type: str, inputs: dict[str, Any]) -> Any:
        return None

    def end(self, run: Any, outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
        return None

    def close(self) -> None:
        return None


class _FailureFlag(logging.Handler):
    """Notices the LangSmith client's own failure logs (sent from its background thread)."""

    def __init__(self, tracer: LangSmithTracer):
        super().__init__(logging.WARNING)
        self.tracer = tracer

    def emit(self, record: logging.LogRecord) -> None:
        self.tracer.failed = True


class LangSmithTracer(NullTracer):
    """One LangSmith run per input (turn) with nested model and tool runs.

    Failures never interrupt the chat: they set ``failed`` once and further sends stop.
    """

    enabled = True

    def __init__(self, settings: TracingSettings, *, client: Any = None):
        self.settings = settings
        self.client = client if client is not None else langsmith_client(settings)
        self.failed = False
        self._stack: list[Any] = []
        self._flag = _FailureFlag(self)
        langsmith_logger = logging.getLogger("langsmith")
        self._propagate = langsmith_logger.propagate
        langsmith_logger.addHandler(self._flag)
        langsmith_logger.propagate = False         # one notice from the host, not tracebacks

    def _guard(self, action: Any) -> Any:
        if self.failed:
            return None
        try:
            return action()
        except Exception:
            self.failed = True
            logger.warning("LangSmith tracing failed; continuing without traces")
            return None

    def start_turn(self, kind: str, inputs: dict[str, Any], **metadata: Any) -> None:
        from langsmith.run_trees import RunTree

        def begin() -> Any:
            run = RunTree(name=f"openepw.agent.{kind}", run_type="chain", inputs=inputs,
                          project_name=self.settings.project, ls_client=self.client,
                          extra={"metadata": metadata})
            run.post()
            return run

        self._stack = [run] if (run := self._guard(begin)) is not None else []

    def end_turn(self, outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
        while len(self._stack) > 1:                 # close anything an exception left open
            self.end(self._stack[-1], error=error or "interrupted")
        if self._stack:
            root = self._stack.pop()
            self._guard(lambda: (root.end(outputs=outputs, error=error), root.patch()))

    def start(self, name: str, run_type: str, inputs: dict[str, Any]) -> Any:
        if not self._stack:
            return None
        parent = self._stack[-1]

        def begin() -> Any:
            child = parent.create_child(name=name, run_type=run_type, inputs=inputs)
            child.post()
            return child

        child = self._guard(begin)
        if child is not None:
            self._stack.append(child)
        return child

    def end(self, run: Any, outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
        if run is None:
            return
        if run in self._stack:
            while self._stack and self._stack[-1] is not run:
                self._stack.pop()
            self._stack.pop()
        self._guard(lambda: (run.end(outputs=outputs, error=error), run.patch()))

    def close(self) -> None:
        try:
            self.client.flush(timeout=5)
        except Exception:
            self.failed = True
        langsmith_logger = logging.getLogger("langsmith")
        langsmith_logger.removeHandler(self._flag)
        langsmith_logger.propagate = self._propagate


def make_tracer(settings: TracingSettings) -> NullTracer:
    return LangSmithTracer(settings) if settings.enabled else NullTracer()
