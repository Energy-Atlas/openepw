"""Request parts: statuses, origins, targeted resets, proposed years and stored sessions."""

import json

import pytest

from openepw.agent.gates import GateRequired, build_requests, check_plan_request, next_need
from openepw.agent.slots import change_options, parts, request_form, status
from openepw.agent.state import Facts, SessionState
from openepw.agent.text import reads_as_question

POINT = {"lat": 42.44, "lon": -76.5, "name": "Ithaca"}
REVIEW = {"key": "k1", "geography": POINT, "sampling": None, "point_count": 1,
          "points": [{**POINT, "standard_offset_minutes": -300}]}
ERA5 = {"id": "era5-openmeteo", "label": "ERA5 (Open-Meteo)",
        "request": {"product": "historical", "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}}
PVGIS = {"id": "pvgis-tmy", "label": "PVGIS TMY",
         "request": {"product": "tmy", "dataset_selections": [{"provider": "pvgis", "dataset": "PVGIS TMY"}]}}
SELECTION = {"product": "historical", "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}


def approved(**changes):
    facts = Facts(geography=POINT, review=REVIEW, approved_key="k1", chosen=[ERA5], years=[2018],
                  offers=[ERA5], plans=[{"plan_hash": "h", "output_count": 1}])
    for name, value in changes.items():
        setattr(facts, name, value)
    return facts


def by_part(facts):
    return {entry["part"]: entry for entry in parts(facts)}


def test_statuses_are_derived_from_the_facts():
    empty = by_part(Facts())
    assert {part: entry["status"] for part, entry in empty.items()} == {
        "place": "empty", "preference": "empty", "products": "empty", "years": "empty"}
    assert status(Facts(geography=POINT), "place") == "proposed"
    assert status(Facts(geography=POINT, review=REVIEW), "place") == "proposed"
    full = by_part(approved(product_type="historical"))
    assert {part: entry["status"] for part, entry in full.items()} == {
        "place": "confirmed", "preference": "confirmed", "products": "confirmed", "years": "confirmed"}
    assert full["place"]["value"] == "Ithaca" and full["products"]["value"] == "ERA5 (Open-Meteo)"
    assert status(approved(recheck=True), "products") == "recheck"
    assert status(approved(years=[2018, 2019], proposed_years=[2019]), "years") == "proposed"


def test_a_preference_from_a_model_filter_is_only_proposed():
    facts = Facts()
    facts.change("preference", ("tmy", None), by="model")
    assert status(facts, "preference") == "proposed"
    facts.change("preference", ("historical", None), by="text", seq=4)
    assert status(facts, "preference") == "confirmed"
    assert facts.origins["preference"] == {"by": "text", "seq": 4}
    assert by_part(facts)["preference"]["origin"] == "from your message"


def test_a_new_place_keeps_years_and_preference_and_rechecks_products():
    facts = approved(product_type="historical")
    facts.change("place", {"lat": 30.27, "lon": -97.74}, by="host")
    assert facts.review is None and facts.approved_key is None and facts.offers == [] and facts.plans == []
    assert facts.chosen == [ERA5] and facts.recheck and status(facts, "products") == "recheck"
    assert facts.years == [2018] and facts.product_type == "historical"


def test_a_new_place_before_any_product_choice_needs_no_recheck():
    facts = Facts()
    facts.change("place", POINT, by="text")
    assert not facts.recheck and status(facts, "products") == "empty"


def test_new_years_keep_the_chosen_products_but_drop_stale_offers():
    facts = approved()
    facts.change("years", [2019], by="text")
    assert facts.years == [2019] and facts.chosen == [ERA5] and not facts.recheck
    assert facts.offers == [] and facts.plans == []


def test_a_new_preference_rechecks_only_products_that_do_not_match():
    facts = approved(chosen=[ERA5])
    facts.change("preference", ("historical", None), by="text")
    assert not facts.recheck and facts.plans == []
    facts.change("preference", ("tmy", None), by="text")
    assert facts.recheck and facts.chosen == [ERA5]
    other = approved(chosen=[ERA5])
    other.change("preference", (None, "pvgis"), by="text")
    assert other.recheck


def test_choosing_products_clears_the_recheck():
    facts = approved(recheck=True)
    facts.change("products", [ERA5], by="form")
    assert not facts.recheck and facts.plans == []


def test_a_new_request_clears_every_part():
    facts = approved(proposed_years=[2018], recheck=True, product_type="tmy",
                     origins={"years": {"by": "text", "seq": 1}})
    facts.new_request()
    assert (facts.chosen, facts.years, facts.proposed_years, facts.origins, facts.recheck) == ([], [], [], {}, False)


@pytest.mark.parametrize("text", ["2018?", "what about 2018", "What's available for 2018 here?",
                                  "is 2018 available", "Can I get AMY 1950 in Austin?", "do you have 2019",
                                  "any data for 2017"])
def test_questions(text):
    assert reads_as_question(text)


@pytest.mark.parametrize("text", ["2018", "2016-2018", "2018 please", "AMY 2018 for Ithaca NY",
                                  "Ithaca, NY", "I need 2019 instead"])
def test_answers(text):
    assert not reads_as_question(text)


def test_proposed_years_never_reach_a_plan():
    facts = approved(years=[2018], proposed_years=[2018], plans=[])
    assert next_need(facts) == "confirm_request"
    with pytest.raises(GateRequired) as error:
        build_requests(facts)
    assert error.value.need == "confirm_request"
    with pytest.raises(GateRequired) as error:
        check_plan_request(facts, {**SELECTION, "years": [2018]})
    assert error.value.need == "confirm_request"


def test_confirmed_years_plan_while_another_year_is_only_proposed():
    facts = approved(years=[2017, 2018], proposed_years=[2018], plans=[])
    assert next_need(facts) == "plan"
    assert build_requests(facts)[0]["years"] == [2017]
    assert check_plan_request(facts, {**SELECTION, "years": []})["years"] == [2017]
    with pytest.raises(GateRequired) as error:
        check_plan_request(facts, {**SELECTION, "years": [2017, 2018]})
    assert error.value.need == "confirm_request"


def test_with_no_year_written_the_need_stays_years():
    assert next_need(approved(years=[], plans=[])) == "years"


def test_products_to_recheck_block_the_plan():
    facts = approved(recheck=True, plans=[])
    assert next_need(facts) == "choose_products"
    with pytest.raises(GateRequired) as error:
        build_requests(facts)
    assert error.value.need == "choose_products"


def test_confirming_years_shown_on_a_form():
    facts = approved(years=[1950, 2018], proposed_years=[1950])
    assert facts.confirm_years([1950, 2017], seq=9)
    assert facts.proposed_years == [] and facts.confirmed_years == [1950, 2018] and facts.plans == []
    assert facts.origins["years"] == {"by": "form", "seq": 9}
    assert not facts.confirm_years([2018])               # nothing was proposed


def test_the_request_summary_lists_parts_and_change_actions():
    facts = approved(years=[2018], proposed_years=[2018], product_type="historical",
                     origins={"years": {"by": "text", "seq": 3}})
    form = request_form(facts)
    assert form.kind == "request_summary" and form.gate == "review_request"
    assert [option.id for option in form.options] == ["change:place", "change:preference", "change:products",
                                                      "change:years"]
    assert [entry["part"] for entry in form.data["parts"]] == ["place", "preference", "products", "years"]
    assert "Years: 2018 (asked about, not confirmed) (proposed, from your message)" in form.summary
    assert "confirm the years" in form.summary
    # Products can be changed only once the place is approved.
    assert "change:products" not in [option.id for option in change_options(Facts(geography=POINT))]


def test_a_session_saved_before_the_parts_existed_loads_and_plans_as_before():
    saved = SessionState(id="s1", facts=approved(plans=[])).model_dump(mode="json")
    for name in ("proposed_years", "origins", "recheck"):
        del saved["facts"][name]
    state = SessionState.model_validate_json(json.dumps(saved))
    facts = state.facts
    assert (facts.proposed_years, facts.origins, facts.recheck) == ([], {}, False)
    assert next_need(facts) == "plan" and build_requests(facts)[0]["years"] == [2018]
    assert status(facts, "years") == "confirmed" and status(facts, "products") == "confirmed"
