"""The web agent host (P4): turns in worker threads, ownership, limits, spend and job following."""

import asyncio
import time

import pytest

from openepw.agent.interactions import Answer, Interaction, Option
from openepw.agent.model_port import ModelReply, ModelUnavailable, ScriptedModel, call, say
from openepw.agent.policy_config import LimitSettings, default_policy
from openepw.agent.web import SpendGuard, WebInput, WebRefusal, WebStore

OWNER = "ip:203.0.113.5"


def idle(host, session_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while host.busy(session_id):
        assert time.monotonic() < deadline, "the turn did not finish"
        time.sleep(0.02)
    return host.snapshot(session_id)


def answer(snapshot, **fields):
    form = snapshot["form"]
    return WebInput(type="answer", answer=Answer(interaction_id=form["id"], revision=form["revision"], **fields))


def step(host, session_id, item):
    host.submit(session_id, OWNER, item)
    return idle(host, session_id)


def finish_jobs(host, session_id, timeout=60.0):
    deadline = time.monotonic() + timeout
    snapshot = host.snapshot(session_id)
    while set(snapshot["job_ids"]) - set(snapshot["finished_job_ids"]):
        assert time.monotonic() < deadline, "the jobs did not finish"
        host.follow_once()
        time.sleep(0.05)
        snapshot = idle(host, session_id)
    return snapshot


def test_guided_session_runs_end_to_end_through_the_host(make_host):
    host = make_host()
    session_id = host.create(OWNER)
    snapshot = idle(host, session_id)
    assert snapshot["mode"] == "guided" and not snapshot["model_available"]
    assert snapshot["form"]["kind"] == "map_input"

    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca NY"))
    assert snapshot["form"]["kind"] == "location_review"
    assert snapshot["places"][0]["name"].startswith("Ithaca") and "standard_offset_minutes" in snapshot["places"][0]

    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["form"]["kind"] == "product_choice"
    offers = {offer["id"]: offer for offer in snapshot["offers"]}
    assert offers["era5-openmeteo"]["group"] == "actual"

    snapshot = step(host, session_id, answer(snapshot, choice_ids=["era5-openmeteo"]))
    assert snapshot["form"]["kind"] == "plan_review"
    assert [part["status"] for part in snapshot["parts"]] == ["confirmed"] * 4

    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["form"] is None and len(snapshot["job_ids"]) == 1
    snapshot = finish_jobs(host, session_id)
    assert snapshot["form"]["gate"] == "next_steps"
    assert snapshot["artifact_ids"]
    texts = [event["text"] for event in host.snapshot(session_id)["events"] if event["type"] == "assistant"]
    assert any("not certified simulation-ready" in text for text in texts)


def test_sessions_belong_to_their_owner(make_host):
    host = make_host()
    session_id = host.create(OWNER)
    idle(host, session_id)
    with pytest.raises(KeyError):
        host.check_owner(session_id, "ip:198.51.100.7")
    with pytest.raises(KeyError):
        host.submit(session_id, "user:someone-else", WebInput(type="text", text="hello"))
    with pytest.raises(KeyError):
        host.check_owner("no-such-session", OWNER)


def test_one_input_at_a_time_per_session(make_host):
    host = make_host()
    session_id = host.create(OWNER)
    idle(host, session_id)
    host._submit(session_id, OWNER, lambda s: asyncio.sleep(0.5))
    with pytest.raises(WebRefusal) as refused:
        host.submit(session_id, OWNER, WebInput(type="text", text="Boston"))
    assert refused.value.code == "SESSION_BUSY" and refused.value.status == 409
    idle(host, session_id)


def test_session_and_input_rates_per_person(make_host):
    host = make_host(limits={"sessions_per_hour": 1, "inputs_per_minute": 2})
    session_id = host.create(OWNER)
    with pytest.raises(WebRefusal) as refused:
        host.create(OWNER)
    assert refused.value.code == "SESSION_LIMIT"
    idle(host, host.create("ip:198.51.100.7"))           # another person is not affected
    idle(host, session_id)
    for text in ("hello", "thanks"):
        step(host, session_id, WebInput(type="text", text=text))
    with pytest.raises(WebRefusal) as refused:
        host.submit(session_id, OWNER, WebInput(type="text", text="Boston"))
    assert refused.value.code == "RATE_LIMIT"


def test_running_jobs_limit_is_checked_at_run_and_retry(make_host):
    host = make_host(limits={"running_jobs": 1})

    class Job:
        state = "running"

    host.runner = type("Runner", (), {"store": type("Store", (), {"get": staticmethod(lambda job_id: Job())})()})()
    host.web.add_jobs(OWNER, "earlier", ["job-1"])
    with pytest.raises(WebRefusal) as refused:
        host._check_running_jobs(OWNER, 1)
    assert refused.value.code == "JOB_LIMIT"
    Job.state = "completed"
    host._check_running_jobs(OWNER, 1)
    # Approving a retry form counts the jobs it would start, like Run.
    session = host.create(OWNER)
    deadline = time.monotonic() + 10
    while host.busy(session) and time.monotonic() < deadline:     # the first step opens its own form
        time.sleep(0.01)
    state = host.store.load(session)
    state.form = Interaction(kind="choice", gate="review_retry", prompt="Retry?", data={"jobs": ["j1", "j2"]},
                             options=[Option(id="retry", label="Retry"), Option(id="cancel", label="Not now")])
    host.store.save(state)
    retry = WebInput(type="answer", answer=Answer(interaction_id=state.form.id, revision=0, choice_ids=["retry"]))
    with pytest.raises(WebRefusal) as refused:
        host.submit(session, OWNER, retry)
    assert refused.value.code == "JOB_LIMIT"


def test_web_input_needs_its_field():
    with pytest.raises(ValueError):
        WebInput(type="text")
    with pytest.raises(ValueError):
        WebInput(type="mode")
    assert WebInput(type="back").type == "back"


def test_spend_guard_stops_at_each_cap_and_records_cost(tmp_path):
    store = WebStore(tmp_path / "web.sqlite")

    def priced(cost):
        return ModelReply(text="ok", cost_usd=cost)

    model = ScriptedModel([priced(0.2), priced(0.2), priced(0.2)])
    security = default_policy().model_copy(update={"limits": LimitSettings(session_usd=0.3)})
    guard = SpendGuard(model, store, security, OWNER, "s1")
    for _ in range(2):
        asyncio.run(guard.respond("system", [], []))
    assert store.spent(session_id="s1") == pytest.approx(0.4)
    with pytest.raises(ModelUnavailable) as stopped:
        asyncio.run(guard.respond("system", [], []))
    assert stopped.value.cause == "budget" and "session" in str(stopped.value)
    daily = default_policy().model_copy(update={"limits": LimitSettings(person_usd_per_day=0.4)})
    assert "your model budget" in SpendGuard(model, store, daily, OWNER, "s2").stopped()
    total = default_policy().model_copy(update={"limits": LimitSettings(total_usd_per_day=0.4)})
    assert "site's model budget" in SpendGuard(model, store, total, "ip:other", "s3").stopped()


def test_a_stopped_budget_switches_the_session_to_guided_mode(make_host):
    model = ScriptedModel([say("Hello")])
    host = make_host(limits={"total_usd_per_day": 0.0}, model=lambda: model)
    session_id = host.create(OWNER)
    snapshot = idle(host, session_id)
    assert snapshot["mode"] == "agent"
    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca NY"))
    assert snapshot["mode"] == "guided"
    notices = [event for event in snapshot["events"] if event["data"].get("code") == "MODEL_UNAVAILABLE"]
    assert notices and notices[-1]["data"]["cause"] == "budget"
    assert snapshot["form"]["kind"] == "location_review"     # guided rules read the message
    assert model.requests == []


def test_agent_mode_turns_record_spend(make_host):
    model = ScriptedModel([call("weather_geocode", {"query": "Ithaca, NY"}),
                           ModelReply(text="Found Ithaca.", cost_usd=0.01)])
    host = make_host(model=lambda: model)
    session_id = host.create(OWNER)
    idle(host, session_id)
    step(host, session_id, WebInput(type="text", text="Where is Ithaca, NY?"))
    assert host.web.spent(session_id=session_id) == pytest.approx(0.01)


def test_each_turn_closes_its_model_client(make_host):
    closed = []

    class Client:
        async def aclose(self):
            closed.append(True)

    def factory():
        model = ScriptedModel([say("Hello")])
        model.client = Client()
        return model

    host = make_host(model=factory)
    session_id = host.create(OWNER)
    idle(host, session_id)
    step(host, session_id, WebInput(type="text", text="Where is Ithaca, NY?"))
    assert len(closed) == 2                                 # the opening turn and the message


def test_candidates_are_listed_for_a_place_choice(make_host):
    host = make_host()
    session_id = host.create(OWNER)
    idle(host, session_id)
    snapshot = step(host, session_id, WebInput(type="text", text="Springfield"))
    assert snapshot["form"]["gate"] == "choose_location"
    assert [item["id"] for item in snapshot["candidates"]] == [option["id"] for option in snapshot["form"]["options"]]
    assert all("lat" in item for item in snapshot["candidates"])


def test_a_model_place_question_lists_its_geocoder_points(make_host):
    model = ScriptedModel([call("weather_geocode", {"query": "Springfield"}),
                           call("ask_choice", {"prompt": "Which Springfield?", "options": [
                               {"id": "1", "label": "Springfield, Illinois"},
                               {"id": "2", "label": "Springfield, Massachusetts"}]})])
    host = make_host(model=lambda: model)
    session_id = host.create(OWNER)
    idle(host, session_id)
    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Springfield"))
    assert snapshot["form"]["gate"] == "ask_choice"
    assert [(item["id"], item["lat"]) for item in snapshot["candidates"]] == [("1", 39.80), ("2", 42.10)]
