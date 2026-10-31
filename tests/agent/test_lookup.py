"""Agent request lookups (slots phase a): seen points and the look_up_products host tool."""

import asyncio
import json

from harness import Harness

from openepw.agent.model_port import ScriptedModel, call, say
from openepw.agent.policy_model import ModelPolicy
from openepw.agent.state import SEEN_LIMIT, SessionState, points_in

ITHACA = {"lat": 42.44, "lon": -76.50, "name": "Ithaca, New York, United States"}


def agent(tmp_path, steps):
    model = ScriptedModel(steps)
    return Harness(tmp_path, policy=ModelPolicy(model, turn_seconds=30)), model


def run(main):
    asyncio.run(main())


def test_points_in_walks_nested_results_within_bounds():
    data = {"candidates": [{"lat": 42.44, "lon": -76.5, "name": "Ithaca"},
                           {"latitude": 40.71, "longitude": -74.01}],
            "draft": {"rows": [{"point": {"lat": 1.0, "lon": 2.0}}]},
            "bad": {"lat": True, "lon": 3}, "far": {"lat": 120, "lon": 0}}
    assert sorted(points_in(data)) == [(1.0, 2.0), (40.71, -74.01), (42.44, -76.5)]
    assert points_in("text") == [] and points_in(None) == []
    assert len(points_in([{"lat": 0.0, "lon": float(index % 180)} for index in range(50)], limit=10)) == 10


def test_seen_points_are_deduplicated_and_capped():
    state = SessionState(id="s")
    state.see([(42.44001, -76.5), (42.44, -76.50004)])
    assert state.seen_points == [(42.44, -76.5)]
    state.see([(index / 100, 0.0) for index in range(SEEN_LIMIT + 5)])
    assert len(state.seen_points) == SEEN_LIMIT
    assert state.seen_points[-1] == ((SEEN_LIMIT + 4) / 100, 0.0)       # the oldest are dropped
    assert state.has_seen(round((SEEN_LIMIT + 4) / 100, 2) + 0.04, 0.04)
    assert not state.has_seen(42.44, -76.5)                              # dropped by the cap


def test_points_are_recorded_from_geocode_review_and_typed_text(tmp_path):
    h, _ = agent(tmp_path, [call("weather_geocode", {"query": "Ithaca, NY"}),
                            call("review_location", {"locations": ITHACA})])

    async def main():
        async with h:
            await h.say("AMY 2018 for Ithaca NY, near 40.71, -74.01")
            state = h.session.state
            assert h.form.gate == "review_location"
            assert state.has_seen(42.44, -76.5)                  # geocode and review results
            assert state.has_seen(40.71, -74.01)                 # typed by the person
            assert not state.has_seen(30.27, -97.74)
    run(main)


def test_points_typed_at_a_form_are_recorded(tmp_path):
    h, _ = agent(tmp_path, [call("ask_text", {"prompt": "Where exactly?"}), say("Thanks.")])

    async def main():
        async with h:
            await h.say("AMY 2018 somewhere")
            assert h.form.gate == "ask_text"
            await h.reply("33.9 S, 151.2 E")
            assert h.session.state.has_seen(-33.9, 151.2)
    run(main)


# look_up_products ---------------------------------------------------------------------------------
AUSTIN = {"lat": 30.27, "lon": -97.74, "name": "Austin, Texas, United States"}


def results(model, name):
    found = {}
    for request in model.requests:
        for item in request["items"]:
            if item["type"] == "tool_result" and item["name"] == name:
                found[item["call_id"]] = json.loads(item["output"])
    return list(found.values())


def refused(h):
    return [(event.data["tool"], event.data.get("code"), event.data.get("need")) for event in h.session.events()
            if event.type == "tool" and event.data.get("phase") == "refused"]


def labels(h):
    return [event.text for event in h.session.events() if event.data.get("code") == "LOOKUP_UNAPPROVED"]


def test_a_lookup_for_a_place_not_approved_is_labelled_once_and_stores_nothing(tmp_path):
    h, model = agent(tmp_path, [call("weather_geocode", {"query": "Ithaca, NY"}),
                                call("look_up_products", {"locations": ITHACA, "product": "historical"}),
                                call("look_up_products", {"locations": {**ITHACA, "lat": 42.4401}}),
                                say("ERA5 is listed for 2023 at Ithaca.")])

    async def main():
        async with h:
            await h.say("Does ERA5 have 2023 for Ithaca, NY?")
            facts = h.session.facts
            assert h.form is None
            assert facts.offers == [] and facts.chosen == [] and facts.geography is None
            assert facts.years == [2023]
            assert len(labels(h)) == 1 and "not approved yet" in labels(h)[0]
            assert "Ithaca, New York, United States (42.440, -76.500)" in labels(h)[0]
            first = results(model, "look_up_products")[0]["tool_data"]
            assert first["place"]["approved"] is False and first["years"] == [2023]
            assert first["products"] and all(item["kind"] == "actual year (AMY)" for item in first["products"])
            assert "request" not in json.dumps(first)
            inner = [event.data["by"] for event in h.session.events()
                     if event.type == "tool" and event.data.get("tool") == "weather_product_offers"
                     and event.data.get("phase") == "call"]
            assert inner == ["lookup", "lookup"]
    run(main)


def test_a_lookup_for_the_approved_place_shows_no_label(tmp_path):
    h, model = agent(tmp_path, [call("weather_geocode", {"query": "Ithaca, NY"}),
                                call("review_location", {"locations": ITHACA}),
                                call("look_up_products", {}),
                                call("look_up_products", {"locations": [ITHACA]}),
                                say("Here is what is listed.")])

    async def main():
        async with h:
            await h.say("What's available for 2018 in Ithaca, NY?")
            await h.approve()
            assert labels(h) == []
            found = results(model, "look_up_products")
            assert len(found) == 2
            for result in found:
                assert result["tool_data"]["place"]["approved"] is True
    run(main)


