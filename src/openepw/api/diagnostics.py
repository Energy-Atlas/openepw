"""Opt-in diagnostics for testing a hosted deployment (``RuntimeConfig.debug_log``).

When enabled, the server keeps its recent warnings and errors in memory (never on disk) and
``GET /v1/diagnostics`` returns them, redacted, for the web UI's "Copy log" button. Off by
default: it is meant for staging, where testers share one server log, not for production.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException

# Loggers whose records are kept: the root (openepw.* and libraries) and uvicorn, which does
# not propagate and logs unhandled request errors.
LOGGERS = ("", "uvicorn")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CREDENTIAL = re.compile(r"(?i)\b(bearer\s+|(?:api[_-]?key|key|token|password|secret)\s*[=:]\s*)[^\s,;'\"]{8,}")
_SECRET_NAME = re.compile(r"(?i)(key|token|secret|password)")


class RecentLog(logging.Handler):
    """The last few hundred warnings and errors, redacted as they are recorded."""

    def __init__(self, capacity: int = 200):
        super().__init__(level=logging.WARNING)
        self.records: deque[dict[str, str]] = deque(maxlen=capacity)
        self.secrets: list[str] = []

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[redacted]")
        text = _CREDENTIAL.sub(lambda match: f"{match.group(1)}[redacted]", text)
        return _EMAIL.sub("[email]", text)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = record.getMessage()
            if record.exc_info:
                text += "\n" + "".join(traceback.format_exception(*record.exc_info))[-4000:]
            self.records.append({
                "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="seconds"),
                "level": record.levelname, "logger": record.name, "message": self.redact(text)[:6000]})
        except Exception:
            self.handleError(record)


_recent: RecentLog | None = None


def _secret_values(service: Any) -> list[str]:
    """Every configured credential and credential-like environment value, longest first."""
    config = service.config
    values = [getattr(config, name).get_secret_value() for name in type(config).model_fields
              if hasattr(getattr(config, name, None), "get_secret_value")]
    values += [value for name, value in os.environ.items() if _SECRET_NAME.search(name)]
    return sorted({value for value in values if value and len(value) >= 6}, key=len, reverse=True)


def install(app: FastAPI, service: Any) -> None:
    """Add GET /v1/diagnostics: 404 unless ``debug_log`` is on."""
    global _recent
    enabled = bool(getattr(service.config, "debug_log", False))
    if enabled and _recent is None:
        _recent = RecentLog()
        for name in LOGGERS:
            logging.getLogger(name).addHandler(_recent)
    if enabled and _recent is not None:
        _recent.secrets = _secret_values(service)

    @app.get("/v1/diagnostics")
    def diagnostics():
        if not enabled or _recent is None:
            raise HTTPException(404, "Not Found")
        policy = getattr(app.state, "security_policy", None)
        view = service.catalog_store.active()
        return {"version": app.version,
                "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "security_profile": f"{policy.profile} ({policy.digest})" if policy else None,
                "catalog_generation": view.snapshot.generation_id if view else None,
                "server_log": list(_recent.records)}
