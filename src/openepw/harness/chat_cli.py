"""Interactive terminal entry point for the local reference agent."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

import questionary

from .agent import ReferenceAgent
from .chat import load_model_key, load_trace_key
from .graph_chat import GraphChatSession
from .graph_model import LangChainTurnParser
from .mcp_client import MCPToolFailure, StdioMCPPort
from .model import ModelUnavailable
from .session_lock import SessionBusy, session_lock
from .trace import LangSmithTrace, TracingMCPPort


async def _read_line(session: GraphChatSession) -> str:
    choices = session.menu()
    if choices and sys.stdin.isatty() and sys.stdout.isatty():
        answer = await questionary.select(
            "Choose one (or Other to type an answer)",
            choices=[questionary.Choice(label, value=value) for value, label in choices],
            use_arrow_keys=True,
        ).ask_async()
        if answer and answer != "other":
            return "\0choice:" + answer
        if answer is None:
            return ""
    return await asyncio.to_thread(input, "You> ")


async def converse(args) -> None:
    root = Path(args.data_root)
    with session_lock(root, args.thread_id):
        await _converse_locked(args, root)


async def _converse_locked(args, root: Path) -> None:
    key = load_model_key(args.env_file)
    model = LangChainTurnParser(
        key, model=args.model,
        ledger_path=root / "harness" / "cost-ledger.json")
    async with StdioMCPPort(root, allowed_roots=args.allow_root) as mcp:
        trace_key = None if args.no_trace else load_trace_key(args.env_file)
        tracer = (LangSmithTrace(trace_key, project=args.trace_project)
                  if trace_key else None)
        port = TracingMCPPort(mcp, tracer) if tracer else mcp
        record_name = ("chat-last-run.json" if args.thread_id == "console" else
                       "chat-" + hashlib.sha256(args.thread_id.encode()).hexdigest()[:16]
                       + "-last-run.json")
        record = root / "harness" / record_name
        agent = (ReferenceAgent.restore(port, model, record) if record.is_file()
                 else ReferenceAgent(port, model, record_path=record))
        async with GraphChatSession(
                agent, port, model, root / "harness" / "chat-checkpoints.sqlite",
                thread_id=args.thread_id, auto_submit=not args.manual,
                tracer=tracer) as session:
            print("OpenEPW chat. Type /help for commands; /quit to leave.")
            print("New plans execute automatically." if session.auto_submit else
                  "New plans pause for review.")
            if tracer:
                print(f"LangSmith tracing on: {args.trace_project}.")
            warned = False
            try:
                while not session.exit_requested:
                    try:
                        line = await _read_line(session)
                    except EOFError:
                        break
                    except KeyboardInterrupt:
                        print("\nSession ended. Jobs and artifacts remain in the data root.")
                        break
                    if line.startswith("\0choice:"):
                        answer = await session.handle_choice(line[len("\0choice:"):])
                    else:
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
    parser.add_argument("--thread-id", default="console",
                        help="Local conversation ID; reuse it to resume saved choices")
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
    except (ModelUnavailable, MCPToolFailure, SessionBusy, OSError) as error:
        if isinstance(error, ModelUnavailable):
            print(f"Model unavailable: {error}")
        elif isinstance(error, MCPToolFailure):
            print(f"MCP {error.code}: {error}")
        elif isinstance(error, SessionBusy):
            print(str(error))
        else:
            print("Local chat setup failed")
        return 2
