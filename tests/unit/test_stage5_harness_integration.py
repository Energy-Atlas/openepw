import asyncio
from pathlib import Path

from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.mcp_client import StdioMCPPort


class StubModel:
    def parse(self, prompt):
        return AgentIntent(
            kind="weather", lat=42.44, lon=-76.5, product="historical",
            years=[2024], provider="station")


def test_reference_agent_runs_and_resumes_over_real_stdio_mcp(tmp_path):
    root = tmp_path / "store"
    source = Path(__file__).parents[1] / "pilot" / "fixture_server.py"
    model = StubModel()
    record = tmp_path / "run.json"

    async def run():
        async with StdioMCPPort(root, server_args=[
            str(source), "--data-root", str(root), "--mode", "general",
        ]) as mcp:
            agent = ReferenceAgent(mcp, model, record_path=record)
            outcome = await agent.run(
                "Historical weather for Ithaca in 2024", auto_submit=True)
            assert outcome.status == "completed"
            assert "simulation_ready=false" in outcome.message
            assert outcome.artifact_ids
            first_job = outcome.job_id
        async with StdioMCPPort(root, server_args=[
            str(source), "--data-root", str(root), "--mode", "general",
        ]) as mcp:
            restored = ReferenceAgent.restore(mcp, model, record)
            resumed = await restored.resume()
            assert resumed.job_id == first_job
            assert resumed.status == "completed"
            assert resumed.artifact_ids == outcome.artifact_ids

    asyncio.run(run())
    saved = record.read_text()
    assert "Historical weather for Ithaca" not in saved
    assert "content_base64" not in saved
