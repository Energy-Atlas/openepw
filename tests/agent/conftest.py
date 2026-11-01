import pytest

from openepw.agent.evals.stubs import stub_service
from openepw.agent.policy_config import LimitSettings, default_policy
from openepw.agent.web import AgentHost
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server


@pytest.fixture
def make_host(tmp_path):
    """Web agent hosts (P4) on the offline stub providers, closed after the test."""
    hosts = []

    def build(*, limits=None, model=None):
        service = stub_service(tmp_path / "data")
        runner = JobRunner(service)
        security = default_policy()
        if limits is not None:
            security = security.model_copy(update={"limits": LimitSettings(**limits)})
        host = AgentHost(service.config.data_root, runner, create_server(service, runner=runner),
                         security=security, model_factory=model, poll_seconds=0.05)
        hosts.append((host, runner))
        return host

    yield build
    for host, runner in hosts:
        host.close()
        runner.close()
