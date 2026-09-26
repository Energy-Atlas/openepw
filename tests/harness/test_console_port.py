"""Console tool events are explicit and safe to print."""

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from openepw.harness.console_port import ConsoleMCPPort
from openepw.harness.mcp_client import MCPToolFailure


def events(output):
    return [json.loads(line.removeprefix("Tool> "))
            for line in output.splitlines() if line.startswith("Tool> ")]


class Session:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if self.fail:
            return SimpleNamespace(
                isError=True, structuredContent=None,
                content=[SimpleNamespace(text='{"code":"DENIED","message":"private"}')])
        result = ({"artifact_id": "artifact-1"} if name == "baseline_upload"
                  else {"plan_hash": "a" * 64, "output_count": 7,
                        "private_provider_payload": "topsecret"})
        return SimpleNamespace(isError=False, structuredContent=result)

    async def read_resource(self, uri):
        return SimpleNamespace(contents=[SimpleNamespace(
            blob=base64.b64encode(b"private EPW bytes").decode())])


def test_console_emits_structured_call_and_result_without_payload(capsys):
    before = []
    port = ConsoleMCPPort("unused", before_message=lambda: before.append(True))
    port.session = Session()
    result = asyncio.run(port.call(
        "weather_plan", request={"product": "historical", "years": [2012, 2013],
                                 "locations": {"lat": 1.2, "lon": 3.4},
                                 "secret": "topsecret"}))
    assert result["output_count"] == 7
    output = capsys.readouterr().out
    records = events(output)
    assert [row["event"] for row in records] == ["call", "result"]
    assert [row["tool"] for row in records] == ["weather_plan", "weather_plan"]
    assert records[0]["call_id"] == records[1]["call_id"]
    assert records[0]["arguments"]["product"] == "historical"
    assert records[0]["arguments"]["years"] == [2012, 2013]
    assert records[0]["arguments"]["location_count"] == 1
    assert records[1]["summary"]["output_count"] == 7
    assert "topsecret" not in output
    assert "private_provider_payload" not in output
    assert len(before) == 2


def test_console_upload_logs_real_tool_without_epw_bytes_or_path(tmp_path, capsys):
    source = tmp_path / "private-weather.epw"
    source.write_bytes(b"private EPW bytes")
    port = ConsoleMCPPort(tmp_path)
    port.session = Session()
    assert asyncio.run(port.upload_file(source)) == "artifact-1"
    output = capsys.readouterr().out
    records = events(output)
    assert records[0]["tool"] == "baseline_upload"
    assert records[0]["arguments"]["bytes"] == len(b"private EPW bytes")
    assert "private EPW bytes" not in output
    assert str(source) not in output
    assert "content_base64" not in output


def test_console_error_event_has_code_but_not_private_message(capsys):
    port = ConsoleMCPPort("unused")
    port.session = Session(fail=True)
    with pytest.raises(MCPToolFailure):
        asyncio.run(port.call("weather_plan", request={"secret": "topsecret"}))
    output = capsys.readouterr().out
    records = events(output)
    assert [row["event"] for row in records] == ["call", "error"]
    assert records[1]["code"] == "DENIED"
    assert "private" not in output
    assert "topsecret" not in output


def test_console_assessment_summarizes_nested_query(capsys):
    port = ConsoleMCPPort("unused")
    port.session = Session()
    asyncio.run(port.call("weather_assess", query={
        "kind": "weather", "request": {
            "product": "historical", "years": [2018],
            "locations": {"lat": 42.4, "lon": -71.1}}}))
    call = events(capsys.readouterr().out)[0]
    assert call["arguments"] == {
        "product": "historical", "years": [2018], "location_count": 1}
