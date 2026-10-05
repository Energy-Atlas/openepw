"""The agent's MCP client: in-process transport, parsed failures and one-shot approvals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.shared.memory import create_connected_server_and_client_session

from ..mcp.approval import approval_callback


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, Any]          # structuredContent, for renderers and the host
    text: str                     # short summary, for model context and transcripts


class ToolFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: list[dict[str, Any]] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or []


def parse_failure(text: str) -> ToolFailure:
    """Tool errors are bare JSON (P1 contract); anything else becomes MCP_TOOL_ERROR."""
    try:
        payload = json.loads(text[text.index("{"):])
        return ToolFailure(str(payload["code"]), str(payload.get("message", "")),
                           retryable=bool(payload.get("retryable", False)),
                           details=list(payload.get("details") or []))
    except (ValueError, KeyError, TypeError):
        return ToolFailure("MCP_TOOL_ERROR", text[:200] or "MCP tool failed")


class ApprovalBook:
    """Each approved plan hash answers exactly one submission confirmation."""

    def __init__(self) -> None:
        self._pending: set[str] = set()

    def approve(self, plan_hash: str) -> None:
        self._pending.add(plan_hash)

    def consume(self, plan_hash: str) -> bool:
        if plan_hash in self._pending:
            self._pending.discard(plan_hash)
            return True
        return False

    @property
    def pending(self) -> frozenset[str]:
        return frozenset(self._pending)


class MCPPort(Protocol):
    async def call(self, name: str, **arguments: Any) -> ToolResult: ...


class InProcessMCP:
    """A real MCP client session over the SDK's in-memory transport.

    Enter and exit it in the same asyncio task. The server should be built with a runner the
    host owns (``create_server(service, runner=...)``).
    """

    def __init__(self, server: Any, approvals: ApprovalBook):
        self.server = server
        self.approvals = approvals
        self._context: Any = None
        self._session: Any = None

    async def __aenter__(self) -> InProcessMCP:
        self._context = create_connected_server_and_client_session(
            self.server, elicitation_callback=approval_callback(self.approvals.consume))
        self._session = await self._context.__aenter__()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        context, self._context, self._session = self._context, None, None
        if context is not None:
            await context.__aexit__(*exc_info)

    async def call(self, name: str, **arguments: Any) -> ToolResult:
        if self._session is None:
            raise ToolFailure("CLIENT_CLOSED", "The MCP session is closed")
        result = await self._session.call_tool(name, arguments)
        text = "".join(block.text for block in result.content if getattr(block, "type", "") == "text")
        if result.isError:
            raise parse_failure(text)
        return ToolResult(dict(result.structuredContent or {}), text)
