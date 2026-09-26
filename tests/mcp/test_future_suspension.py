"""Future generation is temporarily absent from the public MCP surface."""

import asyncio
import base64
import sys
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic

from openepw.config import RuntimeConfig
from openepw.epw.writer import epw_bytes
from openepw.jobs.store import JobStore
from openepw.mcp.server import create_server
from openepw.models import FutureRequest, WeatherPlan
from openepw.service import WeatherService


def call(server, name, **arguments):
    return asyncio.run(server.call_tool(name, arguments))[1]


def test_future_tools_are_absent_but_generic_epw_upload_remains(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert {"future_plan", "future_submit", "weather_generate_future",
            "baseline_upload", "baseline_register_path"}.isdisjoint(names)
    assert {"epw_upload", "epw_register_path", "weather_plan", "weather_submit",
            "job_inspect", "artifact_inspect"} <= names
    body = epw_bytes(synthetic(2023, 8760))
    uploaded = call(server, "epw_upload", content_base64=base64.b64encode(body).decode())
    assert uploaded["rows"] == 8760
    assert call(server, "artifact_inspect", artifact_id=uploaded["artifact_id"])[
        "role"] == "baseline"


def test_future_compatibility_paths_are_suspended(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError, match="FEATURE_SUSPENDED"):
        call(server, "weather_plan", request={}, kind="future")
    with pytest.raises(ToolError, match="FEATURE_SUSPENDED"):
        call(server, "weather_assess", query={"kind": "future"})


def test_old_future_job_can_be_inspected_but_not_retried(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    plan = WeatherPlan(kind="future", request=FutureRequest(
        baseline="old-baseline", climate_scenario="ssp245",
        climate_period=(2036, 2065)))
    service.plan_store.put(plan)
    job = JobStore(tmp_path).submit(plan)
    server = create_server(service)
    assert call(server, "plan_inspect", plan_hash=plan.plan_hash)["kind"] == "future"
    assert call(server, "job_inspect", job_id=job.id)["kind"] == "future"
    with pytest.raises(ToolError, match="FEATURE_SUSPENDED"):
        call(server, "weather_submit", plan_hash=plan.plan_hash)
    with pytest.raises(ToolError, match="FEATURE_SUSPENDED"):
        call(server, "weather_fetch", plan=plan.model_dump(mode="json"))
    with pytest.raises(ToolError, match="FEATURE_SUSPENDED"):
        call(server, "job_retry_failed", job_id=job.id)