def test_omitted_locations_need_an_approved_place(tmp_path):
    h, model = agent(tmp_path, [call("look_up_products", {}), say("Which place?")])

    async def main():
        async with h:
            await h.say("What's available?")
            assert results(model, "look_up_products")[0]["code"] == "GATE_REQUIRED"
            assert refused(h) == [("look_up_products", "GATE_REQUIRED", "weather_geocode")]
    run(main)


def test_ungrounded_points_unwritten_years_and_large_lookups_are_refused(tmp_path):
    many = [{"lat": 42.44, "lon": -76.5}] * 26
    h, model = agent(tmp_path, [call("look_up_products", {"locations": AUSTIN}),
                                call("weather_geocode", {"query": "Ithaca, NY"}),
                                call("look_up_products", {"locations": ITHACA, "years": [2023]}),
                                call("look_up_products", {"locations": many}),
                                say("Done.")])

    async def main():
        async with h:
            await h.say("TMY for Ithaca, NY")
            codes = [result["code"] for result in results(model, "look_up_products")]
            assert codes == ["UNGROUNDED_POINT", "YEARS_NOT_WRITTEN", "INVALID_ARGUMENTS"]
            assert [code for _, code, _ in refused(h)] == codes
            assert h.session.state.mode == "agent" and labels(h) == []
    run(main)


def test_a_lookup_offline_without_a_catalog_says_so(tmp_path):
    h, model = agent(tmp_path, [call("weather_geocode", {"query": "Ithaca, NY"}),
                                call("look_up_products", {"locations": ITHACA}), say("Not verified.")])

    async def main():
        async with h:
            await h.say("What's listed for Ithaca, NY?")
            data = results(model, "look_up_products")[0]["tool_data"]
            assert data["catalog_loaded"] is False and "not loaded" in data["note"]
            assert "not verified; checked when planning" in {item["status"] for item in data["products"]}
    run(main)


def test_a_plan_after_a_lookup_still_needs_the_product_form(tmp_path):
    era5 = [{"provider": "openmeteo", "dataset": "era5"}]
    h, model = agent(tmp_path, [call("weather_geocode", {"query": "Ithaca, NY"}),
                                call("review_location", {"locations": ITHACA}),
                                call("look_up_products", {}),
                                call("weather_plan", {"request": {"product": "historical", "years": [2018],
                                                                  "dataset_selections": era5}}),
                                say("Choose products first.")])

    async def main():
        async with h:
            await h.say("AMY 2018 for Ithaca, NY")
            await h.approve()
            assert results(model, "weather_plan")[0]["need"] == "choose_products"
            assert h.session.facts.plans == []
    run(main)


def test_lookup_summary_statuses_stations_and_limits():
    from openepw.agent.host import lookup_label, lookup_summary

    def option(id, product, available, unverified, sites):
        return {"id": id, "label": id.upper(), "available": available, "unverified": unverified,
                "sites": sites, "request": {"product": product, "dataset_selections": []}}

    data = {"options": [option("era5", "historical", 1, 0, 1), option("noaa-isd", "historical", 0, 1, 1),
                        option("onebuilding:TMYx", "tmyx", 1, 0, 1)],
            "availability": {"years": [1950], "years_assumed": False, "catalog_loaded": True, "locations": [
                {"products": [{"option": "noaa-isd", "station": {"name": "AUSTIN", "distance_km": 8.25}}]}]}}
    summary = lookup_summary(data, approved=False, points=[AUSTIN])
    assert [(item["kind"], item["status"]) for item in summary["products"]] == [
        ("actual year (AMY)", "listed"), ("actual year (AMY)", "not verified; checked when planning"),
        ("typical year (TMYx)", "listed")]
    assert summary["products"][1]["station"] == "AUSTIN · 8.25 km"
    assert summary["catalog_loaded"] is True and "request" not in json.dumps(summary)

    several = lookup_summary({"options": [option("era5", "historical", 2, 1, 3)] * 31,
                              "availability": {"catalog_loaded": True}},
                             approved=True, points=[AUSTIN] * 7)
    assert several["products"][0]["status"] == "listed at 2 of 3 places"
    assert len(several["products"]) == 30 and several["more_products"] == 1
    assert len(several["place"]["points"]) == 5 and several["place"]["more_points"] == 2
    assert lookup_label([AUSTIN]) == ("Availability checked for Austin, Texas, United States (30.270, -97.740); "
                                      "this location is not approved yet. You'll confirm it before choosing "
                                      "products.")
    assert lookup_label([AUSTIN] * 5).endswith("and 2 more; these locations are not approved yet. "
                                               "You'll confirm them before choosing products.")


def test_the_prompt_sends_availability_questions_to_the_lookup(tmp_path):
    from openepw.agent.policy_model import SYSTEM, SYSTEM_WITHOUT_KNOWLEDGE

    for system in (SYSTEM, SYSTEM_WITHOUT_KNOWLEDGE):
        assert "look_up_products and say in one or two sentences, from its result only" in system
        assert "A lookup chooses nothing" in system and "product form states" not in system
    h, model = agent(tmp_path, [say("Hello.")])

    async def main():
        async with h:
            await h.say("AMY 2018 for Ithaca, NY")
            tools = model.requests[0]["tools"]
            assert "look_up_products" in tools and "weather_product_offers" not in tools
    run(main)
