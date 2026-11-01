"""`/v2/agent` routes (P4) and parity with the CLI: the same scenario gives the same forms and tools."""

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openepw.agent.cli import main_chat
from openepw.agent.evals.runner import _answer, scripted_model
from openepw.agent.evals.schema import load_tasks
from openepw.agent.evals.stubs import stub_service, synthetic_epw
from openepw.agent.interactions import Answer
from openepw.agent.policy_config import LimitSettings, default_policy
from openepw.agent.store import SessionStore
from openepw.api.app import create_app

TASKS = {task.id: task for task in load_tasks()}
OTHER = {"X-Forwarded-For": "198.51.100.7"}


def client_for(root, *, model=None, security=None):
    app = create_app(stub_service(root), agent_model=model, security_policy=security)
    app.state.agent_host.poll_seconds = 0.05
    return TestClient(app)


def wait_idle(client, session_id, timeout=60.0):
    deadline = time.monotonic() + timeout
    while True:
        state = client.get(f"/v2/agent/sessions/{session_id}/events", params={"poll": 1, "after": 10**9}).json()["state"]
        if not state["busy"]:
            return client.get(f"/v2/agent/sessions/{session_id}").json()
        assert time.monotonic() < deadline, "the turn did not finish"
        time.sleep(0.02)


def send(client, session_id, body):
    response = client.post(f"/v2/agent/sessions/{session_id}/inputs", json=body)
    assert response.status_code == 202, response.text
    return wait_idle(client, session_id)


def sse_frames(text):
    frames = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if not line.startswith(":"))
        if fields:
            frames.append(fields)
    return frames


def test_create_stream_and_answer(tmp_path):
    with client_for(tmp_path) as client:
        created = client.post("/v2/agent/sessions")
        assert created.status_code == 201
        session_id = created.json()["id"]
        snapshot = wait_idle(client, session_id)
        assert snapshot["form"]["kind"] == "map_input" and snapshot["mode"] == "guided"

        stream = client.get(f"/v2/agent/sessions/{session_id}/events", params={"until_idle": 1})
        assert stream.headers["content-type"].startswith("text/event-stream")
        frames = sse_frames(stream.text)
        agent = [frame for frame in frames if frame["event"] == "agent"]
        assert [int(frame["id"]) for frame in agent] == [json.loads(frame["data"])["seq"] for frame in agent]
        assert json.loads(frames[-1]["data"])["form"]["kind"] == "map_input"
        # A reconnect sends Last-Event-ID and gets only newer events.
        again = client.get(f"/v2/agent/sessions/{session_id}/events", params={"until_idle": 1},
                           headers={"Last-Event-ID": agent[-1]["id"]})
        assert [frame["event"] for frame in sse_frames(again.text)] == ["state"]

        snapshot = send(client, session_id, {"type": "text", "text": "AMY 2018 for Ithaca NY"})
        form = snapshot["form"]
        assert form["kind"] == "location_review"
        snapshot = send(client, session_id, {"type": "answer", "answer": {
            "interaction_id": form["id"], "revision": form["revision"], "approve": True}})
        assert snapshot["form"]["kind"] == "product_choice" and snapshot["offers"]
        snapshot = send(client, session_id, {"type": "request"})
        assert snapshot["form"]["kind"] == "request_summary"
        snapshot = send(client, session_id, {"type": "back"})
        assert snapshot["form"]["kind"] == "product_choice"


def test_sessions_are_private_and_inputs_are_validated(tmp_path):
    with client_for(tmp_path) as client:
        session_id = client.post("/v2/agent/sessions").json()["id"]
        wait_idle(client, session_id)
        assert client.get(f"/v2/agent/sessions/{session_id}", headers=OTHER).status_code == 404
        assert client.get(f"/v2/agent/sessions/{session_id}/events", params={"poll": 1},
                          headers=OTHER).status_code == 404
        assert client.post(f"/v2/agent/sessions/{session_id}/inputs", json={"type": "text", "text": "hi"},
                           headers=OTHER).status_code == 404
        assert client.post(f"/v2/agent/sessions/{session_id}/inputs", json={"type": "text"}).status_code == 422
        assert client.post(f"/v2/agent/sessions/{session_id}/inputs", json={"type": "shout"}).status_code == 422


def test_limits_answer_429_with_a_code(tmp_path):
    security = default_policy().model_copy(update={"limits": LimitSettings(sessions_per_hour=1)})
    with client_for(tmp_path, security=security) as client:
        wait_idle(client, client.post("/v2/agent/sessions").json()["id"])
        refused = client.post("/v2/agent/sessions")
        assert refused.status_code == 429 and refused.json()["code"] == "SESSION_LIMIT"
        assert client.post("/v2/agent/sessions", headers=OTHER).status_code == 201


