"""Real local stdio MCP transport for the reference agent."""

from __future__ import annotations

import base64
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPToolFailure(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class StdioMCPPort:
    def __init__(self, data_root: str | Path, *,
                 allowed_roots: list[str | Path] | None = None):
        self.data_root = Path(data_root)
        self.allowed_roots = allowed_roots or []
        self.stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None

    async def __aenter__(self):
        self.stack = AsyncExitStack()
        await self.stack.__aenter__()
        args = ["-c", "from openepw.cli.main import main; raise SystemExit(main())",
                "--data-root", str(self.data_root), "mcp"]
        for root in self.allowed_roots:
            args.extend(["--allow-root", str(root)])
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("OPENAI_API_KEY", "LANGCHAIN_API_KEY",
                                      "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2")}
        params = StdioServerParameters(command=sys.executable, args=args, env=environment)
        reader, writer = await self.stack.enter_async_context(stdio_client(params))
        self.session = await self.stack.enter_async_context(ClientSession(reader, writer))
        assert self.session is not None
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        assert self.stack is not None
        await self.stack.__aexit__(exc_type, exc, tb)
        self.session = None

    async def call(self, name: str, **arguments: Any) -> dict[str, Any]:
        if self.session is None:
            raise MCPToolFailure("CLIENT_CLOSED", "MCP client session is closed")
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            try:
                raw = result.content[0].text
                payload = json.loads(raw[raw.index("{"):])
                code = payload.get("code", "MCP_TOOL_ERROR")
                message = payload.get("message", "MCP tool failed")
            except (AttributeError, IndexError, ValueError, TypeError):
                code, message = "MCP_TOOL_ERROR", "MCP tool failed"
            raise MCPToolFailure(code, message)
        if result.structuredContent is not None:
            return result.structuredContent
        try:
            return json.loads(result.content[0].text)
        except (AttributeError, IndexError, ValueError, TypeError):
            raise MCPToolFailure("INVALID_MCP_RESULT", "MCP tool returned no JSON") from None

    async def upload_file(self, path: str | Path) -> str:
        """Read the EPW out of band; never place its bytes in model input or run logs."""
        source = Path(path)
        if not source.is_file() or source.stat().st_size > 5_000_000:
            raise MCPToolFailure("INVALID_BASELINE", "EPW file missing or exceeds 5 MB")
        body = source.read_bytes()
        result = await self.call(
            "baseline_upload", content_base64=base64.b64encode(body).decode("ascii"))
        return result["artifact_id"]
