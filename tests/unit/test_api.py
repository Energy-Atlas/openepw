import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def test_api_plan_parity_and_auth(tmp_path):
    service = WeatherService(
        RuntimeConfig(data_root=tmp_path, bearer_token="test-token"), providers=[StationProvider()]
    )
    with TestClient(create_app(service, remote=True)) as client:
        body = {"locations": {"lat": 1, "lon": 0}, "start": "2024-01-01", "end": "2024-01-01"}
        assert client.post("/v1/weather/plan", json=body).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        response = client.post("/v1/weather/plan", json=body, headers=headers)
        assert response.status_code == 200
        assert len(response.json()["tasks"]) == 1
        bad = client.post(
            "/v1/weather/plan", json={**body, "api_key": "must-not-echo"}, headers=headers
        )
        assert bad.status_code == 422
        assert "must-not-echo" not in bad.text
        assert client.get("/v1/artifacts/not-valid", headers=headers).status_code == 400


def test_remote_without_token_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_app(WeatherService(RuntimeConfig(data_root=tmp_path)), remote=True)


def test_catalog_scopes_route_is_read_only(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        response = client.get("/v1/catalog/scopes")
        assert response.status_code == 200
        assert "scopes" in response.json()
        assert "unmapped" in response.json()


def test_catalog_map_route_is_read_only(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        response = client.get("/v1/catalog/map")
        assert response.status_code == 200
        assert response.json()["schema"] == "catalog-map-1"


def test_retry_route_submits_only_failed_outputs(tmp_path):
    from openepw.models import Location, OpenEPWError, WeatherRequest

    class SometimesFails(StationProvider):
        def fetch(self, task, http):
            if task.source.identity == "2":
                raise OpenEPWError("SOURCE_FAILED", "Synthetic failure")
            return super().fetch(task, http)

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[SometimesFails()])
    app = create_app(service)
    plan = service.plan(
        WeatherRequest(
            locations=[Location(lat=1, lon=0), Location(lat=2, lon=0)],
            start="2024-01-01",
            end="2024-01-01",
        )
    )
    with TestClient(app) as client:
        original = app.state.runner.store.submit(plan)
        app.state.runner.run(original.id)
        app.state.runner.enqueue = lambda job_id: None
        response = client.post(f"/v1/jobs/{original.id}/retry", json={})
        assert response.status_code == 202
        retry = response.json()
        assert retry["retry_of"] == original.id
        assert retry["total"] == 1
        assert len(app.state.runner.store.plan(retry["id"]).outputs) == 1


def test_stored_hash_job_and_compact_export_share_service_identities(tmp_path):
    from openepw.models import Location, WeatherRequest

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(WeatherRequest(
        locations=[Location(lat=1, lon=0), Location(lat=12, lon=0)],
        start="2024-01-01", end="2024-01-01"))
    app = create_app(service)
    with TestClient(app) as client:
        app.state.runner.enqueue = lambda _: None
        response = client.post("/v1/weather/jobs", json={"plan_hash": plan.plan_hash})
        assert response.status_code == 202
        job_id = response.json()["id"]
        app.state.runner.run(job_id)
        job = client.get(f"/v1/jobs/{job_id}").json()
        assert job["plan_hash"] == plan.plan_hash
        assert "dry_bulb" not in response.text
        export = client.post(f"/v1/jobs/{job_id}/export/compact")
        assert export.status_code == 200
        ref = export.json()
        assert ref["media_type"] == "application/zip"
        downloaded = client.get(f"/v1/artifacts/{ref['id']}")
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"PK")


class Reanalysis(StationProvider):
    """The synthetic provider under the Open-Meteo ERA5 name the chat product card offers."""
    name = "openmeteo"

    def discover(self, request, location, http):
        return [candidate.model_copy(update={"source": candidate.source.model_copy(update={"dataset": "era5"})})
                for candidate in super().discover(request, location, http)]


def _choose_era5(client, sid, state):
    card = state["active_card"]
    assert card["prompt"] == "Which weather product?"
    return client.post(f"/v1/chat/sessions/{sid}/products", json={
        "product_ids": ["era5-openmeteo"], "revision": card["revision"], "idempotency_key": "product"}).json()


