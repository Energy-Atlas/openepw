"""Going back one step, product option details and the markdown plan summary."""

import pytest
from test_chat_sessions import Parser, Service

from openepw.chat.coordinator import (
    ChatActionError,
    ChatCoordinator,
    StaleSession,
    plan_summary_markdown,
)


def test_back_restores_the_previous_step_as_a_new_revision(tmp_path):
    chat = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    assert chosen["facts"]["location"]["id"] == "cambridge"
    back = chat.back(state["id"], chosen["revision"], "three")
    assert back["revision"] == chosen["revision"] + 1
    assert back["facts"] == first["facts"] and back["events"] == first["events"]
    assert back["active_card"]["kind"] == "choice"
    again = chat.back(state["id"], back["revision"], "four")
    assert again["facts"] == {} and again["events"] == []
    with pytest.raises(ChatActionError):
        chat.back(state["id"], again["revision"], "five")          # nothing earlier to return to


def test_back_is_refused_once_the_step_started_a_job(tmp_path):
    chat = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")

    def started(state):
        state["job_id"] = "job-1"
    after = chat._change(state["id"], first["revision"], "job", started)
    with pytest.raises(ChatActionError, match="job"):
        chat.back(state["id"], after["revision"], "two")


def test_product_choices_each_name_one_downloadable_product(tmp_path):
    class NoProduct(Parser):
        def parse_many(self, text):
            from openepw.harness.agent import AgentIntent
            if "tmy" in text:
                return [AgentIntent(kind="weather", product="tmy")]
            return [AgentIntent(kind="weather", lat=42.0, lon=-71.0)]

    chat = ChatCoordinator(Service(), parser=NoProduct(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    typed = chat.turn(state["id"], "42, -71", 0, "one")
    card = chat.approve_location(state["id"], typed["revision"], "approve")["active_card"]
    assert card["prompt"] == "Which weather product?"
    labels = {option["id"]: option["label"] for option in card["options"]}
    assert labels["nsrdb-actual"] == "NSRDB actual year · GOES v4"
    assert labels["noaa-isd"] == "NOAA ISD station observations"
    assert labels["pvgis-tmy"] == "PVGIS TMY 5.3 · SARAH3"
    assert not any(" or " in label or "Other" in label for label in labels.values())
    chosen = chat.answer(state["id"], card["revision"], "nsrdb-actual", "nsrdb")
    assert chosen["facts"]["product"] == "historical"
    assert chosen["facts"]["selections"] == [{"provider": "nsrdb", "dataset": "nsrdb-GOES-aggregated-v4-0-0",
                                              "product_id": None}]
    assert chosen["active_card"]["prompt"] == "Which actual year or years?"
    retyped = chat.turn(state["id"], "tmy instead", chosen["revision"], "tmy")
    assert "selections" not in retyped["facts"]                     # a new type asks for the product again
    assert all(option["group"] == "typical" for option in retyped["active_card"]["options"])


def test_plan_summary_is_a_markdown_bullet_per_planned_download():
    request = {"locations": [{"lat": 42.36, "lon": -71.06, "name": "Boston, Massachusetts, United States"},
                             {"lat": 39.74, "lon": -104.98}]}
    rows = [{"occurrence_index": 0, "period_start": "2018-01-01", "status": "planned",
             "dataset_selection": {"provider": "openmeteo", "dataset": "era5"}},
            {"occurrence_index": 1, "period_start": "2018-01-01", "status": "unsupported",
             "dataset_selection": None, "issue_codes": ["NO_SOURCE"]}]
    summary = plan_summary_markdown(request, rows)
    assert summary.splitlines() == [
        "- **Boston, Massachusetts, United States** · 2018 · openmeteo/era5 · planned",
        "- **39.7400, -104.9800** · 2018 · no source · unsupported (NO_SOURCE)",
    ]


def test_roll_back_to_an_agent_message_undoes_every_later_step(tmp_path):
    chat = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    question = next(event for event in first["events"] if event["type"] == "question")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    later = chat.turn(state["id"], "2016", chosen["revision"], "three")
    rolled = chat.back(state["id"], later["revision"], "four", to_event=question["id"])
    assert rolled["events"] == first["events"] and rolled["facts"] == first["facts"]
    assert rolled["revision"] == later["revision"] + 1
    with pytest.raises(ChatActionError):
        chat.back(state["id"], rolled["revision"], "five", to_event=999)


def test_explicit_years_in_the_message_count_even_when_the_model_omits_them(tmp_path):
    class ForgetfulModel(Parser):
        def parse_many(self, text):
            from openepw.harness.agent import AgentIntent
            if "Cambridge" in text:
                return super().parse_many(text)
            return [AgentIntent(kind="unknown")]          # the model dropped the year

    chat = ChatCoordinator(Service(), parser=ForgetfulModel(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    answered = chat.turn(state["id"], "2015", chosen["revision"], "three")
    assert answered["facts"]["years"] == [2015]
    ranged = chat.turn(state["id"], "2016 to 2018", answered["revision"], "four")
    assert ranged["facts"]["years"] == [2016, 2017, 2018]
    buildings = chat.turn(state["id"], "for 2012 buildings", ranged["revision"], "five")
    assert buildings["facts"]["years"] == [2016, 2017, 2018]      # a building count is not a year


def test_a_reply_that_changes_nothing_says_what_was_missing(tmp_path):
    class Coordinates(Parser):
        def parse_many(self, text):
            from openepw.harness.agent import AgentIntent
            if text.startswith("42"):
                return [AgentIntent(kind="weather", lat=42.0, lon=-71.0, product="historical")]
            return []

    chat = ChatCoordinator(Service(), parser=Coordinates(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    vague = chat.turn(state["id"], "somewhere nice", 0, "one")
    assert vague["active_card"]["prompt"] == "Where do you need weather?"
    assert "couldn't find a place" in vague["events"][-2]["text"]
    typed = chat.turn(state["id"], "42, -71", vague["revision"], "two")
    approved = chat.approve_location(state["id"], typed["revision"], "approve")
    asked = chat.answer(state["id"], approved["active_card"]["revision"], "era5-openmeteo", "product")
    assert asked["active_card"]["prompt"] == "Which actual year or years?"
    assert not any("couldn't" in (event.get("text") or "") for event in asked["events"][len(vague["events"]):])
    missed = chat.turn(state["id"], "the dry one", asked["revision"], "three")
    notice = missed["events"][-2]
    assert notice["data"] == {"role": "assistant", "unchanged": True}
    assert notice["text"] == "I couldn't find a year in that — try “2015” or “2015–2017”."
    assert missed["facts"] == asked["facts"]

def test_a_chosen_or_typed_location_is_summarised_for_approval(tmp_path):
    class Coordinates(Parser):
        def parse_many(self, text):
            import re

            from openepw.harness.agent import AgentIntent
            if match := re.search(r"(4[\d.]*), (-[\d.]+)$", text):
                lat, lon = float(match.group(1)), float(match.group(2))
                return [AgentIntent(kind="weather", lat=lat, lon=lon)]
            return super().parse_many(text)

    chat = ChatCoordinator(Service(), parser=Coordinates(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    review = chosen["active_card"]
    assert review["kind"] == "location_review" and review["prompt"] == "Is this the right location?"
    assert "**Cambridge, Massachusetts**" in review["data"]["summary"]
    assert "42.3700, -71.1100" in review["data"]["summary"]
    with pytest.raises(ChatActionError):
        chat.prepare(state["id"], chosen["revision"], "early")        # nothing runs before approval
    steered = chat.turn(state["id"], "41.5, -70.9", chosen["revision"], "three")
    assert steered["facts"]["location"]["lat"] == 41.5
    assert steered["active_card"]["kind"] == "location_review"
    assert "41.5000, -70.9000" in steered["active_card"]["data"]["summary"]
    with pytest.raises(StaleSession):
        chat.approve_location(state["id"], chosen["revision"], "stale")
    approved = chat.approve_location(state["id"], steered["revision"], "four")
    assert approved["active_card"]["prompt"] == "Which weather product?"   # historical was typed
    assert all(option["group"] == "actual" for option in approved["active_card"]["options"])
    assert approved["events"][-2]["data"]["role"] == "user"
    assert approved["events"][-2]["text"] == "Approved 41.5000, -70.9000 · typed coordinates"
    approved = chat.answer(state["id"], approved["active_card"]["revision"], "era5-openmeteo", "product")
    assert approved["active_card"]["kind"] == "plan_review"          # the years were already given
    moved = chat.turn(state["id"], "40.7, -74.0", approved["revision"], "five")
    assert moved["active_card"]["kind"] == "location_review"         # a new location needs approval again

def test_a_card_restored_by_roll_back_can_be_answered(tmp_path):
    chat = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    back = chat.back(state["id"], chosen["revision"], "three")
    assert back["active_card"]["revision"] == back["revision"]
    again = chat.answer(state["id"], back["active_card"]["revision"], "cambridgeport", "four")
    assert again["facts"]["location"]["id"] == "cambridgeport"

def test_a_location_correction_is_read_against_the_location_under_review(tmp_path):
    prompts = []

    class Steered(Parser):
        def parse_many(self, text):
            from openepw.harness.agent import AgentIntent
            prompts.append(text)
            if "Correcting" in text and "England" in text:
                return [AgentIntent(kind="weather", place="Cambridge, England")]
            if "Correcting" in text and "2019" in text:          # the model repeats the reviewed place
                return [AgentIntent(kind="weather", place="Cambridge, Massachusetts", years=[2019])]
            if "Correcting" in text and "tmy" in text:           # or repeats its coordinates
                return [AgentIntent(kind="weather", lat=42.37, lon=-71.11, product="tmy")]
            return super().parse_many(text)

    chat = ChatCoordinator(Service(), parser=Steered(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    years = chat.turn(state["id"], "2019 instead", chosen["revision"], "three")
    assert years["facts"]["years"] == [2019]
    assert years["facts"]["location"]["id"] == "cambridge"            # not geocoded again
    assert years["active_card"]["kind"] == "location_review"
    product = chat.turn(state["id"], "tmy please", years["revision"], "echo")
    assert product["facts"]["product"] == "tmy" and product["facts"]["location"]["id"] == "cambridge"
    years = product
    england = chat.turn(state["id"], "actually the one in England", years["revision"], "four")
    assert "Cambridge, Massachusetts" in prompts[-1] and "actually the one in England" in prompts[-1]
    assert england["active_card"]["kind"] == "choice" and england["facts"]["candidates"]

def test_several_products_of_one_kind_are_chosen_together(tmp_path):
    chat = ChatCoordinator(Service(), parser=Parser(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    chosen = chat.answer(state["id"], first["active_card"]["revision"], "cambridge", "two")
    card = chat.approve_location(state["id"], chosen["revision"], "three")["active_card"]
    assert card["prompt"] == "Which weather product?"
    both = chat.choose_products(state["id"], card["revision"], ["nsrdb-actual", "noaa-isd"], "four")
    assert [item["provider"] for item in both["facts"]["selections"]] == ["nsrdb", "noaa"]
    assert both["facts"]["product_labels"] == ["NSRDB actual year · GOES v4", "NOAA ISD station observations"]
    assert both["facts"]["product"] == "historical" and both["active_card"]["kind"] == "plan_review"
    assert both["events"][-2]["text"] == "NSRDB actual year · GOES v4; NOAA ISD station observations"
    request = chat._request(both["facts"])
    assert [(s.provider, s.dataset) for s in request.dataset_selections] == [
        ("nsrdb", "nsrdb-GOES-aggregated-v4-0-0"), ("noaa", "ISD global-hourly")]
    back = chat.back(state["id"], both["revision"], "five")
    with pytest.raises(ChatActionError, match="one kind"):
        chat.choose_products(state["id"], back["active_card"]["revision"], ["noaa-isd", "pvgis-tmy"], "six")
    with pytest.raises(ChatActionError):
        chat.choose_products(state["id"], back["active_card"]["revision"], [], "seven")
    typical = chat.choose_products(state["id"], back["active_card"]["revision"],
                                   ["nsrdb-tmy", "onebuilding:TMYx.2009-2023"], "eight")
    assert typical["facts"]["product"] == "tmy" and "years" not in typical["facts"]
    assert typical["facts"]["selections"][1]["variant"] == "TMYx.2009-2023"

@pytest.mark.parametrize("text, years", [
    ("2012", [2012]),
    ("2012-18", list(range(2012, 2019))),
    ("2012-2018", list(range(2012, 2019))),
    ("2012, 2013, 2015-16, 2020", [2012, 2013, 2015, 2016, 2020]),
    ("[2012, 2013, 2016, 2020]", [2012, 2013, 2016, 2020]),
    ("1998-02", [1998, 1999, 2000, 2001, 2002]),
])
def test_written_year_lists_and_ranges_are_read(text, years):
    from openepw.chat.coordinator import explicit_weather_years
    assert sorted(explicit_weather_years(text)) == years


def test_model_years_count_for_relative_phrases_but_not_invented_ones(tmp_path):
    class Relative(Parser):
        def parse_many(self, text):
            from openepw.harness.agent import AgentIntent
            if "Cambridge" in text:
                return super().parse_many(text)
            if "last three" in text:
                return [AgentIntent(kind="unknown", years=[2023, 2024, 2025])]
            if "since 2021" in text:
                return [AgentIntent(kind="unknown", years=[2021, 2022, 2023, 2024, 2025])]
            return [AgentIntent(kind="unknown", years=[1990])]            # nothing temporal was written

    chat = ChatCoordinator(Service(), parser=Relative(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    first = chat.turn(state["id"], "Historical Cambridge, MA 2012–2014", 0, "one")
    last = chat.turn(state["id"], "the last three years", first["revision"], "two")
    assert last["facts"]["years"] == [2023, 2024, 2025]
    since = chat.turn(state["id"], "everything since 2021", last["revision"], "three")
    assert since["facts"]["years"] == [2021, 2022, 2023, 2024, 2025]
    invented = chat.turn(state["id"], "sounds good", since["revision"], "four")
    assert invented["facts"]["years"] == [2021, 2022, 2023, 2024, 2025]