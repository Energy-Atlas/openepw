"""Availability adapters serialize the canonical Python assessment."""

import asyncio
import json

from fastapi.testclient import TestClient
from test_availability_service import ForbiddenHttp, _catalog

from openepw.api.app import create_app
from openepw.availability import CatalogBundle, FutureAvailabilityQuery, WeatherAvailabilityQuery
from openepw.cli.main import main
from openepw.config import RuntimeConfig
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


def test_rest_and_cli_share_weather_decision(tmp_path, capsys):
    _catalog(tmp_path / "runtime")
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp())
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024],
                             providers=["noaa"])
    query = WeatherAvailabilityQuery(request=request)
    expected = service.assess_availability(query).model_dump(mode="json")
    with TestClient(create_app(service)) as client:
        response = client.post("/v1/availability", json=query.model_dump(mode="json"))
        assert response.status_code == 200
        rest = response.json()
        discovery = client.post("/v1/weather/discover", json=request.model_dump(mode="json"))
        assert discovery.status_code == 200
        assert discovery.json()["availability"]["snapshots"] == rest["snapshots"]
    query_file = tmp_path / "query.json"
    query_file.write_text(query.model_dump_json(), encoding="utf-8")
    assert main(["--data-root", str(tmp_path / "runtime"), "availability", str(query_file)]) == 0
    cli = json.loads(capsys.readouterr().out)
    for result in (rest, cli):
        assert result["options"][0]["eligibility"] == expected["options"][0]["eligibility"]
        assert result["snapshots"] == expected["snapshots"]
        assert "noaa-counts" in json.dumps(result)
        assert "raw/" not in json.dumps(result)


def test_future_query_and_invalid_temporal_kind_are_bounded(tmp_path, capsys):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp())
    query = FutureAvailabilityQuery(location=Location(lat=42, lon=-76),
                                    method="morph", scenario="ssp245",
                                    climate_period=(2041, 2070))
    with TestClient(create_app(service)) as client:
        response = client.post("/v1/availability", json=query.model_dump(mode="json"))
        assert response.status_code == 200
        assert response.json()["options"][0]["eligibility"]["status"] == "unknown"
        invalid = client.post("/v1/availability", json={"kind": "invalid", "root": "/secret"})
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "INVALID_REQUEST"
        assert "/secret" not in invalid.text
    query_file = tmp_path / "future.json"
    query_file.write_text(query.model_dump_json(), encoding="utf-8")
    assert main(["--data-root", str(tmp_path / "runtime"), "availability", str(query_file)]) == 0
    assert json.loads(capsys.readouterr().out)["options"][0]["product"]["provider"] == "cmip6"


def test_existing_mcp_discovery_exposes_shared_assessment(tmp_path):
    from openepw.mcp.server import create_server

    _catalog(tmp_path / "runtime")
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "runtime"),
                             http=ForbiddenHttp())
    request = WeatherRequest(locations=Location(lat=42, lon=-76), years=[2024],
                             providers=["noaa"])
    expected = service.discover(request).model_dump(mode="json")
    result = asyncio.run(create_server(service).call_tool(
        "weather_discover", {"request": request.model_dump(mode="json")}))
    actual = result if isinstance(result, dict) else json.loads(result[0].text)
    assert actual["availability"]["snapshots"] == expected["availability"]["snapshots"]
    assert actual["availability"]["options"][0]["eligibility"] == (
        expected["availability"]["options"][0]["eligibility"])
    assert actual["availability"]["locations"] == expected["availability"]["locations"]
    assert [item["id"] for item in actual["candidates"]] == [
        item["id"] for item in expected["candidates"]]


def test_catalog_cli_status_and_missing_import(tmp_path, capsys):
    root = tmp_path / "runtime"
    assert main(["--data-root", str(root), "catalog", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["loaded"] is False
    assert "cds" in status["missing_sources"]
    assert "era5" not in status["missing_sources"]
    assert main(["--data-root", str(root), "catalog", "import", "--from",
                 str(tmp_path / "missing")]) == 2
    error = json.loads(capsys.readouterr().out)
    assert error["code"] == "CATALOG_IMPORT_ERROR"
    assert not (root / "catalog" / "active").exists()


def test_catalog_cli_imports_existing_snapshot_offline(tmp_path, capsys, monkeypatch):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "ledger.json").write_text('{"records": []}', encoding="utf-8")
    (snapshot / "analysis.json").write_text('{"inventories": {}}', encoding="utf-8")
    import openepw.cli.main as cli_module

    seen = []
    monkeypatch.setattr(cli_module, "import_stage1",
                        lambda root: (seen.append(root), CatalogBundle())[1])
    root = tmp_path / "runtime"
    assert main(["--data-root", str(root), "catalog", "import", "--from",
                 str(snapshot)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["loaded"] is True
    assert result["entry_count"] == 0
    assert seen == [snapshot]
    assert main(["--data-root", str(root), "catalog", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["generation_id"] == result["generation_id"]
    assert status["stale_sources"] == []
