"""Deterministic place-text parsing: coordinates, lists, set descriptions and edits."""

import pytest

from openepw.models import OpenEPWError
from openepw.places.parse import (
    apply_edit,
    classify_places,
    describe_place_set,
    parse_coordinates,
    split_place_list,
)


@pytest.mark.parametrize("text, expected", [
    ("40.0, -105.3", [(40.0, -105.3)]),
    ("40 -105", [(40.0, -105.0)]),
    ("(40.0,-105.3), (41.5, -100)", [(40.0, -105.3), (41.5, -100.0)]),
    ("40,-105; 41,-100\n42.25, -71.1", [(40.0, -105.0), (41.0, -100.0), (42.25, -71.1)]),
    ("[[40, -105], [41, -100]]", [(40.0, -105.0), (41.0, -100.0)]),
    ("40.0N 105.3W", [(40.0, -105.3)]),
    ("33.9S, 151.2E", [(-33.9, 151.2)]),
    ("40,-105, 41,-100", [(40.0, -105.0), (41.0, -100.0)]),
])
def test_coordinates_keep_latitude_first(text, expected):
    assert parse_coordinates(text) == expected


@pytest.mark.parametrize("text", ["Boston", "Boston and Denver", "2018 historical", "40"])
def test_non_coordinate_text_is_not_coordinates(text):
    assert parse_coordinates(text) is None


@pytest.mark.parametrize("text", ["95, 10", "40, -190", "40, -105, 41"])
def test_invalid_coordinates_fail_without_repair(text):
    with pytest.raises(OpenEPWError) as error:
        parse_coordinates(text)
    assert error.value.issue.code == "INVALID_COORDINATES"


@pytest.mark.parametrize("text", ["bbox 40,-106,41,-105", "polygon (40,-105), (41,-105), (41,-104)",
                                  "the area between 40,-105 and 41,-104"])
def test_only_points_are_supported(text):
    with pytest.raises(OpenEPWError) as error:
        parse_coordinates(text)
    assert error.value.issue.code == "UNSUPPORTED_GEOGRAPHY"


@pytest.mark.parametrize("text, expected", [
    ("Boston; Denver; Austin", ["Boston", "Denver", "Austin"]),
    ("Boston, Denver and Austin", ["Boston", "Denver", "Austin"]),
    ("Cambridge, MA, Portland, Oregon and Reno", ["Cambridge, MA", "Portland, Oregon", "Reno"]),
    ("1. Paris, France\n2. Lyon\n- Nice", ["Paris, France", "Lyon", "Nice"]),
    ("Boston", ["Boston"]),
])
def test_place_lists_keep_region_qualifiers(text, expected):
    assert split_place_list(text) == expected


@pytest.mark.parametrize("text, kind, region, min_population, limit, missing", [
    ("all cities in America", "city", "America", None, None, ["region", "definition", "limit"]),
    ("every state capital in the United States", "capital", "the United States", None, None, ["limit"]),
    ("top 50 cities in Canada", "city", "Canada", None, 50, ["definition"]),
    ("all cities over 100,000 people in Texas", "city", "Texas", 100_000, None, ["limit"]),
    ("cities with population above 250k in Germany, top 20", "city", "Germany", 250_000, 20, []),
])
def test_set_descriptions_list_missing_fields(text, kind, region, min_population, limit, missing):
    draft = describe_place_set(text)
    assert draft is not None
    assert (draft.kind, draft.region_text, draft.min_population, draft.limit) == (
        kind, region, min_population, limit)
    # Region resolution happens later against GeoNames; only "America" is flagged here.
    assert draft.missing == missing


@pytest.mark.parametrize("text", ["Boston", "Cambridge, MA", "capital weather 2018", "40,-105"])
def test_ordinary_places_are_not_set_descriptions(text):
    assert describe_place_set(text) is None


@pytest.mark.parametrize("text, kind", [
    ("40, -105", "coordinates"),
    ("all cities in America", "descriptive"),
    ("Boston; Denver", "list"),
    ("Boston", "single"),
])
def test_classify_routes_each_input(text, kind):
    assert classify_places(text)["kind"] == kind


@pytest.mark.parametrize("text, expected", [
    ("remove 2", ["Boston", "Austin"]),
    ("drop Denver", ["Boston", "Austin"]),
    ("replace 3 with Portland, Oregon", ["Boston", "Denver", "Portland, Oregon"]),
    ("change Boston to Worcester", ["Worcester", "Denver", "Austin"]),
    ("add Reno and Salt Lake City", ["Boston", "Denver", "Austin", "Reno", "Salt Lake City"]),
])
def test_text_edits_change_the_preview_list(text, expected):
    assert apply_edit(["Boston", "Denver", "Austin"], text) == expected


def test_unrecognised_edit_returns_none_and_bad_index_fails():
    assert apply_edit(["Boston"], "looks good") is None
    with pytest.raises(OpenEPWError) as error:
        apply_edit(["Boston"], "remove 4")
    assert error.value.issue.code == "INVALID_EDIT"
