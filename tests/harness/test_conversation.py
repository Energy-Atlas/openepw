"""A clarification answer completes the same request instead of starting over."""

import asyncio

from openepw.harness.agent import AgentIntent, ReferenceAgent
from openepw.harness.chat import ChatSession

CAMBRIDGE = {"id": "4931", "name": "Cambridge, Massachusetts, United States",
             "lat": 42.3751, "lon": -71.1056, "elevation": 12.0}
ALLSTON = {"id": "725", "name": "Allston, Massachusetts, United States",
           "lat": 42.3584, "lon": -71.1259, "elevation": 8.0}


class SequenceModel:
    def __init__(self, *intents):
        self.intents = list(intents)
        self.prompts = []

    def parse(self, prompt):
        self.prompts.append(prompt)
        return self.intents.pop(0)


class Port:
    def __init__(self, candidates=None):
        self.candidates = candidates or [CAMBRIDGE]
        self.calls = []

    async def call(self, name, **arguments):
        self.calls.append((name, arguments))
        if name == "weather_geocode":
            return {"candidates": self.candidates}
        if name == "weather_assess":
            product = arguments["query"]["request"]["product"]
            return {"options": [{"product": {"provider": "openmeteo",
                                             "dataset": product},
                                 "id": product,
                                 "eligibility": {"status": "unknown",
                                                 "access": "unknown",
                                                 "unknowns": ["coverage"]}}],
                    "locations": [{"ranked_option_ids": [product]}],
                    "issues": [{"code": "CATALOG_UNAVAILABLE"}], "snapshots": []}
        if name == "weather_discover":
            return {"availability": {"options": []}, "candidates": []}
        if name == "weather_plan":
            return {"plan_hash": "a" * 64, "output_count": 1, "estimated_calls": 1}
        if name == "plan_inspect":
            return {"kind": "weather", "selected_candidates": []}
        if name == "weather_submit":
            return {"id": "b" * 32, "state": "queued"}
        if name == "job_inspect":
            return {"id": "b" * 32, "state": "completed", "completed": 1,
                    "failed": 0, "artifacts": {"weather": []}}
        raise AssertionError(name)

    async def upload_file(self, path):
        raise AssertionError("unused")

    async def read_artifact(self, artifact_id):
        raise AssertionError("unused")


def test_short_answers_fill_draft_and_parse_once_per_turn():
    model = SequenceModel(
        AgentIntent(kind="weather", place="Cambridge, MA"),
        AgentIntent(kind="unknown", years=[2018]),
        AgentIntent(kind="unknown", product="historical"),
    )
    port = Port()
    chat = ChatSession(ReferenceAgent(port, model), port, model, auto_submit=False)

    async def journey():
        assert "product" in (await chat.handle("I need weather for Cambridge, MA"))
        assert "review_required" in (await chat.handle("2018"))
        answer = await chat.handle("historical")
        assert "review_required" in answer

    asyncio.run(journey())
    assert len(model.prompts) == 3
    assert [name for name, _ in port.calls].count("weather_plan") == 1
    request = next(args["request"] for name, args in port.calls if name == "weather_plan")
    assert request["years"] == [2018]
    assert request["locations"]["lat"] == CAMBRIDGE["lat"]


def test_numbered_geocode_choice_resumes_without_second_model_or_geocode():
    model = SequenceModel(AgentIntent(kind="weather", place="Cambridge, MA",
                                      product="historical", years=[2018]))
    port = Port([CAMBRIDGE, ALLSTON])
    chat = ChatSession(ReferenceAgent(port, model), port, model, auto_submit=False)

    async def journey():
        first = await chat.handle("Historical weather 2018 for Cambridge, MA")
        assert "1." in first and "2." in first
        second = await chat.handle("Cambridge, Massachusetts, United States")
        assert "review_required" in second

    asyncio.run(journey())
    assert len(model.prompts) == 1
    assert [name for name, _ in port.calls].count("weather_geocode") == 1
    request = next(args["request"] for name, args in port.calls if name == "weather_plan")
    assert request["locations"]["id"] == CAMBRIDGE["id"]


def test_exploration_reports_unknown_without_planning_or_fetching():
    model = SequenceModel(AgentIntent(kind="weather", place="Cambridge, MA",
                                      years=[2018], action="explore"))
    port = Port()
    chat = ChatSession(ReferenceAgent(port, model), port, model)

    answer = asyncio.run(chat.handle("Weather for 2018 in Cambridge MA: what do you have?"))

    assert "unknown" in answer.lower()
    assert "eligible to try" in answer.lower()
    assert "coverage" in answer.lower()
    assert "local inventory" in answer.lower()
    assert "weather_assess" in [name for name, _ in port.calls]
    assert "weather_plan" not in [name for name, _ in port.calls]


def test_cambridge_transcript_explores_then_submits_one_completed_request():
    model = SequenceModel(
        AgentIntent(kind="weather", place="Cambridge, MA"),
        AgentIntent(kind="unknown", years=[2018], action="explore"),
        AgentIntent(kind="unknown", action="explore"),
        AgentIntent(kind="weather", place="Cambridge MA", product="historical",
                    years=[2018]),
    )
    port = Port([CAMBRIDGE, ALLSTON])
    chat = ChatSession(ReferenceAgent(port, model), port, model)

    async def journey():
        assert "product" in await chat.handle(
            "I would like to do energy modeling for a building in Cambridge MA")
        options = await chat.handle("weather for 2018 - what do you have?")
        assert "TMY" in options and "1." in options
        assert "weather_plan" not in [name for name, _ in port.calls]
        assert "1." in await chat.handle("what do you have?")
        assert "1." in await chat.handle("historical weather 2018 for Cambridge MA")
        final = await chat.handle("Cambridge, Massachusetts, United States")
        assert "completed" in final

    asyncio.run(journey())
    names = [name for name, _ in port.calls]
    assert len(model.prompts) == 4
    assert names.count("weather_geocode") == 1
    assert names.count("weather_plan") == 1
    assert names.count("weather_submit") == 1


