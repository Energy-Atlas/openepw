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


def test_offline_coordinate_entry_accepts_integer_degrees(tmp_path):
    from openepw.chat.coordinator import OfflineParser

    coordinator = ChatCoordinator(Service(), parser=OfflineParser(),
                                  path=tmp_path / "chat.sqlite")
    state = coordinator.create()
    result = coordinator.turn(state["id"], "40,-105 historical 2018", 0, "one")
    assert result["facts"]["location"]["lat"] == 40
    assert result["facts"]["location"]["lon"] == -105
    assert result["facts"]["years"] == [2018]


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
            if event["type"] == "message"] == ["first"]
    secret = coordinator.enqueue_turn(state["id"], "api_key=synthetic-secret", "third-key")
    deadline = time.monotonic() + 3
    while coordinator.queued_turn(secret["queue_id"])["state"] != "completed":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert "synthetic-secret" not in coordinator.queue_path.read_bytes().decode(errors="ignore")
