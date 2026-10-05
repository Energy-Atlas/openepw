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
