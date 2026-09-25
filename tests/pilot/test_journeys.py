"""Stage 6 pilot through a real SDK stdio session and synthetic sources."""

import asyncio
import base64
import csv
import io
import json
import sys
import time
import zipfile
from pathlib import Path

from pydantic import AnyUrl

from openepw.artifacts.store import ArtifactStore
from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    FutureWindowScope,
    ProductRecord,
    TMYReferenceScope,
)
from openepw.availability.store import CatalogStore
from openepw.epw import read_epw
from openepw.epw.writer import epw_bytes
from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.mcp_client import MCPToolFailure, StdioMCPPort

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic
from test_future import signal

SERVER = str(Path(__file__).with_name("fixture_server.py"))
ITHACA = {"id": "ithaca", "lat": 42.44, "lon": -76.5}


class FixedModel:
    def __init__(self, intent):
        self.intent = intent

    def parse(self, prompt):
        return self.intent


class PilotPort(StdioMCPPort):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tool_calls = 0

    async def call(self, name, **arguments):
        self.tool_calls += 1
        return await super().call(name, **arguments)


def port(root, mode="general"):
    return PilotPort(root, server_args=[
        SERVER, "--data-root", str(root), "--mode", mode,
    ])


async def finished(client, job_id):
    start = time.monotonic()
    while time.monotonic() - start < 30:
        job = await client.call("job_inspect", job_id=job_id)
        if job["state"] not in ("queued", "running"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError("pilot job did not finish in 30 seconds")


async def resource(client, artifact_id):
    response = await client.session.read_resource(
        AnyUrl(f"weather://artifacts/{artifact_id}"))
    return base64.b64decode(response.contents[0].blob)


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_actual_year_agent_alternatives_and_reconnect(tmp_path):
    async def journey():
        intent = AgentIntent(kind="weather", lat=42.44, lon=-76.5,
                             product="historical", years=[2024])
        record = tmp_path / "agent.json"
        async with port(tmp_path) as client:
            discovery = await client.call("weather_discover", request={
                "locations": ITHACA, "product": "historical", "years": [2024],
                "providers": ["station", "alternative"]})
            assert {c["source"]["provider"] for c in discovery["candidates"]} == {
                "station", "alternative"}
            agent = ReferenceAgent(client, FixedModel(intent), record_path=record)
            result = await agent.run("Ithaca actual year 2024", auto_submit=True)
            assert result.status == "completed", result.message
            assert "Source alternatives" in result.message
            assert "provisional identity or missing coverage" in result.message
            assert "simulation_ready=false" in result.message
            job = await finished(client, result.job_id)
            assert job["plan_hash"] == result.plan_hash
            assert len(result.artifact_ids) == 1
            epw = await resource(client, result.artifact_ids[0])
            assert len(read_epw(epw).data) == 8784
            inspect = await client.call("artifact_inspect", artifact_id=result.artifact_ids[0])
            assert inspect["sha256"]
            assert inspect["manifest_artifact_id"]
            assert inspect["qc_artifact_id"]
            cancellation = await client.call("job_cancel", job_id=result.job_id)
            assert cancellation["state"] == "completed"
            assert cancellation["artifacts"]["weather"] == list(result.artifact_ids)
            assert b"OPENAI_API_KEY" not in record.read_bytes()
            assert client.tool_calls <= 30
        async with port(tmp_path) as client:
            resumed = await ReferenceAgent.restore(
                client, FixedModel(intent), record).resume()
            assert resumed.artifact_ids == result.artifact_ids
            assert resumed.plan_hash == result.plan_hash
        return result.artifact_ids[0]

    run(journey())


def test_b_published_batch_exact_product_occurrences_and_export(tmp_path):
    async def journey():
        request = {
            "locations": [
                ITHACA,
                {"id": "nearby", "lat": 42.5, "lon": -76.45},
                ITHACA,
                {"id": "far", "lat": 30.0, "lon": -100.0},
            ],
            "product": "tmyx", "providers": ["onebuilding"],
            "product_id": "USA/NY/Ithaca.zip",
        }
        async with port(tmp_path) as client:
            plan = await client.call("weather_plan", request=request)
            detail = await client.call("plan_inspect", plan_hash=plan["plan_hash"])
            assert detail["plan_hash"] == plan["plan_hash"]
            assert detail["output_count"] == 3
            assert detail["batch_row_count"] == 4
            assert {c["product_id"] for c in detail["selected_candidates"]} == {
                "USA/NY/Ithaca.zip"}
            job = await client.call("weather_submit", plan_hash=plan["plan_hash"])
            complete = await finished(client, job["id"])
            assert complete["state"] == "partially_completed"
            assert complete["completed"] == 3
            assert len(complete["batch_rows"]) == 4
            assert [r["occurrence_index"] for r in complete["batch_rows"]] == list(range(4))
            assert len(complete["artifacts"]["weather"]) == 3
            manifest = json.loads(await resource(
                client, complete["artifacts"]["manifest"]))
            assert manifest["counts"]["native_tasks"] == 1
            export = await client.call("weather_export_compact", job_id=job["id"])
            compact = await resource(client, export["artifact_id"])
            with zipfile.ZipFile(io.BytesIO(compact)) as archive:
                assert len([name for name in archive.namelist()
                            if name.endswith(".epw")]) == 1
                mapping = list(csv.DictReader(io.StringIO(
                    archive.read("mapping.csv").decode())))
                assert len(mapping) == 4
                assert not mapping[-1]["compact_member"]
            agent = ReferenceAgent(client, FixedModel(AgentIntent(
                kind="weather", locations=request["locations"], product="tmyx",
                provider="OneBuilding", product_id="USA/NY/Ithaca.zip")))
            answer = await agent.run("Named OneBuilding batch", auto_submit=True)
            assert answer.status == "partially_completed"
            assert "Exact product USA/NY/Ithaca.zip" in answer.message
            assert "Per-occurrence outcomes" in answer.message
            assert "unresolved (PROVIDER_UNAVAILABLE)" in answer.message
            assert client.tool_calls <= 30

    run(journey())


def test_c_uploaded_and_fetched_baselines_and_unsupported_future(tmp_path):
    async def journey():
        signals = [signal().model_dump(mode="json")]
        sig_ref = ArtifactStore(tmp_path).write(
            "s" * 32, "signals.json", json.dumps(signals).encode(), "signals")
        async with port(tmp_path) as client:
            upload = await client.call(
                "baseline_upload", content_base64=base64.b64encode(
                    epw_bytes(synthetic(2023, 8760))).decode())
            assert upload["rows"] == 8760
            request = {
                "baseline": upload["artifact_id"], "signals": sig_ref.id,
                "method": "morph", "climate_scenario": "ssp245",
                "reference_period": [1985, 2014], "climate_period": [2036, 2065],
            }
            plan = await client.call("future_plan", request=request)
            assert plan["baseline_ref"]["origin"] == "user_provided"
            job = await client.call("future_submit", plan_hash=plan["plan_hash"])
            complete = await finished(client, job["id"])
            assert complete["state"] == "completed", complete
            assert len(complete["artifacts"]["weather"]) == 1
            assert len(read_epw(await resource(
                client, complete["artifacts"]["weather"][0])).data) == 8760
            agent = ReferenceAgent(client, FixedModel(AgentIntent(
                kind="future", baseline_artifact_id=upload["artifact_id"],
                signals_artifact_id=sig_ref.id, method="morph",
                climate_scenario="ssp245", reference_period=(1985, 2014),
                climate_period=(2036, 2065))))
            answer = await agent.run("My uploaded baseline SSP245", auto_submit=True)
            assert answer.status == "completed", answer.message
            assert "baseline origin user_provided" in answer.message
            assert client.tool_calls <= 30
            first_journey_calls = client.tool_calls
            rejected = dict(request, method="climate_profile")
            try:
                await client.call("future_plan", request=rejected)
            except MCPToolFailure as error:
                assert error.code == "INVALID_SCENARIO_PERIOD"
            else:
                raise AssertionError("SSP climate profile must be rejected")

            weather = await client.call("weather_plan", request={
                "locations": ITHACA, "product": "historical", "years": [2024],
                "providers": ["station"]})
            wjob = await client.call("weather_submit", plan_hash=weather["plan_hash"])
            wdone = await finished(client, wjob["id"])
            fetched = wdone["artifacts"]["weather"][0]
            second = await client.call("future_plan", request={
                **request, "baseline": fetched})
            assert second["baseline_ref"]["origin"] == "weather_output"
            fjob = await client.call("future_submit", plan_hash=second["plan_hash"])
            fdone = await finished(client, fjob["id"])
            assert fdone["state"] == "completed", fdone
            assert fdone["artifacts"]["weather"]
            fetched_agent = ReferenceAgent(client, FixedModel(AgentIntent(
                kind="future", baseline_artifact_id=fetched,
                signals_artifact_id=sig_ref.id, method="morph",
                climate_scenario="ssp245", reference_period=(1985, 2014),
                climate_period=(2036, 2065))))
            answer = await fetched_agent.run("My fetched weather SSP245", auto_submit=True)
            assert answer.status == "completed", answer.message
            assert "baseline origin weather_output" in answer.message
            assert client.tool_calls - first_journey_calls <= 30

    run(journey())


def test_g_noaa_gap_warn_and_error(tmp_path):
    async def journey():
        async with port(tmp_path, "noaa") as client:
            hashes = json.loads((tmp_path / "noaa-hashes.json").read_text())
            warn = await client.call("weather_submit", plan_hash=hashes["warn"])
            warning = await finished(client, warn["id"])
            assert warning["artifacts"]["weather"]
            epw = await resource(client, warning["artifacts"]["weather"][0])
            assert b"99.9" in epw
            inspect = await client.call(
                "artifact_inspect", artifact_id=warning["artifacts"]["weather"][0])
            assert inspect["simulation_ready"] is False
            assert "MISSING_CRITICAL_VARIABLE" in inspect["qc_issue_codes"]
            error = await client.call("weather_submit", plan_hash=hashes["error"])
            failed = await finished(client, error["id"])
            assert not failed["artifacts"]["weather"]
            assert failed["failed"] >= 1
            retry = await client.call("job_retry_failed", job_id=error["id"])
            retried = await finished(client, retry["id"])
            assert not retried["artifacts"]["weather"]
            batch = await client.call("weather_submit", plan_hash=hashes["batch_error"])
            mixed = await finished(client, batch["id"])
            assert mixed["state"] == "partially_completed", mixed
            assert mixed["completed"] == 1 and mixed["failed"] == 1
            assert len(mixed["artifacts"]["weather"]) == 1
            assert len(mixed["batch_rows"]) == 2
            assert len(read_epw(await resource(
                client, mixed["artifacts"]["weather"][0])).data) == 24
            agent = ReferenceAgent(client, FixedModel(AgentIntent(kind="unknown")))
            resumed = await agent.resume(warn["id"])
            assert "simulation_ready=false" in resumed.message
            assert "gap" in resumed.message.lower()
            assert client.tool_calls <= 30
    run(journey())


def test_c2_hourly_profile_uses_bounded_archive_and_comparison_baseline(tmp_path):
    async def journey():
        async with port(tmp_path, "puma") as client:
            baseline = await client.call(
                "baseline_upload", content_base64=base64.b64encode(
                    epw_bytes(synthetic(2023, 8760))).decode())
            agent = ReferenceAgent(client, FixedModel(AgentIntent(
                kind="future", baseline_artifact_id=baseline["artifact_id"],
                method="climate_profile", climate_scenario="rcp85",
                climate_period=(2045, 2054))))
            answer = await agent.run("PUMA RCP8.5 2045-2054", auto_submit=True)
            assert answer.status == "completed", answer.message
            assert len(answer.artifact_ids) == 1
            assert len(read_epw(await resource(client, answer.artifact_ids[0])).data) == 8760
            inspected = await client.call(
                "artifact_inspect", artifact_id=answer.artifact_ids[0])
            manifest = json.loads(await resource(
                client, inspected["manifest_artifact_id"]))
            output = manifest["outputs"][0]
            assert output["method"] == "climate_profile"
            assert output["lineage"]["dry_bulb"]["source"]["provider"] == "oedi"
            assert output["metadata"]["user_baseline_location"]["lat"] == 42
            assert output["metadata"]["user_baseline_location"]["lon"] == -76
            for changed, code in (
                ({"climate_period": [2036, 2065]}, "INVALID_SCENARIO_PERIOD"),
            ):
                try:
                    await client.call("future_plan", request={
                        "baseline": baseline["artifact_id"],
                        "method": "climate_profile", "climate_scenario": "rcp85",
                        "climate_period": [2045, 2054], **changed})
                except MCPToolFailure as error:
                    assert error.code == code
                else:
                    raise AssertionError("Unsupported hourly archive period accepted")
            distant = synthetic(2023, 8760)
            distant.location.lat = 0
            distant.location.lon = 0
            distant_ref = await client.call(
                "baseline_upload", content_base64=base64.b64encode(
                    epw_bytes(distant)).decode())
            try:
                await client.call("future_plan", request={
                    "baseline": distant_ref["artifact_id"],
                    "method": "climate_profile", "climate_scenario": "rcp85",
                    "climate_period": [2045, 2054]})
            except MCPToolFailure as error:
                assert error.code == "UNSUPPORTED_GEOGRAPHY"
            else:
                raise AssertionError("Unsupported hourly archive site accepted")
            assert client.tool_calls <= 30

    run(journey())


def test_recovery_path_allowlist_invalid_upload_and_corrupt_artifact(tmp_path):
    async def journey():
        epw_path = tmp_path / "user.epw"
        epw_path.write_bytes(epw_bytes(synthetic(2023, 8760)))
        async with StdioMCPPort(tmp_path) as client:
            for name, args, code in (
                ("baseline_register_path", {"path": str(epw_path)}, "ACCESS_DENIED"),
                ("baseline_upload", {"content_base64": "bad!"}, "INVALID_BASELINE"),
                ("artifact_inspect", {"artifact_id": "0" * 32}, "INVALID_ARTIFACT"),
            ):
                try:
                    await client.call(name, **args)
                except MCPToolFailure as error:
                    assert error.code == code
                else:
                    raise AssertionError(f"{name} should fail with {code}")
        async with StdioMCPPort(tmp_path, allowed_roots=[tmp_path]) as client:
            registered = await client.call("baseline_register_path", path=str(epw_path))
            assert registered["rows"] == 8760
            assert registered["artifact_id"]
            ref = ArtifactStore(tmp_path).write(
                "c" * 32, "corrupt.json", b'{"ok":true}', "manifest")
            _, path = ArtifactStore(tmp_path).resolve(ref.id)
            path.write_bytes(b"changed")
            try:
                await client.call("artifact_inspect", artifact_id=ref.id)
            except MCPToolFailure as error:
                assert error.code == "INVALID_ARTIFACT"
            else:
                raise AssertionError("Corrupt artifact was accepted")

    run(journey())


def test_merged_evidence_keeps_unprobed_year_and_future_window_unknown(tmp_path):
    catalog = CatalogStore(tmp_path / "catalog")
    bundle = CatalogBundle(
        products=[
            ProductRecord(id="nsrdb:tdy-2023", provider="nsrdb", dataset="tdy",
                          native_product_id="tdy-2023", temporal_kind="tmy_reference",
                          spatial_kind="grid", adapter_variables=["dry_bulb"]),
            ProductRecord(id="nsrdb:actual", provider="nsrdb", dataset="aggregate",
                          temporal_kind="actual", spatial_kind="grid",
                          adapter_variables=["dry_bulb"]),
            ProductRecord(id="cmip6:model-a", provider="cmip6", dataset="monthly",
                          temporal_kind="future_window", license_effective="CC BY 4.0"),
        ],
        entries=[
            AvailabilityEntry(
                id="tdy", product_id="nsrdb:tdy-2023",
                scope=TMYReferenceScope(product_label="tdy-2023"),
                evidence_basis="inventory"),
            AvailabilityEntry(
                id="actual-probe", product_id="nsrdb:actual",
                scope=ActualScope(years=[2024]),
                probe_location={"lat": 42.44, "lon": -76.5},
                evidence_basis="targeted_probe"),
            AvailabilityEntry(
                id="monthly-model", product_id="cmip6:model-a",
                scope=FutureWindowScope(scenario="ssp245", model="A", member="r1"),
                evidence_basis="inventory"),
        ],
    )
    catalog.activate(catalog.stage(bundle).generation_id)

    async def journey():
        async with StdioMCPPort(tmp_path) as client:
            published = await client.call("weather_assess", query={
                "kind": "weather", "request": {
                    "locations": {"lat": 40, "lon": -105}, "product": "tmy",
                    "product_id": "tdy-2023", "providers": ["nsrdb"],
                }})
            actual = await client.call("weather_assess", query={
                "kind": "weather", "request": {
                    "locations": {"lat": 40, "lon": -105}, "product": "historical",
                    "years": [2023], "providers": ["nsrdb"],
                }})
            assert any(o["product"]["id"] == "nsrdb:tdy-2023"
                       for o in published["options"])
            assert all(o["eligibility"]["status"] != "supported"
                       for o in actual["options"])
            future = await client.call("weather_assess", query={
                "kind": "future", "location": {"lat": 40, "lon": -105},
                "method": "morph", "scenario": "ssp245",
                "climate_period": [2036, 2065], "reference_period": [1985, 2014],
                "model": "A", "member": "r1",
            })
            option = next(o for o in future["options"]
                          if o["product"]["id"] == "cmip6:model-a")
            assert option["product"]["license_effective"] == "CC BY 4.0"
            assert option["eligibility"]["status"] == "unknown"
            assert option["eligibility"]["unknowns"]

    run(journey())
