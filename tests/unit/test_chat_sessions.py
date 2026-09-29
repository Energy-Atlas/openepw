from openepw.chat.coordinator import ChatCoordinator


class Parser:
    def parse_many(self, text):
        from openepw.harness.agent import AgentIntent

        if "Cambridge" in text:
            return [AgentIntent(kind="weather", place="Cambridge, MA", product="historical",
                                years=[2012, 2013, 2014])]
        if text == "2016":
            return [AgentIntent(kind="unknown", years=[2016])]
        return []


class Service:
    def geocode(self, query, *, mode="point"):
        from openepw.models import GeocodeResult, Location

        return GeocodeResult(query=query, candidates=[
            Location(id="cambridge", name="Cambridge, Massachusetts", lat=42.37, lon=-71.11),
            Location(id="cambridgeport", name="Cambridgeport, Massachusetts", lat=42.36, lon=-71.10),
        ])


def test_chat_keeps_location_product_and_years_after_followup(tmp_path):
    coordinator = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    first = coordinator.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    assert first["facts"]["years"] == [2012, 2013, 2014]
    assert first["facts"]["product"] == "historical"
    assert first["active_card"]["kind"] == "choice"
    chosen = coordinator.answer(state["id"], first["active_card"]["revision"],
                                "cambridge", "two")
    assert chosen["facts"]["location"]["id"] == "cambridge"
    changed = coordinator.turn(state["id"], "2016", chosen["revision"], "three")
    assert changed["facts"]["years"] == [2016]
    assert changed["facts"]["location"]["id"] == "cambridge"
    assert changed["facts"]["product"] == "historical"
    assert coordinator.get(state["id"])["facts"] == changed["facts"]
    assert coordinator.turn(state["id"], "2016", chosen["revision"], "three") == changed


def test_chosen_option_is_echoed_by_its_label(tmp_path):
    coordinator = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    first = coordinator.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    label = next(option["label"] for option in first["active_card"]["options"]
                 if option["id"] == "cambridge")
    chosen = coordinator.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    echo = next(event for event in reversed(chosen["events"]) if (event.get("data") or {}).get("choice"))
    assert echo["text"] == label
    assert echo["data"]["choice_id"] == "cambridge"


def test_stale_choice_is_rejected(tmp_path):
    from openepw.chat.coordinator import StaleSession

    coordinator = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    pending = coordinator.turn(state["id"], "Cambridge", 0, "one")
    try:
        coordinator.answer(state["id"], pending["active_card"]["revision"] - 1,
                           "cambridge", "two")
        assert False, "Stale selection should be rejected"
    except StaleSession as error:
        assert error.snapshot["revision"] == pending["revision"]


