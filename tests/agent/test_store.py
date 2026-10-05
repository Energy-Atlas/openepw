import pytest

from openepw.agent.interactions import Answer, Interaction, Option
from openepw.agent.state import Facts
from openepw.agent.store import SessionStore


def test_sessions_round_trip_with_their_open_form(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite")
    state = store.create()
    state.facts.years = [2018]
    state.form = Interaction(kind="choice", gate="choose_location", prompt="Which?",
                             options=[Option(id="1", label="Springfield, Illinois")])
    store.save(state)
    loaded = store.load(state.id)
    assert loaded == state and loaded.form.options[0].label == "Springfield, Illinois"
    with pytest.raises(KeyError):
        store.load("missing")


def test_events_are_numbered_per_session_and_paged(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite")
    first, second = store.create(), store.create()
    store.append(first.id, "user", "AMY 2018 for Ithaca")
    store.append(second.id, "user", "other")
    event = store.append(first.id, "tool", "weather_geocode", {"tool": "weather_geocode"})
    assert event.seq == 2 and event.data["tool"] == "weather_geocode"
    assert [item.seq for item in store.events(first.id)] == [1, 2]
    assert [item.text for item in store.events(first.id, after=1)] == ["weather_geocode"]


def test_snapshots_are_a_stack_per_session(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite")
    state = store.create()
    for years in ([2018], [2019], [2020]):
        state.facts.years = years
        store.push_snapshot(state)
    assert [item.facts.years for item in store.snapshots(state.id, 2)] == [[2020], [2019]]
    store.drop_snapshot(state.id)
    assert [item.facts.years for item in store.snapshots(state.id, 5)] == [[2019], [2018]]


def test_new_geography_drops_the_review_and_everything_after_it():
    facts = Facts(review={"key": "k"}, approved_key="k", offers=[{"id": "x"}], chosen=[{"id": "x"}],
                  plans=[{"plan_hash": "h"}], years=[2018], product_type="historical")
    facts.set_geography({"lat": 1, "lon": 2})
    assert (facts.review, facts.approved_key, facts.offers, facts.chosen, facts.plans) == (None, None, [], [], [])
    assert facts.years == [2018] and facts.product_type == "historical"


def test_a_new_request_keeps_results_but_clears_the_request():
    facts = Facts(stage="results", geography={"lat": 1, "lon": 2}, job_ids=["j"], finished_job_ids=["j"],
                  artifact_ids=["a"], years=[2018])
    facts.new_request()
    assert facts.stage == "request" and facts.geography is None and facts.job_ids == [] and facts.years == []
    assert facts.finished_job_ids == ["j"] and facts.artifact_ids == ["a"]


def test_answers_and_forms_are_strict():
    with pytest.raises(ValueError):
        Interaction(kind="dialog", prompt="x")
    assert Answer(interaction_id="i", revision=1, approve=True).choice_ids == []
