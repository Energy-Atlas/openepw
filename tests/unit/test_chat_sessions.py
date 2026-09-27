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
