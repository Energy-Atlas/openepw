import pytest

from openepw.agent.gates import GateRequired, build_requests, check_plan_request, next_need
from openepw.agent.state import Facts

POINT = {"lat": 42.44, "lon": -76.5, "standard_offset_minutes": -300, "name": "Ithaca"}
REVIEW = {"key": "k1", "geography": POINT, "sampling": None}
ERA5 = {"id": "era5-openmeteo", "label": "ERA5",
        "request": {"product": "historical",
                    "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}}
ERA5_CDS = {"id": "era5-cds", "label": "ERA5 CDS",
            "request": {"product": "historical",
                        "dataset_selections": [{"provider": "cds", "dataset": "reanalysis-era5-single-levels"}]}}
PVGIS = {"id": "pvgis-tmy", "label": "PVGIS TMY",
         "request": {"product": "tmy", "dataset_selections": [{"provider": "pvgis", "dataset": "PVGIS TMY"}]}}


def approved(**changes):
    facts = Facts(geography=POINT, review=REVIEW, approved_key="k1", chosen=[ERA5], years=[2018])
    for name, value in changes.items():
        setattr(facts, name, value)
    return facts


def test_the_gate_order():
    assert next_need(Facts()) == "where"
    assert next_need(Facts(candidates=[{"id": "1"}])) == "choose_location"
    assert next_need(Facts(place_set={"questions": [{}]})) == "place_set"
    assert next_need(Facts(geography=POINT)) == "review_location"
    assert next_need(Facts(geography=POINT, review=REVIEW)) == "review_location"
    assert next_need(Facts(geography=POINT, review=REVIEW, approved_key="k1")) == "choose_products"
    assert next_need(approved(years=[])) == "years"
    assert next_need(approved(chosen=[PVGIS], years=[])) == "plan"
    assert next_need(approved()) == "plan"
    assert next_need(approved(plans=[{"plan_hash": "h"}])) == "review_plan"
    assert next_need(approved(plans=[{"plan_hash": "h"}], job_ids=["j"])) == "jobs"
    started = {"plan_hash": "h", "output_count": 1, "job_id": "j"}
    assert next_need(approved(plans=[started], job_ids=["j"])) == "jobs"
    assert next_need(approved(plans=[started, {"plan_hash": "i", "output_count": 1}],
                              job_ids=["j"])) == "review_plan"
    assert next_need(Facts(stage="results")) == "next_steps"


def test_requests_use_the_approved_review_and_group_by_kind():
    requests = build_requests(approved(chosen=[ERA5, ERA5_CDS, PVGIS]))
    assert [(item["product"], [s["provider"] for s in item["dataset_selections"]]) for item in requests] == [
        ("historical", ["openmeteo"]), ("historical", ["cds"]), ("tmy", ["pvgis"])]
    assert all(item["locations"] == POINT and item["sampling"] == {} for item in requests)
    assert requests[0]["years"] == [2018] and requests[2]["years"] == []


def test_requests_refuse_unapproved_facts():
    with pytest.raises(GateRequired) as error:
        build_requests(approved(approved_key="other"))
    assert error.value.need == "review_location"
    with pytest.raises(GateRequired) as error:
        build_requests(approved(chosen=[]))
    assert error.value.need == "choose_products"
    with pytest.raises(GateRequired) as error:
        build_requests(approved(years=[]))
    assert error.value.need == "years"


def test_a_model_request_is_rewritten_to_the_approved_location():
    proposed = {"locations": {"lat": 0, "lon": 0}, "product": "historical", "years": [2018],
                "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}
    checked = check_plan_request(approved(), proposed)
    assert checked["locations"] == POINT and checked["years"] == [2018]


def test_a_model_request_cannot_add_products_or_years():
    with pytest.raises(GateRequired) as error:
        check_plan_request(approved(), {"product": "historical", "years": [2018],
                                        "dataset_selections": [{"provider": "nsrdb", "dataset": "x"}]})
    assert error.value.need == "choose_products"
    with pytest.raises(GateRequired) as error:
        check_plan_request(approved(), {"product": "historical", "years": [2017],
                                        "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]})
    assert error.value.need == "years"


TMYX = {"id": "tmyx-onebuilding", "label": "TMYx",
        "request": {"product": "tmyx", "dataset_selections": [{"provider": "onebuilding", "dataset": "TMYx"}]}}


def test_typical_requests_match_any_chosen_typical_offer():
    facts = approved(chosen=[PVGIS, TMYX], years=[])
    tmyx = {"product": "tmyx", "dataset_selections": TMYX["request"]["dataset_selections"]}
    checked = check_plan_request(facts, tmyx)
    assert [(item["provider"], item["dataset"]) for item in checked["dataset_selections"]] == [
        ("onebuilding", "TMYx")]
    only = approved(chosen=[TMYX], years=[])
    assert check_plan_request(only, {**tmyx, "product": "tmy"})["product"] == "tmyx"
    with pytest.raises(GateRequired):
        check_plan_request(facts, {"product": "historical", "dataset_selections": tmyx["dataset_selections"]})


def test_a_model_request_keeps_its_own_subset_of_stated_years():
    facts = approved(years=[2018, 2019])
    proposed = {"product": "historical", "years": [2018],
                "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}
    assert check_plan_request(facts, proposed)["years"] == [2018]
    assert check_plan_request(facts, {**proposed, "years": []})["years"] == [2018, 2019]
