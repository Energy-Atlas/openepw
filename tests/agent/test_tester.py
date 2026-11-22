"""The tester account's treatment in the web agent host (ADR 0006, owner 2026-11-16): its own
limits and spend cap, spend left out of the site total, sessions removed after a day, and opt-in
stub sessions on the eval stub providers."""

import time
from types import SimpleNamespace

import pytest
from test_web_host import answer, idle

from openepw.agent.moderation import FLAG_MARKER
from openepw.agent.policy_config import LimitSettings, TesterSettings, default_policy, load_policy
from openepw.agent.web import AgentHost, SpendGuard, StubChoice, WebInput, WebRefusal
from openepw.api.agent_routes import owner_of, stub_backend, task_script

TESTER = "tester:tester"
PERSON = "user:7"


MODEL = SimpleNamespace(name="no-calls")


def step(host, session_id, item, owner=TESTER):
    host.submit(session_id, owner, item)
    return idle(host, session_id)


class Clock:
    def __init__(self):
        self.now = time.time()

    def __call__(self):
        return self.now


@pytest.fixture
def tester_host(tmp_path):
    hosts = []

    def build(*, limits=None, tester=None, model=None, clock=time.time, policy=None):
        from openepw.agent.evals.stubs import stub_service
        from openepw.jobs.worker import JobRunner
        from openepw.mcp.server import create_server

        service = stub_service(tmp_path / "data")
        runner = JobRunner(service)
        security = (policy or default_policy()).model_copy(update={
            "limits": LimitSettings(**(limits or {})), "tester": TesterSettings(**(tester or {}))})
        host = AgentHost(service.config.data_root, runner, create_server(service, runner=runner),
                         security=security, model_factory=model, poll_seconds=0.05, clock=clock,
                         stub_backend=stub_backend,
                         scripted_model=task_script)
        hosts.append((host, runner))
        return host

    yield build
    for host, runner in hosts:
        host.close()
        runner.close()


def test_the_tester_owner_comes_from_the_account_gate():
    request = SimpleNamespace(state=SimpleNamespace(tester_name="tester", user_id=3), headers={}, client=None)
    assert owner_of(request) == TESTER
    request.state = SimpleNamespace(user_id=3)
    assert owner_of(request) == "user:3"


def test_the_hosted_profile_caps_the_tester_at_about_a_dollar_a_run():
    tester = load_policy("hosted").tester
    assert tester.session_usd == 1.00 and tester.person_usd_per_day == 3.00
    assert tester.keep_hours == 24 and tester.stub_mode and tester.total_usd_per_day is None


def test_the_tester_has_its_own_limits(tester_host):
    host = tester_host(limits={"sessions_per_hour": 1}, tester={"sessions_per_hour": 3})
    host.create(PERSON)
    with pytest.raises(WebRefusal):
        host.create(PERSON)
    for _ in range(3):
        idle(host, host.create(TESTER))
    with pytest.raises(WebRefusal):
        host.create(TESTER)


def test_tester_spend_has_its_own_cap_and_is_left_out_of_the_site_total(tester_host):
    host = tester_host(limits={"total_usd_per_day": 1.0}, tester={"session_usd": 1.0})
    host.web.record_spend(TESTER, "t1", 0.95)
    person = SpendGuard(MODEL, host.web, host.security, PERSON, "p1")
    assert person.stopped() is None                       # the tester's spend is not the site's
    host.web.record_spend(TESTER, "t1", 0.10)
    assert SpendGuard(MODEL, host.web, host.security, TESTER, "t1").stopped() == \
        "this session's model budget is used up"
    host.web.record_spend(PERSON, "p1", 1.0)
    assert person.stopped() == "the site's model budget for today is used up"


def test_stub_sessions_are_for_the_tester_only(tester_host):
    host = tester_host()
    with pytest.raises(WebRefusal) as refused:
        host.create(PERSON, stub=StubChoice())
    assert refused.value.code == "STUB_NOT_ALLOWED" and refused.value.status == 403
    off = tester_host(tester={"stub_mode": False})
    with pytest.raises(WebRefusal):
        off.create(TESTER, stub=StubChoice())
    with pytest.raises(WebRefusal) as unknown:
        host.create(TESTER, stub=StubChoice(task="S9999", mode="agent"))
    assert unknown.value.code == "UNKNOWN_TASK"
    with pytest.raises(ValueError):
        StubChoice(mode="agent")                            # agent mode needs a task's script