def test_model_years_must_be_grounded_in_weather_request(tmp_path):
    from openepw.harness.agent import AgentIntent

    class Overeager:
        def parse_many(self, _text):
            return [AgentIntent(kind="weather", lat=42.37, lon=-71.11,
                                product="historical", years=[2012, 2021, 2022, 2023])]

    coordinator = ChatCoordinator(Service(), parser=Overeager(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    result = coordinator.turn(state["id"],
                              "UBEM for 2012 buildings in Cambridge for 2021–2023", 0, "one")
    assert result["facts"]["years"] == [2021, 2022, 2023]


def test_chat_redacts_bearer_and_generic_key_assignments(tmp_path):
    coordinator = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    result = coordinator.turn(state["id"],
                              "api_key=example-secret OPENEPW_BEARER_TOKEN=another-secret",
                              0, "one")
    serialized = str(result)
    assert "example-secret" not in serialized
    assert "another-secret" not in serialized
    assert "[redacted]" in serialized
    next_state = coordinator.turn(state["id"], '{"api_key":"json-secret"}',
                                  result["revision"], "two")
    assert "json-secret" not in str(next_state)


def test_offline_coordinate_entry_accepts_integer_degrees(tmp_path):
    from openepw.chat.coordinator import OfflineParser

    coordinator = ChatCoordinator(Service(), parser=OfflineParser(),
                                  path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    result = coordinator.turn(state["id"], "40,-105 historical 2018", 0, "one")
    assert result["facts"]["location"]["lat"] == 40
    assert result["facts"]["location"]["lon"] == -105
    assert result["facts"]["location"]["standard_offset_minutes"] == -420
    assert result["facts"]["years"] == [2018]


def test_chat_geocoded_location_uses_local_standard_offset(tmp_path):
    from openepw.chat.coordinator import location_key, standard_time_summary
    from openepw.providers.openmeteo import interval_bounds

    coordinator = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    first = coordinator.turn(state["id"], "Historical Cambridge, MA 2012", 0, "one")
    chosen = coordinator.answer(state["id"], first["active_card"]["revision"],
                                "cambridge", "two")
    assert chosen["facts"]["location"]["standard_offset_minutes"] == -300
    facts = chosen["facts"] | {
        "location_approved": location_key(chosen["facts"]["location"]),
        "selections": [{"provider": "openmeteo", "dataset": "era5"}],
    }
    request = coordinator._request(facts)
    assert request.locations.standard_offset_minutes == -300
    start, end = interval_bounds({"location": request.locations.model_dump(),
                                  "start": "2012-01-01", "end": "2012-12-31"})
    assert start.isoformat() == "2012-01-01T05:00:00+00:00"
    assert end.isoformat() == "2013-01-01T05:00:00+00:00"
    assert "UTC-05:00" in standard_time_summary(request, facts["offset_estimated"])
    assert "estimated from longitude" in standard_time_summary(request, facts["offset_estimated"])


def test_chat_geography_estimates_missing_offsets_but_preserves_explicit_utc(tmp_path):
    from openepw.models import Location

    class GeographyService(Service):
        def locations(self, request):
            return request.locations if isinstance(request.locations, list) else [request.locations]

    coordinator = ChatCoordinator(GeographyService(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    selected = coordinator.set_geography(state["id"], [
        {"lat": 42.44, "lon": -76.5},
        Location(lat=42.44, lon=-76.5, standard_offset_minutes=0).model_dump(),
    ], 0, "geo")
    assert [point["standard_offset_minutes"] for point in selected["facts"]["geography"]] == [-300, 0]


def test_chat_area_uses_longitude_standard_time_for_sampling(tmp_path):
    from openepw.models import BoundingBox
    from openepw.planning.spatial import sample

    class GeographyService(Service):
        def locations(self, request):
            return sample(request.locations, request.sampling)

    coordinator = ChatCoordinator(GeographyService(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    area = BoundingBox(west=-76.6, east=-76.4, south=42.3, north=42.5).model_dump()
    selected = coordinator.set_geography(state["id"], area, 0, "geo")
    assert selected["facts"]["sampling"]["standard_offset"] == "longitude"
    assert {point["standard_offset_minutes"] for point in selected["facts"]["resolved_points"]} == {-300}
    from openepw.chat.coordinator import location_key
    facts = selected["facts"] | {
        "location_approved": location_key(selected["facts"]["geography"]),
        "product": "historical", "years": [2024],
        "selections": [{"provider": "openmeteo", "dataset": "era5"}],
    }
    assert coordinator._request(facts).sampling.standard_offset == "longitude"


def test_retry_replaces_durable_session_job_and_is_idempotent(tmp_path):
    from types import SimpleNamespace

    coordinator = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    started = coordinator._change(state["id"], 0, "seed", lambda item: item.update(job_id="old"))

    class Runner:
        calls = 0

        def retry_failed(self, job_id, key):
            assert job_id == "old"
            assert key.startswith("chat-retry:")
            self.calls += 1
            return SimpleNamespace(id="new")

    runner = Runner()
    retried = coordinator.retry(state["id"], started["revision"], "retry", runner)
    assert retried["job_id"] == "new"
    assert coordinator.get(state["id"])["job_id"] == "new"
    assert coordinator.retry(state["id"], started["revision"], "retry", runner) == retried
    assert runner.calls == 1


def test_durable_turn_queue_is_ordered_withdrawable_and_redacted(tmp_path):
    import threading
    import time

    entered, release = threading.Event(), threading.Event()

    class SlowParser:
        def parse_many(self, text):
            if text == "first":
                entered.set()
                release.wait(timeout=3)
            return []

    coordinator = ChatCoordinator(Service(), parser=SlowParser(), path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    first = coordinator.enqueue_turn(state["id"], "first", "first-key")
    assert entered.wait(timeout=2)
    second = coordinator.enqueue_turn(state["id"], "second", "second-key")
    assert second["state"] == "queued" and second["position"] == 2
    assert coordinator.enqueue_turn(state["id"], "second", "second-key")["queue_id"] == second["queue_id"]
    assert coordinator.withdraw_turn(second["queue_id"])["state"] == "cancelled"
    release.set()
    deadline = time.monotonic() + 3
    while coordinator.queued_turn(first["queue_id"])["state"] != "completed":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert [event["text"] for event in coordinator.get(state["id"])["events"]
            if (event.get("data") or {}).get("role") == "user"] == ["first"]
    secret = coordinator.enqueue_turn(state["id"], "api_key=synthetic-secret", "third-key")
    deadline = time.monotonic() + 3
    while coordinator.queued_turn(secret["queue_id"])["state"] != "completed":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert "synthetic-secret" not in coordinator.queue_path.read_bytes().decode(errors="ignore")
