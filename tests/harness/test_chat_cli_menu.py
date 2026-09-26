import asyncio
from types import SimpleNamespace

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
