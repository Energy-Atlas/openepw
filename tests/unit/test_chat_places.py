"""Chat coordinator place routing: list previews, text edits and clarified place sets."""

from test_places_service import Http

from openepw.chat.coordinator import ChatCoordinator, OfflineParser
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def _chat(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"), http=Http())
    chat = ChatCoordinator(service, parser=OfflineParser(), path=tmp_path / "chat.sqlite")
    return chat, service


def _texts(state, role=None, kind=None):
    return [event["text"] for event in state["events"]
            if (kind is None or event["type"] == kind)
            and (role is None or (event.get("data") or {}).get("role") == role)]


def test_place_list_previews_points_without_a_location_choice(tmp_path):
    chat, service = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "Boston; Denver; Nowhereville 2018 historical", 0, "one")
    facts = state["facts"]
    assert [(point["lat"], point["lon"]) for point in facts["geography"]] == [(42.36, -71.06), (39.74, -104.98)]
    assert facts["resolved_points"] == facts["geography"]
    assert "candidates" not in facts and facts["product"] == "historical" and facts["years"] == [2018]
    listing = _texts(state, role="assistant")[-1]
    assert "1. Boston, Massachusetts, United States" in listing and "top of 2 matches" in listing
    assert "3. 'Nowhereville' not found" in listing
    assert "Previewed 2 of 3 places" in _texts(state, kind="tool")[-1]
    review = state["active_card"]                                  # the list is approved first
    assert review["kind"] == "location_review" and review["prompt"] == "Are these the right locations?"
    assert review["data"]["summary"].startswith("**2 places** · 1 not found and left out · Boston")
    service.http.calls.clear()
    edited = chat.turn(state["id"], "remove 3", state["revision"], "two")
    assert len(edited["facts"]["place_rows"]) == 2 and service.http.calls == []   # pinned, not re-geocoded
    assert edited["active_card"]["kind"] == "location_review"
    approved = chat.approve_location(state["id"], edited["revision"], "approve")
    assert approved["active_card"]["kind"] == "plan_review"        # Run still needs review
    assert _texts(approved, role="user")[-1].startswith("Approved 2 places")
    replaced = chat.turn(state["id"], "replace 1 with Denver", approved["revision"], "three")
    assert replaced["facts"]["geography"][0]["name"] == "Denver, Colorado, United States"
    assert service.http.calls == ["geocode:Denver"]
    assert replaced["active_card"]["kind"] == "location_review"   # an edited list is approved again


def test_coordinate_lists_preview_and_single_places_keep_the_choice_flow(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "40,-105; 41,-100 tmy", 0, "one")
    assert len(state["facts"]["geography"]) == 2 and state["facts"]["product"] == "tmy"
    single = chat.create()
    single = chat.turn(single["id"], "historical 2018 weather in Boston", 0, "two")
    assert single["active_card"]["kind"] == "choice" and len(single["facts"]["candidates"]) == 2


def test_descriptive_sets_ask_one_question_at_a_time_then_preview(tmp_path):
    chat, service = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "tmy for all cities in Texas", 0, "one")
    card = state["active_card"]
    assert card["kind"] == "choice" and "minimum population" in card["prompt"]
    assert "cities" not in "".join(service.http.calls)            # nothing listed yet
    option = next(item for item in card["options"] if item["label"] == "100,000")
    state = chat.answer(state["id"], card["revision"], option["id"], "two")
    card = state["active_card"]
    assert "How many" in card["prompt"]
    state = chat.answer(state["id"], card["revision"], card["options"][0]["id"], "three")   # 10
    names = [point["name"] for point in state["facts"]["geography"]]
    assert names == ["Houston, Texas, United States", "Dallas, Texas, United States",
                     "Austin, Texas, United States"]
    assert "GeoNames" in _texts(state, role="assistant")[-1]
    assert state["facts"]["product"] == "tmy" and "place_set" not in state["facts"]


def test_typed_answers_fill_a_set_and_unsupported_geometry_is_explained(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "all cities in America", 0, "one")
    assert state["active_card"]["prompt"].startswith("Which region?")
    state = chat.turn(state["id"], "United States, over 1m, top 2", state["revision"], "two")
    assert [point["name"] for point in state["facts"]["geography"]] == [
        "Houston, Texas, United States", "Dallas, Texas, United States"]
    other = chat.create()
    other = chat.turn(other["id"], "bbox 40,-106,41,-105", 0, "three")
    assert "Only points or lists of points" in _texts(other, role="assistant")[-1]
