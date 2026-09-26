"""Interactive terminal entry point for the local reference agent."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from pathlib import Path
from typing import Any

import questionary

from .agent import ReferenceAgent
from .chat import load_model_key, load_trace_key
from .console_port import ConsoleMCPPort
from .graph_chat import GraphChatSession
from .graph_model import LangChainTurnParser
from .mcp_client import MCPToolFailure
from .model import ModelUnavailable
from .session_lock import SessionBusy, session_lock
from .trace import LangSmithTrace, TracingMCPPort


class MenuAborted(Exception):
    """The user dismissed a choice prompt with Ctrl+C."""


class ProgressPrinter:
    def __init__(self, *, heartbeat_seconds: float = 5.0,
                 interactive: bool | None = None, bar_width: int = 20):
        self.heartbeat_seconds = heartbeat_seconds
        self.interactive = sys.stdout.isatty() if interactive is None else interactive
        self.bar_width = bar_width
        self.last_snapshot: tuple[str, str, int, int, int] | None = None
        self.last_print_at: float | None = None
        self.started_at: float | None = None
        self.last_line_width = 0
        self.line_open = False

    def finish(self) -> None:
        if self.interactive and self.line_open:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self.line_open = False
            self.last_line_width = 0

    def _line(self, update: dict[str, Any], elapsed: int, heartbeat: bool) -> str:
        total = max(0, int(update["total"]))
        completed = max(0, int(update["completed"]))
        failed = max(0, int(update["failed"]))
        processed = min(total, completed + failed)
        filled = self.bar_width * processed // total if total else 0
        active = update["state"] == "running" and processed < total
        bar = ("#" * filled + (">" if active else "") +
               "-" * (self.bar_width - filled - int(active)))
        if active:
            detail = f"output {processed + 1}/{total}"
        elif update["state"] == "queued":
            detail = "waiting to start"
        elif total:
            detail = f"{processed}/{total} processed"
        else:
            detail = "preparing"
        suffix = f"; still {update['state']}" if heartbeat else ""
        return (f"Progress> [{bar}] {update['state']}: {detail}; "
                f"{completed} finished, {failed} failed; {elapsed}s{suffix}")

    def __call__(self, update: dict[str, Any]) -> None:
        now = time.monotonic()
        if self.started_at is None or (self.last_snapshot is not None and
                                       update["job_id"] != self.last_snapshot[0]):
            self.finish()
            self.started_at = now
            self.last_print_at = None
            self.last_snapshot = None
        snapshot = (update["job_id"], update["state"], update["completed"],
                    update["failed"], update["total"])
        changed = snapshot != self.last_snapshot
        heartbeat = (not changed and update["state"] in ("queued", "running")
                     and self.last_print_at is not None
                     and now - self.last_print_at >= self.heartbeat_seconds)
        if changed or heartbeat:
            started_at = self.started_at if self.started_at is not None else now
            line = self._line(update, int(now - started_at), heartbeat)
            if self.interactive:
                sys.stdout.write("\r" + line +
                                 " " * max(0, self.last_line_width - len(line)))
                sys.stdout.flush()
                self.last_line_width = len(line)
                self.line_open = True
            else:
                print(line, flush=True)
            self.last_print_at = now
        self.last_snapshot = snapshot
        if update["state"] not in ("queued", "running"):
            self.finish()


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
            raise MenuAborted
    return await asyncio.to_thread(input, "You> ")


async def _cancel_active_job(port, agent: ReferenceAgent) -> bool:
    if not agent.job_id:
        return False
    try:
        job = await asyncio.wait_for(
            port.call("job_inspect", job_id=agent.job_id), timeout=5)
        if job.get("state") not in ("queued", "running"):
            return False
        await asyncio.wait_for(
            port.call("job_cancel", job_id=agent.job_id), timeout=5)
    except (MCPToolFailure, OSError, asyncio.TimeoutError):
        print(f"Could not confirm cancellation of job {agent.job_id}; "
              "check /status when you resume.")
        return False
    print(f"Cancellation requested for job {agent.job_id}.")
    return True


async def converse(args) -> None:
    root = Path(args.data_root)
    with session_lock(root, args.thread_id):
        await _converse_locked(args, root)


async def _converse_locked(args, root: Path) -> None:
    key = load_model_key(args.env_file)
    model = LangChainTurnParser(
        key, model=args.model,
        ledger_path=root / "harness" / "cost-ledger.json")
    progress = ProgressPrinter()
    async with ConsoleMCPPort(
            root, allowed_roots=args.allow_root,
            before_message=progress.finish) as mcp:
        trace_key = None if args.no_trace else load_trace_key(args.env_file)
        tracer = (LangSmithTrace(trace_key, project=args.trace_project)
                  if trace_key else None)
        port = TracingMCPPort(mcp, tracer) if tracer else mcp
        record_name = ("chat-last-run.json" if args.thread_id == "console" else
                       "chat-" + hashlib.sha256(args.thread_id.encode()).hexdigest()[:16]
                       + "-last-run.json")
        record = root / "harness" / record_name
        agent = (ReferenceAgent.restore(
            port, model, record, on_progress=progress, stream_jobs=True)
            if record.is_file() else ReferenceAgent(
                port, model, record_path=record, on_progress=progress,
                stream_jobs=True))
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
                    if line.startswith("\0choice:"):
                        answer = await session.handle_choice(line[len("\0choice:"):])
                    else:
                        answer = await session.handle(line)
                    if answer:
                        progress.finish()
                        print("Agent> " + answer)
                    if tracer and tracer.failed and not warned:
                        print("LangSmith tracing failed; the chat will continue without traces.")
                        warned = True
            except (KeyboardInterrupt, MenuAborted):
                progress.finish()
                await _cancel_active_job(port, agent)
                print("\nSession ended. Completed artifacts remain in the data root.")
            except asyncio.CancelledError:
                progress.finish()
                await _cancel_active_job(port, agent)
                raise
            finally:
                progress.finish()
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
    except KeyboardInterrupt:
        print("\nSession interrupted. Completed artifacts remain in the data root.")
        return 130
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
