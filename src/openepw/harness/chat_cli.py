"""Interactive terminal entry point for the local reference agent."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .agent import ReferenceAgent
from .chat import ChatSession, load_model_key, load_trace_key
from .mcp_client import MCPToolFailure, StdioMCPPort
from .model import ModelUnavailable, OpenAIIntentParser
from .trace import LangSmithTrace, TracingIntentParser, TracingMCPPort


async def converse(args) -> None:
    root = Path(args.data_root)
    key = load_model_key(args.env_file)
    model = OpenAIIntentParser(
        key, model=args.model, max_calls=None,
        ledger_path=root / "harness" / "cost-ledger.json")
    async with StdioMCPPort(root, allowed_roots=args.allow_root) as mcp:
        trace_key = None if args.no_trace else load_trace_key(args.env_file)
        tracer = (LangSmithTrace(trace_key, project=args.trace_project)
                  if trace_key else None)
        port = TracingMCPPort(mcp, tracer) if tracer else mcp
        parser = TracingIntentParser(model, tracer) if tracer else model
        agent = ReferenceAgent(
            port, parser, record_path=root / "harness" / "chat-last-run.json")
        session = ChatSession(agent, port, parser, auto_submit=not args.manual,
                              tracer=tracer)
        print("OpenEPW chat. Type /help for commands; /quit to leave.")
        print("New plans execute automatically." if session.auto_submit else
              "New plans pause for review.")
        if tracer:
            print(f"LangSmith tracing on: {args.trace_project}.")
        warned = False
        try:
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
                if tracer and tracer.failed and not warned:
                    print("LangSmith tracing failed; the chat will continue without traces.")
                    warned = True
        finally:
            if tracer:
                tracer.close()
                if tracer.failed and not warned:
                    print("LangSmith trace delivery failed.")


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
    parser.add_argument("--no-trace", action="store_true",
                        help="Disable LangSmith traces even when a key is available")
    parser.add_argument("--trace-project", default="openepw-local-chat",
                        help="LangSmith project for console traces")
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
