"""Text replies patch a previewed place list instead of replacing it."""

from test_chat_sessions import Parser
from test_places_geonames import FakeHttp

from openepw.chat.coordinator import ChatCoordinator
from openepw.config import RuntimeConfig
from openepw.service import WeatherService

GEOCODER = {
    "New York": [("New York, New York, United States", 40.71, -74.01)],
    "San Francisco": [("San Francisco, California, United States", 37.77, -122.42)],
    "Chicago": [("Chicago, Illinois, United States", 41.85, -87.65)],
    "los angeles": [("Los Angeles, California, United States", 34.05, -118.24)],
    "hawaii": [("Hawaii, United States", 19.6, -155.5)],
    "Reno": [("Reno, Nevada, United States", 39.53, -119.81)],
}


class Http(FakeHttp):
    def get_json(self, url, params=None, **kwargs):
        self.calls.append("geocode:" + params["name"])
        return {"results": [{"id": index + 1, "name": name, "latitude": lat, "longitude": lon}
                            for index, (name, lat, lon) in enumerate(GEOCODER.get(params["name"], []))]}


class Model(Parser):
    """Stands in for the model: a free-form reply names one place."""

    def parse_many(self, text):
        from openepw.harness.agent import AgentIntent
        for name in ("San Francisco", "Reno", "Chicago"):
            if name in text:
                return [AgentIntent(kind="weather", place=name)]
        return []


def _chat(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"), http=Http())
    return ChatCoordinator(service, parser=Model(), path=tmp_path / "chat.sqlite"), service


def _names(state):
    return [row.get("name") or row["input"] for row in state["facts"]["place_rows"]]


def test_should_be_y_fixes_the_row_that_was_not_found(tmp_path):
    chat, service = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "New York; sanfrancisco; Chicago", 0, "one")
    assert _names(state) == ["New York, New York, United States", "sanfrancisco", "Chicago, Illinois, United States"]
    service.http.calls.clear()
    fixed = chat.turn(state["id"], "should be San Francisco", state["revision"], "two")
    assert _names(fixed) == ["New York, New York, United States", "San Francisco, California, United States",
                             "Chicago, Illinois, United States"]
    assert service.http.calls == ["geocode:San Francisco"]                 # only the corrected row
    assert fixed["active_card"]["kind"] == "location_review"


def test_a_bare_place_fixes_the_missing_row_and_also_adds(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "New York; sanfrancisco; Chicago", 0, "one")
    bare = chat.turn(state["id"], "San Francisco", state["revision"], "two")
    assert _names(bare)[1] == "San Francisco, California, United States" and len(_names(bare)) == 3
    added = chat.turn(state["id"], "and Reno please", bare["revision"], "three")
    assert _names(added)[-1] == "Reno, Nevada, United States" and len(_names(added)) == 4
    only = chat.turn(state["id"], "only Chicago instead", added["revision"], "four")
    assert "place_rows" not in only["facts"] and only["facts"]["candidates"]   # an explicit override


def test_also_adds_even_while_a_row_is_missing(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "New York; sanfrancisco; Chicago", 0, "one")
    added = chat.turn(state["id"], "also Reno", state["revision"], "two")
    assert _names(added) == ["New York, New York, United States", "sanfrancisco",
                             "Chicago, Illinois, United States", "Reno, Nevada, United States"]


def test_a_place_and_region_pair_that_is_not_found_is_tried_as_two_places(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "New York, los angeles, hawaii, Chicago", 0, "one")
    assert _names(state) == ["New York, New York, United States", "Los Angeles, California, United States",
                             "Hawaii, United States", "Chicago, Illinois, United States"]


def test_a_model_failure_after_a_list_preview_keeps_the_preview(tmp_path):
    from openepw.harness.model import ModelUnavailable

    class TooMany(Model):
        def parse_many(self, text):
            raise ModelUnavailable("More than five requests in one turn; split the request")

    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"), http=Http())
    chat = ChatCoordinator(service, parser=TooMany(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    state = chat.turn(state["id"], "New York; Chicago; Reno", 0, "one")
    assert _names(state) == ["New York, New York, United States", "Chicago, Illinois, United States",
                             "Reno, Nevada, United States"]
    assert state["active_card"]["kind"] == "location_review"
    vague = chat.turn(state["id"], "hmm", state["revision"], "two")                  # nothing handled it
    assert "could not read" in vague["events"][-2]["text"]


def test_a_reply_that_names_a_listed_place_replaces_that_row(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "New York, los angeles, hawaii, Chicago", 0, "one")
    fixed = chat.turn(state["id"], "I meant Reno for hawaii", state["revision"], "two")
    assert _names(fixed) == ["New York, New York, United States", "Los Angeles, California, United States",
                             "Reno, Nevada, United States", "Chicago, Illinois, United States"]



def test_should_be_y_fixes_a_missing_row_that_looks_nothing_like_y(tmp_path):
    chat, _ = _chat(tmp_path)
    state = chat.create()
    state = chat.turn(state["id"], "New York; sf; Chicago", 0, "one")
    assert _names(state)[1] == "sf"
    fixed = chat.turn(state["id"], "should be San Francisco", state["revision"], "two")
    assert _names(fixed) == ["New York, New York, United States", "San Francisco, California, United States",
                             "Chicago, Illinois, United States"]