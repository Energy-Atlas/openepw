import asyncio

import pytest
from fakes import scenario_service

from openepw.agent.mcp_port import ApprovalBook, InProcessMCP, ToolFailure, parse_failure
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server

REQUEST = {"locations": {"lat": 42.44, "lon": -76.5, "standard_offset_minutes": -300},
           "product": "historical", "years": [2018],
           "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}


def test_failures_parse_bare_json_and_plain_text():
    failure = parse_failure('{"code": "INVALID_REQUEST", "message": "bad", "retryable": false, '
                            '"details": [{"loc": "offset", "msg": "x"}]}')
    assert (failure.code, failure.message, failure.details[0]["loc"]) == ("INVALID_REQUEST", "bad", "offset")
    assert parse_failure("Unknown tool: nope").code == "MCP_TOOL_ERROR"


def test_approvals_are_one_shot():
    book = ApprovalBook()
    book.approve("a" * 64)
    assert book.pending == frozenset({"a" * 64})
    assert book.consume("a" * 64) is True and book.consume("a" * 64) is False


def test_in_process_client_calls_tools_and_submits_only_once_per_approval(tmp_path):
    service = scenario_service(tmp_path)
    runner = JobRunner(service)
    approvals = ApprovalBook()

    async def scenario():
        async with InProcessMCP(create_server(service, runner=runner), approvals) as port:
            review = await port.call("weather_locations_review", locations={"lat": 42.44, "lon": -76.5})
            assert review.data["points"][0]["standard_offset_minutes"] == -300
            assert review.data["key"] in review.text
            plan = await port.call("weather_plan", request=REQUEST)
            plan_hash = plan.data["plan_hash"]
            with pytest.raises(ToolFailure) as refused:
                await port.call("weather_submit", plan_hash=plan_hash)
            assert refused.value.code == "APPROVAL_DECLINED"
            approvals.approve(plan_hash)
            job = await port.call("weather_submit", plan_hash=plan_hash)
            assert job.data["approved_via"] == "elicitation" and approvals.pending == frozenset()
            with pytest.raises(ToolFailure) as again:
                await port.call("weather_submit", plan_hash=plan_hash)
            assert again.value.code == "APPROVAL_DECLINED"

    try:
        asyncio.run(scenario())
    finally:
        runner.close()
