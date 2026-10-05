"""Call the openepw MCP server through a real in-memory client session in tests."""

import asyncio

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, ElicitResult


def session_call(server, name, arguments, *, approve=None) -> CallToolResult:
    """approve=None: the client cannot confirm; True/False: it accepts or declines."""

    async def answer(context, params):
        if approve:
            return ElicitResult(action="accept", content={"approve": True})
        return ElicitResult(action="decline")

    async def run():
        async with create_connected_server_and_client_session(
                server, elicitation_callback=answer if approve is not None else None) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())
