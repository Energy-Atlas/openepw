"""Service previews for place lists, coordinates and clarified place sets."""

import pytest
from test_places_geonames import FakeHttp

from openepw.config import RuntimeConfig
from openepw.models import OpenEPWError, WeatherRequest
from openepw.places.models import PlaceSetQuery
from openepw.service import WeatherService

GEOCODER = {
    "Boston": [("Boston, Massachusetts, United States", 42.36, -71.06),
               ("Boston, Lincolnshire, United Kingdom", 52.98, -0.03)],
    "Denver": [("Denver, Colorado, United States", 39.74, -104.98)],
    "Nowhereville": [],
}


class Http(FakeHttp):
    def get_json(self, url, params=None, **kwargs):
        self.calls.append("geocode:" + params["name"])
        return {"results": [{"id": index + 1, "name": name, "latitude": lat, "longitude": lon}
                            for index, (name, lat, lon) in enumerate(GEOCODER[params["name"]])]}


def _service(tmp_path):
    return WeatherService(RuntimeConfig(data_root=tmp_path), http=Http())


def test_list_preview_takes_top_matches_and_keeps_ambiguity_visible(tmp_path):
    preview = _service(tmp_path).preview_places(["Boston", "Denver", "40, -105.3"])
    assert [(row.index, row.name, row.source, row.ambiguous) for row in preview.rows] == [
        (1, "Boston, Massachusetts, United States", "geocoder", True),
        (2, "Denver, Colorado, United States", "geocoder", False),
        (3, "40.0000, -105.3000", "coordinates", False),
    ]
    assert preview.rows[0].candidate_count == 2
    assert [(point.lat, point.lon) for point in preview.locations] == [(42.36, -71.06), (39.74, -104.98), (40.0, -105.3)]
    assert [feature["properties"]["index"] for feature in preview.geojson["features"]] == [1, 2, 3]
    assert any(issue.code == "AMBIGUOUS_LOCATION" for issue in preview.issues)
    # The locations are a valid request geography as returned.
    WeatherRequest.model_validate({"locations": [point.model_dump() for point in preview.locations], "years": [2018]})


def test_unresolved_names_are_reported_not_dropped(tmp_path):
    preview = _service(tmp_path).preview_places(["Denver", "Nowhereville"])
    assert [row.status for row in preview.rows] == ["resolved", "unresolved"]
    assert len(preview.locations) == 1
    assert any(issue.code == "UNRESOLVED_PLACE" and "Nowhereville" in issue.message for issue in preview.issues)


def test_coordinate_lists_expand_and_same_input_gives_same_digest(tmp_path):
    service = _service(tmp_path)
    first = service.preview_places(["40,-105; 41,-100"])
    assert len(first.rows) == 2 and first.digest == service.preview_places(["40,-105; 41,-100"]).digest


def test_descriptive_items_and_oversized_lists_are_refused(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(OpenEPWError) as error:
        service.preview_places(["all cities in Texas"])
    assert error.value.issue.code == "NEEDS_CLARIFICATION"
    with pytest.raises(OpenEPWError) as error:
        service.preview_places(["40,-105"] * 1001)
    assert error.value.issue.code == "RESOURCE_LIMIT"


def test_interpret_routes_text_and_asks_before_enumerating(tmp_path):
    service = _service(tmp_path)
    assert service.interpret_places("Boston; Denver")["kind"] == "list"
    assert service.interpret_places("40, -105")["points"] == [[40.0, -105.0]]
    assert service.interpret_places("bbox 40,-106,41,-105")["kind"] == "invalid"
    vague = service.interpret_places("all cities in America")
    assert vague["kind"] == "descriptive" and vague["query"] is None
    assert [question["field"] for question in vague["questions"]] == ["region", "definition", "limit"]
    assert "cities" not in "".join(service.http.calls)        # nothing enumerated before clarification
    georgia = service.interpret_places("all cities over 5000 people in Georgia, top 10")
    assert [option["label"] for option in georgia["questions"][0]["options"]] == [
        "Georgia", "Georgia, United States"]
    complete = service.interpret_places("top 2 cities over 100k in Texas")
    assert complete["questions"] == []
    assert complete["query"] == {"kind": "city", "country": "US", "admin1": "TX",
                                 "min_population": 100000, "limit": 2}


def test_place_set_preview_carries_geonames_attribution(tmp_path):
    preview = _service(tmp_path).place_set(
        PlaceSetQuery(kind="city", country="US", admin1="TX", min_population=100_000, limit=2))
    assert [row.name for row in preview.rows] == ["Houston, Texas, United States", "Dallas, Texas, United States"]
    assert preview.rows[0].population == 2_300_000 and preview.rows[0].source == "geonames"
    assert any("GeoNames" in item for item in preview.attribution)
    assert any(issue.code == "PLACE_SET_TRUNCATED" for issue in preview.issues)
