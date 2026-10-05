"""Drive an AgentSession in guided mode against the real MCP server with offline fakes."""

from fakes import scenario_service

from openepw.agent.guided import GuidedPolicy
from openepw.agent.interactions import Answer
from openepw.agent.mcp_port import ApprovalBook, InProcessMCP
from openepw.agent.session import AgentSession
from openepw.agent.store import SessionStore
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server


class Harness:
    def __init__(self, tmp_path, session_id=None, policy=None, fail_near=()):
        self.tmp_path = tmp_path
        self.session_id = session_id
        self.policy = policy or GuidedPolicy()
        self.service = scenario_service(tmp_path, fail_near=fail_near)
        self.runner = JobRunner(self.service)
        self.server = create_server(self.service, runner=self.runner)
        self.approvals = ApprovalBook()
        self.store = SessionStore(tmp_path / "agent" / "sessions.sqlite")

    async def __aenter__(self):
        self.port = await InProcessMCP(self.server, self.approvals).__aenter__()
        if self.session_id:
            self.session = AgentSession.resume(self.store, self.port, self.approvals, self.policy,
                                               self.session_id, poll_seconds=0.05)
        else:
            self.session = AgentSession.start(self.store, self.port, self.approvals, self.policy,
                                              poll_seconds=0.05)
        await self.session.begin()
        return self

    async def __aexit__(self, *exc_info):
        await self.port.__aexit__(*exc_info)
        self.runner.close()

    @property
    def form(self):
        return self.session.form

    async def say(self, text):
        await self.session.send_text(text)

    async def choose(self, *ids):
        form = self.form
        await self.session.answer(Answer(interaction_id=form.id, revision=form.revision, choice_ids=list(ids)))

    async def approve(self):
        form = self.form
        await self.session.answer(Answer(interaction_id=form.id, revision=form.revision, approve=True))

    async def reply(self, text):
        form = self.form
        await self.session.answer(Answer(interaction_id=form.id, revision=form.revision, text=text))

    def tools(self):
        return [event.data["tool"] for event in self.session.events()
                if event.type == "tool" and event.data.get("phase") == "call"]

    def texts(self, type):
        return [event.text for event in self.session.events() if event.type == type]


def in_order(sequence, wanted):
    """True when ``wanted`` appears in ``sequence`` in this order (gaps allowed)."""
    remaining = iter(sequence)
    return all(item in remaining for item in wanted)
