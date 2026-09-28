"""Tool steps of a running action are visible before the action finishes."""

import threading

from test_chat_sessions import Service

from openepw.chat.coordinator import ChatCoordinator


def test_steps_show_while_the_action_runs_and_clear_after(tmp_path):
    reading, release = threading.Event(), threading.Event()

    class SlowModel:
        def parse_many(self, text):
            reading.set()
            release.wait(timeout=5)
            return []

    chat = ChatCoordinator(Service(), parser=SlowModel(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    assert chat.progress(state["id"]) == {"steps": []}
    worker = threading.Thread(target=chat.turn, args=(state["id"], "somewhere nice", 0, "one"))
    worker.start()
    assert reading.wait(timeout=5)
    steps = chat.progress(state["id"])["steps"]                      # read while the model is still working
    assert steps == [{"tool": "model", "text": "Reading your message"}]
    release.set()
    worker.join(timeout=5)
    assert chat.progress(state["id"]) == {"steps": []}               # finished: the saved events take over
    saved = chat.get(state["id"])["events"]
    assert not any(event.get("text") == "Reading your message" for event in saved)   # progress only


def test_saved_tool_events_also_show_while_running(tmp_path):
    seen = []

    class Watching(Service):
        def geocode(self, query, *, mode="point"):
            seen.append(chat.progress(state["id"])["steps"])
            return super().geocode(query, mode=mode)

    from test_chat_sessions import Parser

    chat = ChatCoordinator(Watching(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    assert seen == [[{"tool": "model", "text": "Reading your message"},
                     {"tool": "geocode", "text": "Geocoding place"}]]
