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
    assert [(step["text"], step["data"]["tool"]) for step in steps] == [("Reading your message", "model")]
    release.set()
    worker.join(timeout=5)
    assert chat.progress(state["id"]) == {"steps": []}               # finished: the saved events take over
    saved = [event for event in chat.get(state["id"])["events"] if event["type"] == "tool"]
    assert [event["text"] for event in saved] == [step["text"] for step in steps]      # live = saved lines
    assert [event["id"] for event in saved] == [step["id"] for step in steps]


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
    assert [[step["text"] for step in steps] for steps in seen] == [["Reading your message", "Geocoding place"]]
    saved = [event["text"] for event in chat.get(state["id"])["events"] if event["type"] == "tool"]
    assert saved[:2] == ["Reading your message", "Geocoding place"]         # the live lines are the saved ones
