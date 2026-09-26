import asyncio
from types import SimpleNamespace

import pytest

from openepw.harness import chat_cli


class MenuSession:
    def menu(self):
        return [("location:cambridge", "Cambridge"), ("other", "Other…")]


class Prompt:
    def __init__(self, result):
        self.result = result

    async def ask_async(self):
        return self.result


def test_terminal_menu_returns_stable_choice_id(monkeypatch):
    monkeypatch.setattr(chat_cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(chat_cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(chat_cli.questionary, "select",
                        lambda *args, **kwargs: Prompt("location:cambridge"))

    assert asyncio.run(chat_cli._read_line(MenuSession())) == "\0choice:location:cambridge"


def test_other_option_accepts_free_text(monkeypatch):
    monkeypatch.setattr(chat_cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(chat_cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(chat_cli.questionary, "select",
                        lambda *args, **kwargs: Prompt("other"))

    async def typed(*args):
        return "Cambridgeport, Massachusetts"

    monkeypatch.setattr(chat_cli.asyncio, "to_thread", typed)
    assert asyncio.run(chat_cli._read_line(MenuSession())) == "Cambridgeport, Massachusetts"


def test_control_c_dismissal_aborts_menu_instead_of_reopening(monkeypatch):
    monkeypatch.setattr(chat_cli.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(chat_cli.sys, "stdout", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(chat_cli.questionary, "select",
                        lambda *args, **kwargs: Prompt(None))
    with pytest.raises(chat_cli.MenuAborted):
        asyncio.run(chat_cli._read_line(MenuSession()))


def test_progress_printer_reports_changes_and_heartbeat(monkeypatch, capsys):
    now = [0.0]
    monkeypatch.setattr(chat_cli.time, "monotonic", lambda: now[0])
    printer = chat_cli.ProgressPrinter(heartbeat_seconds=5, interactive=False,
                                       bar_width=12)
    update = {"job_id": "job-1", "state": "running", "completed": 0,
              "failed": 0, "total": 3}
    printer(update)
    now[0] = 2.0
    printer(update)
    now[0] = 5.0
    printer(update)
    now[0] = 6.0
    printer({**update, "completed": 1})
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert "[>-----------]" in lines[0]
    assert "output 1/3" in lines[0]
    assert "0 finished" in lines[0]
    assert "still running" in lines[1]
    assert "output 2/3" in lines[2]
    assert "1 finished" in lines[2]


def test_progress_bar_updates_one_terminal_line_and_ends_before_reply(capsys):
    printer = chat_cli.ProgressPrinter(interactive=True, bar_width=7)
    printer({"job_id": "job-1", "state": "running", "completed": 0,
             "failed": 0, "total": 7})
    printer({"job_id": "job-1", "state": "running", "completed": 2,
             "failed": 0, "total": 7})
    printer({"job_id": "job-1", "state": "completed", "completed": 7,
             "failed": 0, "total": 7})
    output = capsys.readouterr().out
    assert "\rProgress> [>------]" in output
    assert "output 1/7" in output
    assert "\rProgress> [##>----]" in output
    assert "output 3/7" in output
    assert "\rProgress> [#######]" in output
    assert output.endswith("\n")
    assert output.count("\n") == 1


def test_progress_bar_counts_failed_outputs_as_processed(capsys):
    printer = chat_cli.ProgressPrinter(interactive=False, bar_width=7)
    printer({"job_id": "job-1", "state": "running", "completed": 3,
             "failed": 1, "total": 7})
    output = capsys.readouterr().out
    assert "[####>--]" in output
    assert "output 5/7" in output
    assert "3 finished, 1 failed" in output


def test_queued_bar_does_not_claim_first_output_has_started(capsys):
    printer = chat_cli.ProgressPrinter(interactive=False, bar_width=7)
    printer({"job_id": "job-1", "state": "queued", "completed": 0,
             "failed": 0, "total": 7})
    output = capsys.readouterr().out
    assert "[-------]" in output
    assert "waiting to start" in output
    assert "output 1/7" not in output


def test_interrupt_requests_cancellation_only_for_active_job():
    class Port:
        def __init__(self, state):
            self.state = state
            self.calls = []

        async def call(self, name, **arguments):
            self.calls.append((name, arguments))
            if name == "job_inspect":
                return {"state": self.state}
            if name == "job_cancel":
                return {"cancellation_requested": True}
            raise AssertionError(name)

    agent = SimpleNamespace(job_id="job-1")
    active = Port("running")
    assert asyncio.run(chat_cli._cancel_active_job(active, agent)) is True
    assert [name for name, _ in active.calls] == ["job_inspect", "job_cancel"]
    complete = Port("completed")
    assert asyncio.run(chat_cli._cancel_active_job(complete, agent)) is False
    assert [name for name, _ in complete.calls] == ["job_inspect"]


def test_interrupt_during_download_requests_job_cancellation(monkeypatch, tmp_path):
    calls = []

    class Port:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def call(self, name, **arguments):
            calls.append(name)
            if name == "job_inspect":
                return {"state": "running"}
            if name == "job_cancel":
                return {"cancellation_requested": True}
            raise AssertionError(name)

    class Session:
        def __init__(self, agent, *args, **kwargs):
            agent.job_id = "job-1"
            self.exit_requested = False
            self.auto_submit = True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def handle(self, line):
            raise asyncio.CancelledError

    async def line(_):
        return "download 2012 weather"

    monkeypatch.setattr(chat_cli, "load_model_key", lambda _: "test-key")
    monkeypatch.setattr(chat_cli, "load_trace_key", lambda _: None)
    monkeypatch.setattr(chat_cli, "LangChainTurnParser", lambda *a, **k: object())
    monkeypatch.setattr(chat_cli, "ConsoleMCPPort", lambda *a, **k: Port())
    monkeypatch.setattr(chat_cli, "GraphChatSession", Session)
    monkeypatch.setattr(chat_cli, "_read_line", line)
    args = SimpleNamespace(env_file=".env", model="stub", allow_root=[],
                           thread_id="console", manual=False, no_trace=True,
                           trace_project="unused")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(chat_cli._converse_locked(args, tmp_path))
    assert calls == ["job_inspect", "job_cancel"]
