from openepw.agent.text import FUTURE, explicit_weather_years, place_part, read_product


def test_years_are_read_only_as_written():
    assert explicit_weather_years("AMY 2018 for Ithaca") == {2018}
    assert explicit_weather_years("2016-2018") == {2016, 2017, 2018}
    assert explicit_weather_years("2012 buildings in Boston") == set()
    assert explicit_weather_years("the 2010s") == set(range(2010, 2020))


def test_product_words():
    assert read_product("TMYx for Ithaca") == "tmyx"
    assert read_product("a typical meteorological year") == "tmy"
    assert read_product("AMY 2018") == "historical"
    assert read_product("Ithaca") is None


def test_place_part_strips_years_products_and_question_words():
    assert place_part("AMY 2018 for Ithaca NY") == "Ithaca NY"
    assert place_part("Boston, Austin, Denver 2019") == "Boston, Austin, Denver"
    assert place_part("what's available in Phoenix?") == "Phoenix"
    assert place_part("42.44, -76.5 TMYx") == "42.44, -76.5"
    assert place_part("2019 instead") == ""


def test_future_requests_are_recognised():
    assert FUTURE.search("SSP585 2050 for Denver")
    assert FUTURE.search("future weather")
    assert not FUTURE.search("AMY 2018 for Denver")


def test_coordinator_uses_the_shared_year_reader():
    from openepw.agent import text
    from openepw.chat import coordinator

    assert coordinator.explicit_weather_years is text.explicit_weather_years


def test_scenario_and_pathway_spellings_are_future_requests():
    for text in ("SSP5-8.5 2050 Denver", "SSP2-4.5", "ssp245", "RCP8.5 for Denver", "RCP 4.5",
                 "rcp85", "CMIP6 projections for Boston"):
        assert FUTURE.search(text), text


def test_state_and_country_codes_stay_in_the_place():
    assert place_part("Fort Wayne, IN") == "Fort Wayne, IN"
    assert place_part("Indianapolis IN 2018") == "Indianapolis IN"
    assert place_part("Graz, AT TMYx") == "Graz, AT"
    assert place_part("weather in Phoenix") == "Phoenix"


def test_decades_ranges_and_numbered_tmy_are_not_place_text():
    assert place_part("Ithaca 2010s") == "Ithaca"
    assert place_part("AMY from 2016 to 2018 for Ithaca") == "Ithaca"
    assert read_product("TMY3 for Denver") == "tmy" and place_part("TMY3 for Denver") == "Denver"


def test_head_counts_are_not_years():
    assert explicit_weather_years("over 2000 people") == set()
    assert explicit_weather_years("1900 residents in 2018") == {2018}


def test_redaction_covers_common_local_paths():
    from openepw.agent.text import safe_prompt

    for path in ("/tmp/site.epw", "/var/data/site.epw", "~/weather/site.epw", r"D:\data\site.epw"):
        assert safe_prompt(f"use {path} please") == "use [local path] please", path