def test_a_guided_stub_session_runs_on_the_stub_providers(tester_host, tmp_path):
    host = tester_host()
    session_id = host.create(TESTER, stub=StubChoice())
    snapshot = idle(host, session_id)
    assert snapshot["mode"] == "guided"
    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca, NY"))
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    snapshot = step(host, session_id, answer(snapshot, choice_ids=["era5-openmeteo"]))
    assert snapshot["form"]["gate"] == "review_plan"
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["job_ids"]
    # The job is the stub runner's, in the session's own folder; the real runner never saw it.
    assert (tmp_path / "data" / "tester-stub" / session_id[:12]).is_dir()
    with pytest.raises(Exception):
        host.runner.store.get(snapshot["job_ids"][0])


def test_stub_sessions_run_under_a_profile_that_blocks_unmoderated_input(tester_host):
    """Staging (hosted profile, moderation.on_error: block) refused every typed text of a stub
    session, which had no moderation at all (staging tests, 2026-11-22). Stub sessions use the
    offline stub moderation: nothing goes to OpenAI and the stub's flag marker is still caught."""
    hosted = load_policy("hosted")
    assert hosted.moderation.enabled and hosted.moderation.on_error == "block"
    host = tester_host(policy=hosted)                     # no moderation_factory: no OpenAI key
    session_id = host.create(TESTER, stub=StubChoice())
    idle(host, session_id)
    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca, NY"))
    assert snapshot["form"]["gate"] == "review_location"
    assert not any("could not be checked by moderation" in event["text"] for event in snapshot["events"])
    flagged = host.create(TESTER, stub=StubChoice())
    idle(host, flagged)
    snapshot = step(host, flagged, WebInput(type="text", text=f"AMY 2018 for Ithaca {FLAG_MARKER}"))
    assert snapshot["strikes"] == 1
    assert any("withheld by moderation" in event["text"] for event in snapshot["events"])


def test_an_agent_stub_session_follows_its_task_script_across_turns(tester_host):
    host = tester_host()
    session_id = host.create(TESTER, stub=StubChoice(task="S1", mode="agent"))
    snapshot = idle(host, session_id)
    assert snapshot["mode"] == "agent"
    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca NY"))
    assert snapshot["form"]["gate"] == "review_location"
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["form"]["gate"] == "choose_products"
    snapshot = step(host, session_id, answer(snapshot, choice_ids=["era5-openmeteo"]))
    assert snapshot["form"]["gate"] == "review_plan"          # the script's next steps, not a new script
    assert host.web.spent(owner=TESTER) == 0


def test_tester_sessions_are_removed_after_keep_hours(tester_host):
    clock = Clock()
    host = tester_host(tester={"keep_hours": 1}, clock=clock)
    old, person = host.create(TESTER), host.create(PERSON)
    idle(host, old), idle(host, person)
    clock.now += 1800
    recent = host.create(TESTER)
    idle(host, recent)
    clock.now += 2400                                       # old is 70 minutes old, recent 40
    assert host.purge_testers() == [old]
    with pytest.raises(KeyError):
        host.check_owner(old, TESTER)
    host.check_owner(recent, TESTER)
    host.check_owner(person, PERSON)                        # other people's sessions are untouched


def _run_s65(host):
    session_id = host.create(TESTER, stub=StubChoice(task="S65", mode="guided"))
    snapshot = idle(host, session_id)
    snapshot = step(host, session_id, WebInput(type="text", text="Boston, Denver 2016"))
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    snapshot = step(host, session_id, answer(snapshot, choice_ids=["era5-openmeteo"]))
    step(host, session_id, answer(snapshot, approve=True))
    deadline = time.monotonic() + 60
    while True:
        snapshot = idle(host, session_id)
        finished = snapshot["job_ids"] and set(snapshot["job_ids"]) <= set(snapshot["finished_job_ids"])
        if finished and snapshot["form"] is not None:              # the summary and "What next?"
            return session_id
        assert time.monotonic() < deadline, "the stub job did not finish"
        host.follow_once()
        time.sleep(0.05)


def test_each_stub_session_gets_its_task_setup_afresh(tester_host, tmp_path):
    # Staging preview, 2026-11-16: a shared stub backend failed Boston only in the first session.
    host = tester_host()
    for _ in range(2):
        session_id = _run_s65(host)
        events = host.store.events(session_id)
        said = [event.text[:90] for event in events if event.type in ("assistant", "error")]
        assert any("1 failed" in text for text in said), said


def test_removing_a_stub_session_removes_its_stub_folder(tester_host, tmp_path):
    clock = Clock()
    host = tester_host(tester={"keep_hours": 1}, clock=clock)
    session_id = host.create(TESTER, stub=StubChoice())
    idle(host, session_id)
    step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca, NY"))
    folder = tmp_path / "data" / "tester-stub" / session_id[:12]
    assert folder.is_dir()
    clock.now += 7200
    assert host.purge_testers() == [session_id] and not folder.exists()