def test_chat_rest_prepares_and_runs_only_after_explicit_action(tmp_path):
    from openepw.chat.coordinator import OfflineParser

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[Reanalysis()])
    app = create_app(service, chat_parser=OfflineParser())
    with TestClient(app) as client:
        app.state.runner.enqueue = lambda _: None
        created = client.post("/v1/chat/sessions").json()
        sid = created["id"]
        turn = client.post(f"/v1/chat/sessions/{sid}/turns", json={
            "text": "42.37, -71.11 historical 2018", "revision": 0,
            "idempotency_key": "first"})
        assert turn.status_code == 200
        state = turn.json()
        assert state["facts"]["years"] == [2018]
        assert state["job_id"] is None
        assert client.get(f"/v1/chat/sessions/{sid}").json()["facts"] == state["facts"]
        assert state["active_card"]["kind"] == "location_review"
        unapproved = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": state["revision"], "idempotency_key": "unapproved"})
        assert unapproved.status_code >= 400 and "Approve the location" in unapproved.text
        state = client.post(f"/v1/chat/sessions/{sid}/location/approve", json={
            "revision": state["revision"], "idempotency_key": "approve"}).json()
        unchosen = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": state["revision"], "idempotency_key": "unchosen"})
        assert unchosen.status_code >= 400 and "weather product" in unchosen.text
        state = _choose_era5(client, sid, state)
        assert state["facts"]["selections"] == [{"provider": "openmeteo", "dataset": "era5", "product_id": None}]
        assert state["active_card"]["kind"] == "plan_review"
        stale = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": 0, "idempotency_key": "stale"})
        assert stale.status_code == 409
        prepared = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": state["revision"], "idempotency_key": "prepare"})
        assert prepared.status_code == 200
        state = prepared.json()
        assert state["plan_hash"]
        run_body = {"revision": state["revision"], "idempotency_key": "run-once"}
        run = client.post(f"/v1/chat/sessions/{sid}/run", json=run_body)
        assert run.status_code == 202
        assert run.json()["job_id"]
        assert client.post(f"/v1/chat/sessions/{sid}/run", json=run_body).json() == run.json()
        app.state.runner.run(run.json()["job_id"])
        job = client.get(f"/v1/jobs/{run.json()['job_id']}").json()
        artifact_id = job["bundle"]["weather"][0]["id"]
        view = client.post(f"/v1/chat/sessions/{sid}/views", json={
            "revision": run.json()["revision"], "idempotency_key": "monthly-view",
            "request": {"artifact_ids": [artifact_id], "family": "monthly_series",
                        "variable": "dry_bulb", "allow_partial": True}})
        assert view.status_code == 200
        assert view.json()["view_ids"]
        page = client.get(f"/v1/views/{view.json()['view_ids'][0]}/page").json()
        assert page["specs"][0]["family"] == "monthly_series"
        compact = client.post(f"/v1/chat/sessions/{sid}/export/compact")
        assert compact.status_code == 200
        assert client.get(f"/v1/artifacts/{compact.json()['id']}").content.startswith(b"PK")


def test_chat_turn_queue_completes_and_resumes_session(tmp_path):
    import time

    from openepw.chat.coordinator import OfflineParser

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service, chat_parser=OfflineParser())) as client:
        sid = client.post("/v1/chat/sessions").json()["id"]
        queued = client.post(f"/v1/chat/sessions/{sid}/turns/queue", json={
            "text": "40,-105 historical 2018", "revision": 0,
            "idempotency_key": "queued-one"})
        assert queued.status_code == 202
        queue_id = queued.json()["queue_id"]
        deadline = time.monotonic() + 3
        while True:
            status = client.get(f"/v1/chat/turns/{queue_id}").json()
            if status["state"] == "completed":
                break
            assert time.monotonic() < deadline, status
            time.sleep(0.02)
        state = client.get(f"/v1/chat/sessions/{sid}").json()
        assert state["facts"]["location"]["lat"] == 40
        assert state["facts"]["years"] == [2018]


def test_chat_back_route_undoes_a_step_but_not_a_started_job(tmp_path):
    from openepw.chat.coordinator import OfflineParser

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[Reanalysis()])
    app = create_app(service, chat_parser=OfflineParser())
    with TestClient(app) as client:
        app.state.runner.enqueue = lambda _: None
        sid = client.post("/v1/chat/sessions").json()["id"]
        state = client.post(f"/v1/chat/sessions/{sid}/turns", json={
            "text": "42.37, -71.11 historical 2018", "revision": 0, "idempotency_key": "a"}).json()
        state = client.post(f"/v1/chat/sessions/{sid}/location/approve", json={
            "revision": state["revision"], "idempotency_key": "approve"}).json()
        state = _choose_era5(client, sid, state)
        prepared = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": state["revision"], "idempotency_key": "b"}).json()
        assert prepared["active_card"]["data"]["summary"].startswith("- **42.3700, -71.1100** · 2018 ·")
        back = client.post(f"/v1/chat/sessions/{sid}/back", json={
            "revision": prepared["revision"], "idempotency_key": "c"})
        assert back.status_code == 200 and back.json()["plan_hash"] is None
        again = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": back.json()["revision"], "idempotency_key": "d"}).json()
        run = client.post(f"/v1/chat/sessions/{sid}/run", json={
            "revision": again["revision"], "idempotency_key": "e"}).json()
        refused = client.post(f"/v1/chat/sessions/{sid}/back", json={
            "revision": run["revision"], "idempotency_key": "f"})
        assert refused.status_code >= 400 and "job" in refused.text