def test_upload_registers_an_epw(tmp_path):
    with client_for(tmp_path) as client:
        session_id = client.post("/v2/agent/sessions").json()["id"]
        wait_idle(client, session_id)
        response = client.post(f"/v2/agent/sessions/{session_id}/upload",
                               files={"file": ("ithaca.epw", synthetic_epw(), "text/plain")})
        assert response.status_code == 202
        snapshot = wait_idle(client, session_id)
        assert snapshot["artifact_ids"]
        assert any("Registered your EPW" in event["text"] for event in snapshot["events"])
        empty = client.post(f"/v2/agent/sessions/{session_id}/upload", files={"file": ("x.epw", b"", "text/plain")})
        assert empty.status_code == 413


# Parity (design §6.3): the CLI loop and /v2 give the same form kinds and tool calls. ----------

def trace(events):
    forms = [event["data"]["form"]["kind"] for event in events if event["type"] == "form"]
    tools = [event["data"]["tool"] for event in events if event["type"] == "tool" and event["data"]["phase"] == "call"]
    return forms, tools


def cli_line(form, reply):
    if isinstance(reply, str):
        return reply
    if reply.approve:
        return "run" if form.kind == "plan_review" else "ok"
    choice = reply.choice_ids[0]
    if choice.startswith("change:"):
        return "change " + choice.split(":", 1)[1]
    ids = [option.id for option in form.options]
    return ",".join(str(ids.index(item) + 1) for item in reply.choice_ids)


def run_cli(root, task, model):
    service = stub_service(root)
    store = SessionStore(Path(service.config.data_root) / "agent" / "sessions.sqlite")
    pending = [task.user.say]
    seen: dict[str, int] = {}

    def read(prompt):
        if pending:
            return pending.pop(0)
        [session_id] = [row for row in store_ids(store)]
        form = store.load(session_id).form
        if form is None or form.gate == "next_steps":
            return "/quit"
        reply = _answer(form, task.user.answers, seen.get(form.kind, 0))
        seen[form.kind] = seen.get(form.kind, 0) + 1
        return "/quit" if reply is None else cli_line(form, reply)

    asyncio.run(main_chat(service, read=read, write=lambda text: None, poll_seconds=0.05,
                          follow_seconds=60, model=model))
    [session_id] = store_ids(store)
    return trace([event.model_dump(mode="json") for event in store.events(session_id)])


def store_ids(store):
    with store._connect() as db:
        return [row[0] for row in db.execute("SELECT id FROM sessions")]


def run_web(root, task, model):
    with client_for(root, model=(lambda: model) if model else None) as client:
        session_id = client.post("/v2/agent/sessions").json()["id"]
        snapshot = wait_idle(client, session_id)
        snapshot = send(client, session_id, {"type": "text", "text": task.user.say})
        seen: dict[str, int] = {}
        for _ in range(task.user.max_interactions):
            if set(snapshot["job_ids"]) - set(snapshot["finished_job_ids"]) and snapshot["form"] is None:
                client.app.state.agent_host.follow_once()
                snapshot = wait_idle(client, session_id)
                continue
            form = snapshot["form"]
            if form is None or form["gate"] == "next_steps":
                break
            from openepw.agent.interactions import Interaction

            interaction = Interaction.model_validate(form)
            reply = _answer(interaction, task.user.answers, seen.get(form["kind"], 0))
            seen[form["kind"]] = seen.get(form["kind"], 0) + 1
            if reply is None:
                break
            answer = reply if isinstance(reply, Answer) else Answer(
                interaction_id=form["id"], revision=form["revision"], text=reply)
            snapshot = send(client, session_id, {"type": "answer", "answer": answer.model_dump(mode="json")})
        events = client.get(f"/v2/agent/sessions/{session_id}/events", params={"poll": 1}).json()["events"]
    return trace(events)


@pytest.mark.parametrize("task_id,mode", [("S1", "guided"), ("S2", "guided"), ("S57", "guided"),
                                          ("S1", "agent"), ("S57", "agent")])
def test_cli_and_web_give_the_same_forms_and_tools(tmp_path, task_id, mode):
    task = TASKS[task_id]
    models = [scripted_model(task), scripted_model(task)] if mode == "agent" else [None, None]
    if mode == "agent" and models[0] is None:
        pytest.skip(f"{task_id} has no offline script")
    cli = run_cli(tmp_path / "cli", task, models[0])
    web = run_web(tmp_path / "web", task, models[1])
    assert cli == web
    assert cli[0], "the scenario showed no form"
