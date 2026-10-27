"""Agent request lookups (slots phase a): seen points and the look_up_products host tool."""

import asyncio

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