class Typical(StationProvider):
    """The synthetic provider under the PVGIS TMY name."""
    name = "pvgis"

    def discover(self, request, location, http):
        return [candidate.model_copy(update={"source": candidate.source.model_copy(update={"dataset": "PVGIS TMY"}),
                                             "weather_types": ["tmy"]})
                for candidate in super().discover(request, location, http)]


def test_chat_runs_actual_and_typical_year_products_as_one_job_each(tmp_path):
    from openepw.chat.coordinator import OfflineParser

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[Reanalysis(), Typical()])
    app = create_app(service, chat_parser=OfflineParser())
    with TestClient(app) as client:
        app.state.runner.enqueue = lambda _: None
        sid = client.post("/v1/chat/sessions").json()["id"]
        state = client.post(f"/v1/chat/sessions/{sid}/turns", json={
            "text": "42.37, -71.11", "revision": 0, "idempotency_key": "a"}).json()
        state = client.post(f"/v1/chat/sessions/{sid}/location/approve", json={
            "revision": state["revision"], "idempotency_key": "approve"}).json()
        state = client.post(f"/v1/chat/sessions/{sid}/products", json={
            "product_ids": ["era5-openmeteo", "pvgis-tmy"], "revision": state["active_card"]["revision"],
            "idempotency_key": "products"}).json()
        assert state["active_card"]["prompt"] == "Which actual year or years?"   # asked for the actual-year part
        state = client.post(f"/v1/chat/sessions/{sid}/turns", json={
            "text": "2018", "revision": state["revision"], "idempotency_key": "years"}).json()
        prepared = client.post(f"/v1/chat/sessions/{sid}/prepare", json={
            "revision": state["revision"], "idempotency_key": "prepare"}).json()
        data = prepared["active_card"]["data"]
        assert [plan["product"] for plan in data["plans"]] == ["historical", "tmy"]
        assert len(data["outputs"]) == 2 and "Typical year" in data["summary"]
        run = client.post(f"/v1/chat/sessions/{sid}/run", json={
            "revision": prepared["revision"], "idempotency_key": "run"}).json()
        assert [len(group) for group in run["job_groups"]] == [1, 1]
        assert run["job_ids"] == [group[0] for group in run["job_groups"]]
        for job_id in run["job_ids"]:
            app.state.runner.run(job_id)
        exported = client.post(f"/v1/chat/sessions/{sid}/export/compact")
        assert exported.status_code == 200


def test_catalog_point_lists_named_products_for_the_hover_card(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        body = client.get("/v1/catalog/point", params={"lat": 42.44, "lon": -76.5, "years": "2018,2019"}).json()
        assert body["years"] == [2018, 2019] and body["years_assumed"] is False
        assert {row["id"] for row in body["products"]} >= {"era5-openmeteo", "nsrdb-actual", "noaa-isd", "pvgis-tmy"}
        assert all(row["status"] in ("supported", "unknown", "none") for row in body["products"])
        assert client.get("/v1/catalog/point", params={"lat": 91, "lon": 0}).status_code == 422


def test_catalog_point_answers_repeat_places_from_a_cache(tmp_path, monkeypatch):
    import openepw.chat.products as products

    calls = []
    real = products.point_availability

    def counted(*args, **kwargs):
        calls.append(args[1:3])
        return real(*args, **kwargs)

    monkeypatch.setattr(products, "point_availability", counted)
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        first = client.get("/v1/catalog/point", params={"lat": 42.44, "lon": -76.5}).json()
        again = client.get("/v1/catalog/point", params={"lat": 42.44, "lon": -76.5}).json()
        assert first == again and calls == [(42.44, -76.5)]                  # the repeat is cached
        client.get("/v1/catalog/point", params={"lat": 42.44, "lon": -76.5, "years": "2018"})
        assert len(calls) == 2                                               # other years, other entry


def test_chat_progress_route_lists_no_steps_when_idle(tmp_path):
    from openepw.chat.coordinator import OfflineParser

    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service, chat_parser=OfflineParser())) as client:
        sid = client.post("/v1/chat/sessions").json()["id"]
        assert client.get(f"/v1/chat/sessions/{sid}/progress").json() == {"steps": []}

