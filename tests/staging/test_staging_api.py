"""The signed-in staging check over HTTP, as the tester (ADR 0006). See conftest for settings."""

import pytest


def _first_choice(chat):
    """Pick the first option of a place choice, guided or the model's."""
    if chat.gate in ("choose_location", "ask_choice"):
        chat.answer(choice_ids=[chat.state["form"]["options"][0]["id"]])


def _to_plan_review(chat, text="AMY 2018 for Ithaca, NY", product="era5-openmeteo"):
    chat.say(text)
    _first_choice(chat)
    assert chat.gate == "review_location", chat.gate
    chat.answer(approve=True)
    assert chat.gate == "choose_products", chat.gate
    chat.answer(choice_ids=[product])
    assert chat.gate == "review_plan", chat.gate


def test_the_tester_is_signed_in_with_its_own_name(api, staging):
    session = api.get("/auth/session").json()
    assert session["signed_in"] and session["email"] == staging.name


def test_a_stub_run_with_a_typed_correction_and_the_file_list(chat):
    session = chat({"mode": "guided"})
    _to_plan_review(session)
    session.say("2019 instead")                                 # a correction in words (2026-11-04)
    assert session.gate == "review_plan" and session.state["years"] == [2019]
    session.answer(approve=True)
    assert session.state["job_ids"]
    state = session.wait_jobs()
    assert state["stage"] == "results" and session.gate == "next_steps"
    session.answer(choice_ids=["outputs"])
    assert any("Your files" in event["text"] for event in session.events())


def test_a_failed_output_is_retried_after_the_person_approves(chat):
    session = chat({"task": "S65", "mode": "guided"})          # Boston fails once on the stubs
    session.say("Boston, Denver 2016")
    session.answer(approve=True)
    session.answer(choice_ids=["era5-openmeteo"])
    session.answer(approve=True)
    session.wait_jobs()
    session.say("retry the failed outputs")
    assert session.gate == "review_retry", session.gate
    session.answer(choice_ids=["retry"])
    state = session.wait_jobs()
    assert len(state["job_ids"]) == 2
    assert any("PROVIDER_ERROR" in event["text"] for event in session.events())


def test_an_eval_script_drives_an_agent_stub_session(chat, api, staging):
    session = chat({"task": "S1", "mode": "agent"})
    assert session.state["mode"] == "agent"
    _to_plan_review(session, "AMY 2018 for Ithaca NY")
    session.answer(approve=True)
    assert session.wait_jobs()["stage"] == "results"


def test_a_new_request_leaves_the_results(chat):
    session = chat({"mode": "guided"})
    _to_plan_review(session)
    session.answer(approve=True)
    session.wait_jobs()
    session.answer(choice_ids=["new"])
    assert session.state["stage"] == "request"                  # the browser closes the results card


def test_stub_sessions_are_refused_without_the_tester(staging):
    import httpx

    with httpx.Client(base_url=staging.url, timeout=60) as anonymous:
        assert anonymous.post("/v2/agent/sessions", json={"stub": {"mode": "guided"}}).status_code == 401


@pytest.mark.real
def test_a_small_real_retrieval_downloads_an_epw(chat, api):
    session = chat()
    if session.state["mode"] == "agent":
        session.send({"type": "mode", "mode": "guided"})        # no model spend in this test
    _to_plan_review(session)
    session.answer(approve=True)
    state = session.wait_jobs(timeout=900)
    assert state["artifact_ids"], "the run produced no EPW"
    epw = api.get(f"/v1/artifacts/{state['artifact_ids'][0]}")
    assert epw.status_code == 200 and epw.text.startswith("LOCATION,")


@pytest.mark.agent
def test_an_availability_question_is_answered_in_words(chat):
    session = chat()
    assert session.state["mode"] == "agent", "staging has no model configured"
    session.say("Which actual-year weather products are available for Ithaca, NY in 2018?")
    assert session.gate is None and not session.state["job_ids"]
    replies = [event for event in session.events() if event["type"] == "assistant"]
    assert replies and "ERA5" in replies[-1]["text"]
