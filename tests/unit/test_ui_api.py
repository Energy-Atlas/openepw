import pytest
from test_batch import StationProvider

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.store import JobStore
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


def test_job_pagination_and_schema(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(
        WeatherRequest(locations=Location(lat=1, lon=0), start="2024-01-01", end="2024-01-01")
    )
    with TestClient(create_app(service)) as client:
        store = JobStore(tmp_path)
        ids = {store.submit(plan).id for _ in range(3)}
        first = client.get("/v1/jobs?limit=2").json()
        second = client.get("/v1/jobs", params={"limit": 2, "cursor": first["next_cursor"]}).json()
        assert {j["id"] for j in first["items"] + second["items"]} == ids
        assert second["next_cursor"] is None
        assert client.get("/v1/jobs?limit=101").status_code == 422
        assert client.get("/v1/jobs?cursor=garbage").status_code == 400
        schema = client.get("/openapi.json").json()
        assert (
            "$ref"
            in schema["paths"]["/v1/weather/plan"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
        )


def test_signal_upload_and_preview(tmp_path):
    from test_epw import synthetic
    from test_future import signal

    from openepw.epw.writer import epw_bytes

    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    with TestClient(create_app(service)) as client:
        assert client.post("/v1/artifacts/signals", json=[{}]).status_code == 422
        result = client.post("/v1/artifacts/signals", json=[signal().model_dump(mode="json")])
        assert result.status_code == 201
        assert result.json()["role"] == "signals"
        signals = result.json()
        upload = client.post(
            "/v1/artifacts", files={"file": ("test.epw", epw_bytes(synthetic(2023, 8760)))}
        ).json()
        result = client.get(f"/v1/artifacts/{upload['id']}/preview").json()
        assert result["total_rows"] == 8760
        assert client.get(f"/v1/artifacts/{upload['id']}/preview?limit=169").status_code == 422

        visualization = client.get(
            f"/v1/artifacts/{upload['id']}/visualization",
            params=[("variables", "dry_bulb"), ("variables", "dni")],
        )
        assert visualization.status_code == 200
        assert visualization.json()["timestamps"][0].endswith("00:00:00")
        assert len(visualization.json()["series"]["dry_bulb"]) == 8760
        default_visualization = client.get(f"/v1/artifacts/{upload['id']}/visualization").json()
        assert default_visualization["series"]["liquid_precipitation"] == [None] * 8760
        assert (
            client.get(
                f"/v1/artifacts/{upload['id']}/visualization",
                params={"variables": "not_weather"},
            ).status_code
            == 400
        )
        assert (
            client.get(
                f"/v1/artifacts/{upload['id']}/visualization",
                params=[
                    ("variables", value)
                    for value in ["dry_bulb", "dew_point", "pressure", "ghi", "dni"]
                ],
            ).status_code
            == 400
        )
        assert client.get(f"/v1/artifacts/{signals['id']}/visualization").status_code == 400

        invalid = client.post(
            "/v1/artifacts", files={"file": ("partial.epw", epw_bytes(synthetic()))}
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "INVALID_ARTIFACT"

        oversized = service.artifacts.write(
            "oversized",
            "oversized.epw",
            epw_bytes(synthetic(2024, 8785)),
            "weather",
            "application/vnd.energyplus.epw",
        )
        assert client.get(f"/v1/artifacts/{oversized.id}/visualization").status_code == 400


def test_spatial_preview_and_documented_coverage_contracts(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[])
    with TestClient(create_app(service)) as client:
        request = WeatherRequest(
            locations={"west": 0, "south": 0, "east": 1, "north": 1},
            sampling={"dx_km": 100, "dy_km": 100, "max_locations": 10},
            product="amy",
            years=[2024],
        )
        sampled = client.post("/v1/spatial/preview", json=request.model_dump(mode="json"))
        assert sampled.status_code == 200
        assert sampled.json()["total_count"] == 4

        response = client.get("/v1/weather/coverage", params={"year": 2024})
        assert response.status_code == 200
        layers = response.json()
        era5 = next(layer for layer in layers if layer["id"] == "openmeteo-era5")
        assert era5["coverage_basis"] == "documented"
        assert era5["kind"] == "vector"
        assert era5["geometry"]["type"] == "Polygon"
        assert era5["tiles"] is None
        assert era5["attribution"]
        assert era5["source_url"].startswith("https://")
        assert era5["observed_at"]

        unknown = next(layer for layer in layers if layer["kind"] == "unknown")
        assert unknown["geometry"] is None
        assert unknown["tiles"] is None
