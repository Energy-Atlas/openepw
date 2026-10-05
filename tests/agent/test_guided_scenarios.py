"""Guided-mode scenarios from the design spec (§6), offline against the real MCP server."""

import asyncio

from harness import Harness, in_order


def run(tmp_path, scenario):
    async def main():
        async with Harness(tmp_path) as h:
            await scenario(h)
    asyncio.run(main())


def test_s1_actual_year_for_one_place_runs_after_reviews(tmp_path):
    async def scenario(h):
        assert h.form.gate == "where" and h.form.kind == "map_input"
        await h.say("AMY 2018 for Ithaca NY")
        assert h.form.gate == "review_location"
        assert h.form.data["points"][0]["standard_offset_minutes"] == -300
        await h.approve()
        assert h.form.gate == "choose_products" and h.form.multi
        assert "era5-openmeteo" in [option.id for option in h.form.options]
        await h.choose("era5-openmeteo")
        assert h.form.gate == "review_plan" and h.form.kind == "plan_review"
        await h.approve()
        assert h.form is None and h.session.facts.job_ids
        await h.session.follow_jobs(timeout=120)
        assert h.session.facts.artifact_ids, h.texts("assistant")
        assert "simulation_ready=false" in h.texts("assistant")[-1]
        assert h.form.gate == "next_steps"
        # job_inspect polling is host work and is not logged as tool events.
        assert in_order(h.tools(), ["weather_geocode", "weather_locations_review", "weather_product_offers",
                                    "weather_plan", "weather_submit", "artifact_inspect"])
        assert "job_inspect" not in h.tools()

    run(tmp_path, scenario)


def test_s2_an_ambiguous_name_asks_which_place(tmp_path):
    async def scenario(h):
        await h.say("Springfield 2018")
        assert h.form.gate == "choose_location" and len(h.form.options) == 3
        await h.choose(h.form.options[1].id)
        assert h.form.gate == "review_location"
        assert "Massachusetts" in h.form.data["points"][0]["name"]

    run(tmp_path, scenario)


def test_s3_coordinates_show_an_estimated_offset(tmp_path):
    async def scenario(h):
        await h.say("42.44, -76.5 TMYx")
        assert h.form.gate == "review_location" and h.form.data["offset_estimated"] is True
        assert "estimated" in h.form.summary
        await h.approve()
        assert h.form.gate == "choose_products" and h.session.facts.product_type == "tmyx"

    run(tmp_path, scenario)


def test_s4_a_place_list_is_reviewed_and_edited(tmp_path):
    async def scenario(h):
        await h.say("Boston, Austin, Denver 2019")
        assert h.form.gate == "review_location" and h.form.data["point_count"] == 3
        await h.say("remove 2")
        assert h.form.gate == "review_location" and h.form.data["point_count"] == 2
        assert [point["name"].split(",")[0] for point in h.form.data["points"]] == ["Boston", "Denver"]
        assert h.tools().count("weather_places_preview") == 2

    run(tmp_path, scenario)


def test_s10_a_year_with_a_reference_product_is_explained(tmp_path):
    async def scenario(h):
        await h.say("TMY 2015 for Denver")
        assert any("reference product" in text for text in h.texts("assistant"))
        assert h.session.facts.years == [] and h.session.facts.product_type == "tmy"
        assert h.form.gate == "review_location"

    run(tmp_path, scenario)


def test_s11_future_weather_is_suspended_without_tools(tmp_path):
    async def scenario(h):
        await h.say("SSP585 2050 for Denver")
        assert any("temporarily unavailable" in text for text in h.texts("assistant"))
        assert h.tools() == [] and h.form.gate == "where"

    run(tmp_path, scenario)


def test_s12_asking_what_is_available_offers_products_without_planning(tmp_path):
    async def scenario(h):
        await h.say("what's available in Phoenix?")
        assert h.form.gate == "review_location"
        await h.approve()
        assert h.form.gate == "choose_products" and h.form.options
        assert "weather_plan" not in h.tools()

    run(tmp_path, scenario)


def test_unread_text_keeps_the_form_and_says_why(tmp_path):
    async def scenario(h):
        await h.say("AMY 2018 for Ithaca NY")
        await h.approve()
        form = h.form                      # the product choice: text here is not read as a place
        await h.say("hmm")
        assert h.form == form and h.texts("assistant")[-1].startswith("Guided mode reads")

    run(tmp_path, scenario)