def test_bad_geocode_number_repeats_choices_without_geocoding_again():
    model = SequenceModel(AgentIntent(kind="weather", place="Cambridge, MA",
                                      product="historical", years=[2018]))
    port = Port([CAMBRIDGE, ALLSTON])
    chat = ChatSession(ReferenceAgent(port, model), port, model, auto_submit=False)

    async def journey():
        await chat.handle("Historical 2018 Cambridge MA")
        answer = await chat.handle("9")
        assert "1." in answer and "2." in answer
        partial = await chat.handle("Cambridge")
        assert "1." in partial and "2." in partial
        assert "review_required" in await chat.handle("1")

    asyncio.run(journey())
    assert len(model.prompts) == 1
    assert [name for name, _ in port.calls].count("weather_geocode") == 1


def test_geocode_choice_accepts_equivalent_punctuation():
    model = SequenceModel(AgentIntent(kind="weather", place="Cambridge MA",
                                      product="historical", years=[2018]))
    port = Port([CAMBRIDGE, ALLSTON])
    chat = ChatSession(ReferenceAgent(port, model), port, model, auto_submit=False)

    async def journey():
        await chat.handle("Historical 2018 Cambridge MA")
        return await chat.handle("Cambridge Massachusetts United States")

    assert "review_required" in asyncio.run(journey())
    assert len(model.prompts) == 1
    assert [name for name, _ in port.calls].count("weather_geocode") == 1


def test_exploration_location_choice_then_year_reuses_candidate():
    model = SequenceModel(
        AgentIntent(kind="weather", place="Cambridge MA", action="explore"),
        AgentIntent(kind="unknown", years=[2018], action="explore"),
    )
    port = Port([CAMBRIDGE, ALLSTON])
    chat = ChatSession(ReferenceAgent(port, model), port, model)

    async def journey():
        assert "1." in await chat.handle("What do you have for Cambridge MA?")
        assert "year" in (await chat.handle("1")).lower()
        return await chat.handle("2018")

    assert "eligible to try" in asyncio.run(journey()).lower()
    names = [name for name, _ in port.calls]
    assert names.count("weather_geocode") == 1
    assert names.count("weather_assess") == 5
    assert "weather_plan" not in names


def test_year_correction_replaces_draft_and_reset_discards_it():
    model = SequenceModel(
        AgentIntent(kind="weather", lat=42.37, lon=-71.1, product="historical",
                    years=[2018]),
        AgentIntent(kind="unknown", years=[2019]),
        AgentIntent(kind="weather", product="historical"),
    )
    port = Port()
    chat = ChatSession(ReferenceAgent(port, model), port, model, auto_submit=False)

    async def journey():
        assert "review_required" in await chat.handle("Historical 2018 at 42.37, -71.1")
        assert "review_required" in await chat.handle("Actually 2019")
        assert "cleared" in await chat.handle("/reset")
        assert "year" in (await chat.handle("historical")).lower()

    asyncio.run(journey())
    requests = [args["request"] for name, args in port.calls if name == "weather_plan"]
    assert [request["years"] for request in requests] == [[2018], [2019]]


def test_actual_year_and_tmy_conflict_requests_choice_without_plan():
    model = SequenceModel(AgentIntent(kind="weather", lat=42.37, lon=-71.1,
                                      product="tmy", years=[2018]))
    port = Port()
    chat = ChatSession(ReferenceAgent(port, model), port, model)

    answer = asyncio.run(chat.handle("TMY for 2018"))

    assert "2018" in answer and "TMY" in answer
    assert "weather_plan" not in [name for name, _ in port.calls]


def test_you_tell_me_uses_read_only_catalog_options():
    model = SequenceModel(
        AgentIntent(kind="weather", lat=42.37, lon=-71.1, years=[2018],
                    action="explore"),
        AgentIntent(kind="unknown"),
    )
    port = Port()
    chat = ChatSession(ReferenceAgent(port, model), port, model)

    async def journey():
        await chat.handle("What is available for 2018 at 42.37, -71.1?")
        return await chat.handle("you tell me")

    answer = asyncio.run(journey())
    assert "eligible to try" in answer.lower()
    assert [name for name, _ in port.calls].count("weather_assess") == 10
    assert "weather_plan" not in [name for name, _ in port.calls]


def test_new_future_task_does_not_inherit_weather_draft():
    model = SequenceModel(
        AgentIntent(kind="weather", place="Cambridge, MA"),
        AgentIntent(kind="unknown", method="morph", climate_scenario="ssp245",
                    climate_period=(2036, 2065)),
    )
    port = Port()
    chat = ChatSession(ReferenceAgent(port, model), port, model)

    async def journey():
        await chat.handle("Weather for Cambridge MA")
        return await chat.handle("Now morph a future SSP245 2036-2065 EPW")

    answer = asyncio.run(journey())
    assert "baseline" in answer.lower()
    assert "weather_plan" not in [name for name, _ in port.calls]
