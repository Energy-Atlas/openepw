"""Interactive terminal entry point for the local reference agent."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .agent import ReferenceAgent
from .chat import ChatSession, load_model_key
from .mcp_client import MCPToolFailure, StdioMCPPort
from .model import ModelUnavailable, OpenAIIntentParser


async def converse(args) -> None:
    root = Path(args.data_root)
    key = load_model_key(args.env_file)
    model = OpenAIIntentParser(
        key, model=args.model,
        ledger_path=root / "harness" / "cost-ledger.json")
    async with StdioMCPPort(root, allowed_roots=args.allow_root) as mcp:
        agent = ReferenceAgent(
            mcp, model, record_path=root / "harness" / "chat-last-run.json")
        session = ChatSession(agent, mcp, model, auto_submit=not args.manual)
        print("OpenEPW chat. Type /help for commands; /quit to leave.")
        print("New plans execute automatically." if session.auto_submit else
              "New plans pause for review.")
        while not session.exit_requested:
            try:
                line = await asyncio.to_thread(input, "You> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nSession ended. Jobs and artifacts remain in the data root.")
                break
            answer = await session.handle(line)
            if answer:
                print("Agent> " + answer)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="openepw-chat", description="Chat with the local OpenEPW MCP agent")
    parser.add_argument("--data-root", default=".local/openepw")
    parser.add_argument("--env-file", default=".env",
                        help="Read OPENAI_API_KEY from this existing file if unset in shell")
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--allow-root", action="append", default=[])
    parser.add_argument("--manual", action="store_true",
                        help="Show plans before execution; /auto on can change this")
    args = parser.parse_args(argv)
    try:
        asyncio.run(converse(args))
        return 0
    except (ModelUnavailable, MCPToolFailure, OSError) as error:
        if isinstance(error, ModelUnavailable):
            print(f"Model unavailable: {error}")
        elif isinstance(error, MCPToolFailure):
            print(f"MCP {error.code}: {error}")
        else:
            print("Local chat setup failed")
        return 2
