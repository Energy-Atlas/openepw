"""Text rendering of agent events and forms, and the `openepw chat` loop."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable

from ..jobs.worker import JobRunner
from ..models import OpenEPWError
from .guided import GuidedPolicy
from .interactions import Answer, Event, Interaction
from .mcp_port import ApprovalBook, InProcessMCP
from .session import AgentSession
from .store import SessionStore

HELP = ("Type a weather request, or answer the current form.\n"
        "/back  /new  /upload <path to .epw>  /status  /mode  /help  /quit\n"
        "EPW bytes stay out of the conversation; review QC before simulation.")
_NUMBERS = re.compile(r"\d+(?:\s*,\s*\d+)*")


def render_form(form: Interaction) -> str:
    lines = ["? " + form.prompt]
    if form.summary:
        lines.append(form.summary)
    if form.kind in ("choice", "product_choice"):
        lines.extend(f"  {index}. {option.label}" + (f" — {option.detail}" if option.detail else "")
                     for index, option in enumerate(form.options, start=1))
        lines.append("Reply with numbers separated by commas." if form.multi else "Reply with a number.")
    elif form.kind == "location_review":
        lines.append("Type 'a' to approve, or describe a change (e.g. 'remove 2' or another place).")
    elif form.kind == "plan_review":
        lines.append("Type 'run' to start retrieval, or describe a change.")
    elif form.kind == "upload":
        lines.append("Use /upload <path to .epw>.")
    elif form.data.get("hint"):
        lines.append(str(form.data["hint"]))
    return "\n".join(lines)


def render_event(event: Event) -> str | None:
    if event.type in ("user", "form"):
        return None
    if event.type == "tool":
        return None if event.data.get("phase") == "call" else "  · " + event.text.splitlines()[0]
    prefix = {"assistant": "", "job": "[job] ", "view": "[view] ", "notice": "! ", "error": "✗ "}[event.type]
    return prefix + event.text


def parse_reply(form: Interaction, line: str) -> Answer | None:
    """A reply that answers the form directly; None means read it as text."""
    reply = line.strip()
    base = {"interaction_id": form.id, "revision": form.revision}
    if form.kind in ("choice", "product_choice") and _NUMBERS.fullmatch(reply):
        indices = [int(item) for item in reply.split(",")]
        if not form.multi and len(indices) != 1:
            return None
        if not all(1 <= index <= len(form.options) for index in indices):
            return None
        return Answer(**base, choice_ids=[form.options[index - 1].id for index in indices])
    if form.kind == "location_review" and reply.casefold() in ("a", "approve", "yes", "y", "ok"):
        return Answer(**base, approve=True)
    if form.kind == "plan_review" and reply.casefold() in ("run", "r", "yes", "go"):
        return Answer(**base, approve=True)
    return None


async def main_chat(service: Any, *, session_id: str | None = None,
                    read: Callable[[str], str] = input, write: Callable[[str], Any] = print,
                    poll_seconds: float = 0.5) -> int:
    from ..mcp.server import create_server

    runner = JobRunner(service)
    try:
        runner.recover()
    except OpenEPWError as error:
        write(f"✗ {error.issue.code}: {error.issue.message}")
        runner.close()
        return 2
    approvals = ApprovalBook()
    store = SessionStore(Path(service.config.data_root) / "agent" / "sessions.sqlite")
    if session_id:
        try:
            store.load(session_id)
        except KeyError:
            write(f"✗ SESSION_NOT_FOUND: no saved chat session {session_id} in this data root")
            runner.close()
            return 2
    seen = 0
    try:
        async with InProcessMCP(create_server(service, runner=runner), approvals) as port:
            policy = GuidedPolicy()
            session = (AgentSession.resume(store, port, approvals, policy, session_id, poll_seconds=poll_seconds)
                       if session_id else
                       AgentSession.start(store, port, approvals, policy, poll_seconds=poll_seconds))
            write(f"OpenEPW chat (guided mode) · session {session.id}. Type /help for commands.")
            await session.begin()

            def flush() -> None:
                nonlocal seen
                for event in session.events(seen):
                    seen = event.seq
                    shown = render_event(event)
                    if shown:
                        write(shown)

            flush()
            if session.form:
                write(render_form(session.form))
            while True:
                pending = [job for job in session.facts.job_ids if job not in session.facts.finished_job_ids]
                if pending:
                    await session.follow_jobs(on_update=flush)
                    flush()
                    if session.form:
                        write(render_form(session.form))
                try:
                    line = await asyncio.to_thread(read, "> ")
                except (EOFError, KeyboardInterrupt):
                    break
                command, _, argument = line.strip().partition(" ")
                before = session.form
                if command in ("/quit", "/exit"):
                    break
                if command == "/help":
                    write(HELP)
                    continue
                if command == "/mode":
                    write("Guided mode: rule-based forms. Agent mode arrives with the model loop.")
                    continue
                if command == "/status":
                    write(f"Jobs: {', '.join(session.facts.job_ids) or 'none'}")
                    continue
                if command == "/back":
                    await session.back()
                elif command == "/new":
                    await session.new_request()
                elif command == "/upload":
                    path = Path(argument.strip().strip('"')).expanduser()
                    if not path.is_file():
                        write("✗ No such file.")
                        continue
                    await session.upload_epw(path.read_bytes(), path.name)
                else:
                    answer = parse_reply(session.form, line) if session.form else None
                    if answer is not None:
                        await session.answer(answer)
                    else:
                        await session.send_text(line)
                flush()
                if session.form and session.form != before:
                    write(render_form(session.form))
            # Inside the client block so `session` is always bound when this runs.
            write(f"Session {session.id} saved. Resume with: openepw chat --session {session.id}")
    finally:
        runner.close()
    return 0
