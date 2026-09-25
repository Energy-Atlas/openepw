import asyncio
import base64
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl
from test_epw import synthetic
from test_future import signal

from openepw.artifacts.store import ArtifactStore
from openepw.epw.writer import epw_bytes


def test_real_client_upload_and_fetched_id_future_jobs(tmp_path):
    store = ArtifactStore(tmp_path)
    body = epw_bytes(synthetic(2023, 8760))
    fetched = store.write("b" * 32, "weather.epw", body, "weather",
                          "application/vnd.energyplus.epw")
    store.json("b" * 32, "manifest.json", {
        "outputs": [{"artifact_id": fetched.id, "output_id": "c" * 64}]}, "manifest")
    store.json("b" * 32, "qc.json", [], "qc")
    signals = store.write(
        "a" * 32, "signals.json",
        json.dumps([signal().model_dump(mode="json")]).encode(), "signals")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from openepw.cli.main import main; raise SystemExit(main())",
              "--data-root", str(tmp_path), "mcp"],
    )

    async def run():
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                upload = await client.call_tool(
                    "baseline_upload",
                    {"content_base64": base64.b64encode(body).decode()})
                assert not upload.isError
                uploaded_id = upload.structuredContent["artifact_id"]
                assert uploaded_id != fetched.id
                for baseline, origin in (
                    (uploaded_id, "user_provided"), (fetched.id, "weather_output")
                ):
                    planned = await client.call_tool("future_plan", {"request": {
                        "baseline": baseline, "signals": signals.id,
                        "reference_period": [1985, 2014],
                        "climate_period": [2036, 2065],
                        "climate_scenario": "ssp245",
                    }})
                    assert not planned.isError
                    plan = planned.structuredContent
                    assert plan["baseline_ref"]["origin"] == origin
                    submitted = await client.call_tool(
                        "future_submit", {"plan_hash": plan["plan_hash"]})
                    job_id = submitted.structuredContent["id"]
                    for _ in range(100):
                        inspected = await client.call_tool(
                            "job_inspect", {"job_id": job_id})
                        job = inspected.structuredContent
                        if job["state"] not in ("queued", "running"):
                            break
                        await asyncio.sleep(0.1)
                    assert job["state"] == "completed"
                    artifact_id = job["artifacts"]["weather"][0]
                    result = await client.call_tool(
                        "artifact_inspect", {"artifact_id": artifact_id})
                    assert result.structuredContent["role"] == "weather"
                    resource = await client.read_resource(
                        AnyUrl(f"weather://artifacts/{artifact_id}"))
                    assert base64.b64decode(resource.contents[0].blob).startswith(b"LOCATION,")

    asyncio.run(run())
