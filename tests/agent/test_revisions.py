"""Corrections typed on the plan review (owner, 2026-11-04): read by the host in both modes."""

import asyncio

import pytest
from harness import Harness

from openepw.agent.model_port import ScriptedModel, call
from openepw.agent.policy_model import ModelPolicy
from openepw.agent.revisions import Revision, match_offers, read_revision

ITHACA = {"lat": 42.44, "lon": -76.50, "name": "Ithaca, New York, United States"}
OFFERS = [{"id": item, "label": label} for item, label in (
    ("era5-openmeteo", "ERA5 actual year · Open-Meteo"), ("era5-cds", "ERA5 actual year · Copernicus CDS"),
    ("era5land-openmeteo", "ERA5-Land actual year · Open-Meteo"),
    ("era5land-cds", "ERA5-Land actual year · Copernicus CDS"), ("nsrdb-actual", "NSRDB actual year · GOES v4"),
    ("noaa-isd", "NOAA ISD station observations"))]


@pytest.mark.parametrize(("text", "expected"), [
    ("2019 instead", Revision("years", "2019")),
    ("2019 instead of 2018", Revision("years", "2019")),
    ("make it 2018-2020", Revision("years", "2018-2020")),
    ("can you use 2020 instead?", Revision("years", "2020")),
    ("change the years", Revision("years", "", explicit=True)),
    ("years: 2017 and 2018", Revision("years", "2017 and 2018", explicit=True)),
    ("add NSRDB", Revision("products", "NSRDB", "add", explicit=True)),
    ("drop the CDS products", Revision("products", "the CDS products", "remove", explicit=True)),
    ("try another source", Revision("products", "", explicit=True)),
    ("change location to Boston", Revision("place", "Boston", explicit=True)),
    ("another place", Revision("place", "", explicit=True)),
    ("use Boston instead", Revision(None, "Boston")),
    ("use TMYx instead", Revision("preference", "TMYx")),
])
def test_corrections_are_read(text, expected):
    assert read_revision(text) == expected


@pytest.mark.parametrize("text", ["why is CDS slow?", "looks good", "run it", "no", "Boston", "what about 2019?"])
def test_other_text_is_left_to_the_other_rules(text):
    assert read_revision(text) is None


def test_source_names_match_offers():
    ids = lambda value: [offer["id"] for offer in match_offers(value, OFFERS) or []]   # noqa: E731
    assert ids("NSRDB") == ["nsrdb-actual"]
    assert ids("CDS") == ["era5-cds", "era5land-cds"]
    assert ids("ERA5 on CDS") == ["era5-cds"]
    assert ids("ERA5-Land on Open-Meteo and NSRDB") == ["era5land-openmeteo", "nsrdb-actual"]
    assert match_offers("NSRDB and Boston", OFFERS) is None


async def to_plan_review(h):
    await h.say("AMY 2018 for Ithaca NY")
    await h.approve()
    await h.choose("era5-openmeteo")
    assert h.form.gate == "review_plan"


def test_typed_years_replan_and_show_the_review_again(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            await h.say("2019 instead of 2018")
            assert h.form.gate == "review_plan"
            assert h.session.facts.years == [2019] and h.session.facts.plans[0]["years"] == [2019]
    asyncio.run(main())


def test_add_or_remove_a_source_opens_the_products_with_it_applied(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            await h.say("add ERA5-Land on Open-Meteo")
            assert h.form.gate == "choose_products" and not h.session.facts.plans
            assert h.form.data["selected"] == ["era5-openmeteo", "era5land-openmeteo"]
            await h.choose(*h.form.data["selected"])
            assert h.form.gate == "review_plan" and len(h.session.facts.plans) == 1
            await h.say("remove ERA5-Land")
            assert h.form.gate == "choose_products" and h.form.data["selected"] == ["era5-openmeteo"]
            await h.choose("era5-openmeteo")
            assert h.form.gate == "review_plan"
            await h.say("add NSRDB")                 # not offered here (no key offline): said so
            assert h.form.gate == "choose_products" and "No offered product matches" in h.texts("assistant")[-1]
    asyncio.run(main())


def test_naming_only_the_part_opens_its_form(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            await h.say("change the years")
            assert h.form.data.get("change") == "years" and not h.session.facts.plans
    asyncio.run(main())


def test_a_new_place_in_words_goes_to_the_location_review(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            await h.say("use Springfield, Massachusetts instead")
            assert h.form.gate == "review_location"
            assert "Springfield" in h.form.data["points"][0]["name"] and not h.session.facts.plans
    asyncio.run(main())


def test_agent_mode_reads_the_correction_without_a_model_call(tmp_path):
    model = ScriptedModel([
        call("review_location", {"locations": ITHACA}), call("choose_products", {}),
        call("weather_plan", {"request": {"product": "historical", "years": [2018],
                                          "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}}),
        call("review_plan")])

    async def main():
        async with Harness(tmp_path, policy=ModelPolicy(model, turn_seconds=30)) as h:
            await to_plan_review(h)
            asked = len(model.requests)
            await h.say("2019 instead")
            assert len(model.requests) == asked
            assert h.form.gate == "review_plan" and h.session.facts.plans[0]["years"] == [2019]
            await h.approve()
            assert h.session.facts.job_ids
    asyncio.run(main())
