import asyncio
import json

from test_epw import synthetic
from test_future import signal

from openepw.artifacts.store import ArtifactStore
from openepw.epw.writer import epw_bytes
from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.mcp_client import StdioMCPPort


class StubModel:
    def parse(self, prompt):
        return AgentIntent(
            kind="future", method="morph", climate_scenario="ssp245",
            reference_period=(1985, 2014), climate_period=(2036, 2065),
            signals_artifact_id=self.signals_id)


def test_reference_agent_runs_and_resumes_over_real_stdio_mcp(tmp_path):
    root = tmp_path / "store"
    store = ArtifactStore(root)
    signals = store.write(
        "a" * 32, "signals.json",
        json.dumps([signal().model_dump(mode="json")]).encode(), "signals")
    model = StubModel()
    model.signals_id = signals.id
    file = tmp_path / "user.epw"
    file.write_bytes(epw_bytes(synthetic(2023, 8760)))
    record = tmp_path / "run.json"

    async def run():
        async with StdioMCPPort(root) as mcp:
            baseline_id = await mcp.upload_file(file)
            agent = ReferenceAgent(mcp, model, record_path=record)
            outcome = await agent.run(
                "Morph my uploaded EPW to SSP245 in 2036–2065",
                auto_submit=True, baseline_override=baseline_id)
            assert outcome.status == "completed"
            assert "user_provided" in outcome.message
            assert "simulation_ready=false" in outcome.message
            assert outcome.artifact_ids
            first_job = outcome.job_id
        async with StdioMCPPort(root) as mcp:
            restored = ReferenceAgent.restore(mcp, model, record)
            resumed = await restored.resume()
            assert resumed.job_id == first_job
            assert resumed.status == "completed"
            assert resumed.artifact_ids == outcome.artifact_ids

    asyncio.run(run())
    saved = record.read_text()
    assert "Morph my uploaded" not in saved
    assert str(file) not in saved
    assert "content_base64" not in saved
