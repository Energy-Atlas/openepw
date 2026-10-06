"""Text rendering of agent events and forms, and the `openepw chat` loop."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Callable

from ..jobs.worker import JobRunner
from ..models import OpenEPWError
from .guided import GuidedPolicy
from .interactions import Answer, Event, Interaction
from .mcp_port import ApprovalBook, InProcessMCP
from .model_port import DEFAULT_MODEL, ModelPort, ModelUnavailable, OpenAIModel, load_openai_key
from .policy_model import ModelPolicy
from .session import MAX_UPLOAD, AgentSession, Policy
from .store import SessionStore
from .tracing import NullTracer, make_tracer, tracing_settings

HELP = ("Type a weather request, or answer the current form.\n"
        "/back  /new  /upload <path to .epw>  /status  /mode [agent|guided]  /help  /quit\n"
        "EPW bytes stay out of the conversation; review QC before simulation.")
_NUMBERS = re.compile(r"\d+(?:\s*,\s*\d+)*")


def prepare_console(stream: Any = None) -> None:
    """Keep the chat readable: no per-request SDK or HTTP logs, and no crash on a narrow encoding.

    A redirected Windows stdout uses the ANSI code page, which cannot encode marks such as ✗.
    """
    for name in ("mcp", "httpx"):
        logging.getLogger(name).setLevel(logging.WARNING)
    stream = sys.stdout if stream is None else stream
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")


def chat_model(mode: str | None, *, model: str | None = None, max_cost: float = 5.0,
               data_root: str | Path = ".", env_file: str | Path | None = ".env"
               ) -> tuple[ModelPort | None, str | None]:
    """The model for `openepw chat`, or None for guided mode, with a notice to show.

    Agent mode is the default when an OpenAI key is in the environment or the ignored dotenv
    file; usage is recorded in ``<data root>/agent/model-usage.json`` and stops at ``max_cost``.
    """
    if mode == "guided":
        return None, None
    key = load_openai_key(env_file)
    if not key:
        return None, ("No OPENAI_API_KEY found; using guided mode (rule-based forms)."
                      if mode == "agent" or mode is None else None)
    ledger = Path(data_root) / "agent" / "model-usage.json"
    try:
        chosen = OpenAIModel(key, model=model or DEFAULT_MODEL, max_cost_usd=max_cost, ledger_path=ledger)
    except (ModelUnavailable, TypeError, ValueError):
        return None, (f"The model usage ledger ({ledger}) is unreadable; using guided mode. "
                      "Fix or move it to use agent mode.")
    spent = float(chosen.usage.get("estimated_usd") or 0.0)
    if spent >= max_cost:
        return None, (f"The model budget is used up (${spent:.2f} of --max-cost ${max_cost:.2f}, "
                      f"ledger {ledger}); using guided mode. Raise --max-cost to use agent mode.")
    return chosen, None


def chat_tracer(env_file: str | Path | None = ".env") -> tuple[NullTracer, str | None]:
    """The tracer `openepw chat` uses, decided by LANGSMITH_TRACING in the env file, and a line
    to show: when tracing is on, or when it was asked for but cannot start."""
    settings = tracing_settings(env_file, default_project="openepw-agent")
    if settings.enabled:
        try:
            return make_tracer(settings), f"LangSmith tracing {settings.reason}."
        except Exception as error:                     # a client that cannot start never blocks chat
            return NullTracer(), f"LangSmith tracing is off ({type(error).__name__} starting the client)."
    asked = settings.reason != "LANGSMITH_TRACING is not true"
    return NullTracer(), (f"LangSmith tracing is off: {settings.reason}." if asked else None)


def _read_upload(argument: str, write: Callable[[str], Any]) -> tuple[bytes, str] | None:
    """The EPW to upload, checked for size before it is read; None after telling the person why."""
    path = Path(argument.strip().strip('"')).expanduser()
    try:
        if not path.is_file():
            write("✗ No such file.")
            return None
        if path.stat().st_size > MAX_UPLOAD:
            write("✗ RESOURCE_LIMIT: EPW uploads must be 1 byte to 5 MB.")
            return None
        return path.read_bytes(), path.name
    except OSError as error:
        write(f"✗ Could not read the file ({type(error).__name__}).")
        return None


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
                    poll_seconds: float = 0.5, follow_seconds: float = 120.0,
                    model: ModelPort | None = None, tracer: NullTracer | None = None) -> int:
    """The chat loop; agent mode when a model is given, otherwise guided mode.

    ``tracer`` records LangSmith runs when the env file turns tracing on (see chat_tracer).
    """
    tracer = tracer or NullTracer()
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
            policy: Policy = ModelPolicy(model) if model is not None else GuidedPolicy()
            session = (AgentSession.resume(store, port, approvals, policy, session_id,
                                           poll_seconds=poll_seconds, tracer=tracer)
                       if session_id else
                       AgentSession.start(store, port, approvals, policy, poll_seconds=poll_seconds,
                                          tracer=tracer))
            if model is None and session.state.mode == "agent":
                session.state.mode = "guided"          # a saved agent session without a model
                session.state.pending_call, session.state.turn = None, []
                if session.form is not None and "call_id" in session.form.data:
                    session.close_form()               # the model's question; guided rules ask anew
                session.emit("notice", "No model is configured; continuing in guided mode.", mode="guided")
            write(f"OpenEPW chat ({session.state.mode} mode) · session {session.id}. "
                  "Type /help for commands.")
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
            waited = False
            warned = False
            try:
                while True:
                    if tracer.failed and not warned:
                        warned = True
                        write("! LangSmith tracing failed; the chat continues without traces.")
                    pending = [job for job in session.facts.job_ids
                               if job not in session.facts.finished_job_ids]
                    # Follow running jobs only while no form is open (a partly failed run keeps its
                    # plan review open), and give the prompt back after a bounded wait.
                    if pending and session.form is None and not waited:
                        await session.follow_jobs(timeout=follow_seconds, on_update=flush)
                        flush()
                        if session.form:
                            write(render_form(session.form))
                        elif session.facts.job_ids != session.facts.finished_job_ids:
                            waited = True
                            write("Press Enter to keep following the jobs, or type /status or /quit.")
                    try:
                        # Read on this thread: jobs run on the runner's pool, and Ctrl-C then
                        # arrives here as KeyboardInterrupt instead of cancelling the loop.
                        line = read("> ")
                    except (EOFError, KeyboardInterrupt):
                        break
                    waited = False
                    command, _, argument = line.strip().partition(" ")
                    before = session.form
                    if command in ("/quit", "/exit"):
                        break
                    if command == "/help":
                        write(HELP)
                        continue
                    if command == "/mode":
                        wanted = argument.strip().lower() or (
                            "guided" if session.state.mode == "agent" else "agent")
                        if wanted not in ("agent", "guided"):
                            write("Use /mode, /mode agent or /mode guided.")
                            continue
                        await session.set_mode(wanted)
                        flush()
                        write(f"Mode: {session.state.mode}.")
                        if session.form and session.form != before:
                            write(render_form(session.form))
                        continue
                    if command == "/status":
                        finished = set(session.facts.finished_job_ids)
                        write(f"Mode: {session.state.mode}. Jobs: " + (", ".join(f"{job} ({'finished' if job in finished else 'running'})"
                                                    for job in session.facts.job_ids) or "none"))
                        continue
                    if command == "/back":
                        await session.back()
                    elif command == "/new":
                        await session.new_request()
                    elif command == "/upload":
                        content = _read_upload(argument, write)
                        if content is None:
                            continue
                        await session.upload_epw(*content)
                    else:
                        answer = parse_reply(session.form, line) if session.form else None
                        if answer is not None:
                            await session.answer(answer)
                        else:
                            await session.send_text(line)
                    flush()
                    if session.form and session.form != before:
                        write(render_form(session.form))
            finally:
                # Inside the client block so `session` is always bound when this runs.
                if any(job not in session.facts.finished_job_ids for job in session.facts.job_ids):
                    write("Running jobs finish before the chat exits; they stay in the data root.")
                write(f"Session {session.id} saved. Resume with: openepw chat --session {session.id}")
    finally:
        runner.close()
        tracer.close()                                 # send any traces still queued
    return 0
