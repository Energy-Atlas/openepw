"""Call the openepw MCP server through a real in-memory client session in tests."""

import asyncio

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, ElicitResult


def session_call(server, name, arguments, *, approve=None, callback=None) -> CallToolResult:
    """approve=None: the client cannot confirm; True/False: it accepts or declines.

    callback replaces the approve answer with a custom elicitation callback.
    """

    async def answer(context, params):
        if approve:
            return ElicitResult(action="accept", content={"approve": True})
        return ElicitResult(action="decline")

    elicitation = callback or (answer if approve is not None else None)

    async def run():
        async with create_connected_server_and_client_session(
                server, elicitation_callback=elicitation) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())
