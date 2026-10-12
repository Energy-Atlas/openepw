import asyncio

from openepw.agent.interactions import Answer, Interaction, Option
from openepw.agent.mcp_port import ApprovalBook, ToolFailure, ToolResult
from openepw.agent.session import AgentSession
from openepw.agent.store import SessionStore


class Port:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def call(self, name, **arguments):
        self.calls.append(name)
        if self.fail:
            raise ToolFailure("PROVIDER_DOWN", "Provider unavailable", retryable=True)
        return ToolResult({"ok": True}, f"{name} done")


class StepPolicy:
    """Opens form A, then B on any text; records answers."""

    def __init__(self):
        self.answers = []

    async def advance(self, session):
        if session.form is None:
            session.open_form(Interaction(kind="choice", gate="a", prompt="A?",
                                          options=[Option(id="x", label="X")]))

    async def on_text(self, session, text):
        await session.tool("weather_geocode", query=text)
        session.open_form(Interaction(kind="text", gate="b", prompt="B?"))

    async def on_answer(self, session, form, answer):
        self.answers.append(answer.choice_ids)


def make(tmp_path, port=None):
    store = SessionStore(tmp_path / "sessions.sqlite")
    policy = StepPolicy()
    return AgentSession.start(store, port or Port(), ApprovalBook(), policy), store, policy


def test_forms_get_new_revisions_and_events_record_the_turn(tmp_path):
    session, store, _ = make(tmp_path)
    asyncio.run(session.begin())
    first = session.form
    asyncio.run(session.send_text("Ithaca"))
    assert session.form.gate == "b" and session.form.revision > first.revision
    types = [event.type for event in session.events()]
    assert types == ["form", "user", "tool", "tool", "form"]
    assert store.load(session.id).form == session.form


def test_stale_or_foreign_answers_are_refused(tmp_path):
    session, _, policy = make(tmp_path)
    asyncio.run(session.begin())
    form = session.form
    asyncio.run(session.answer(Answer(interaction_id=form.id, revision=form.revision - 1, choice_ids=["x"])))
    assert policy.answers == [] and session.events()[-1].data["code"] == "STALE_FORM"
    asyncio.run(session.answer(Answer(interaction_id=form.id, revision=form.revision, choice_ids=["x"])))
    assert policy.answers == [["x"]]


def test_tool_failures_become_error_events_and_keep_the_form(tmp_path):
    session, _, _ = make(tmp_path, Port(fail=True))
    asyncio.run(session.begin())
    form = session.form
    asyncio.run(session.send_text("Ithaca"))
    assert session.form == form
    assert session.events()[-1].type == "error" and session.events()[-1].data["code"] == "PROVIDER_DOWN"


def test_back_restores_the_previous_form_until_none_is_left(tmp_path):
    session, _, _ = make(tmp_path)
    asyncio.run(session.begin())
    first = session.form
    asyncio.run(session.send_text("Ithaca"))
    asyncio.run(session.back())
    assert session.form.id == first.id and session.form.revision > first.revision
    asyncio.run(session.back())
    assert session.events()[-1].data["code"] == "NOTHING_TO_UNDO"


def test_back_never_crosses_a_started_job(tmp_path):
    session, _, _ = make(tmp_path)
    asyncio.run(session.begin())
    asyncio.run(session.send_text("Ithaca"))
    session.facts.job_ids.append("job-1")
    asyncio.run(session.back())
    assert session.form.gate == "b" and session.events()[-1].data["code"] == "JOB_STARTED"


def test_a_session_resumes_with_its_open_form(tmp_path):
    session, store, policy = make(tmp_path)
    asyncio.run(session.begin())
    resumed = AgentSession.resume(store, Port(), ApprovalBook(), policy, session.id)
    assert resumed.form == session.form


class Broken(StepPolicy):
    def __init__(self, error):
        super().__init__()
        self.error = error

    async def on_text(self, session, text):
        raise self.error


def test_unexpected_policy_errors_become_error_events(tmp_path):
    from openepw.models import OpenEPWError

    store = SessionStore(tmp_path / "sessions.sqlite")
    for error, code in ((OpenEPWError("INVALID_REQUEST", "bad"), "INVALID_REQUEST"),
                        (KeyError("secret-value"), "INTERNAL_ERROR")):
        session = AgentSession.start(store, Port(), ApprovalBook(), Broken(error))
        asyncio.run(session.send_text("Ithaca"))
        last = session.events()[-1]
        assert last.type == "error" and last.data["code"] == code and "secret-value" not in last.text


def test_following_no_jobs_changes_nothing(tmp_path):
    session, _, _ = make(tmp_path)
    asyncio.run(session.begin())
    form = session.form
    asyncio.run(session.follow_jobs())
    assert session.facts.stage == "request" and session.form == form


def test_back_keeps_uploaded_artifacts(tmp_path):
    session, _, _ = make(tmp_path)
    asyncio.run(session.begin())
    asyncio.run(session.send_text("Ithaca"))
    session.facts.artifact_ids.append("artifact-1")
    asyncio.run(session.back())
    assert session.form.gate == "a" and session.facts.artifact_ids == ["artifact-1"]
