"""Request parts in both modes: questions at forms, the request summary, Change and Back (slots design)."""

import asyncio
import json

from harness import Harness

from openepw.agent import host
from openepw.agent.cli import parse_reply, render_form
from openepw.agent.interactions import Answer, Interaction, Option
from openepw.agent.model_port import ScriptedModel, call, say
from openepw.agent.policy_model import SYSTEM, SYSTEM_WITHOUT_KNOWLEDGE, ModelPolicy
from openepw.agent.slots import status
from openepw.agent.tools import ASK_TOOLS, NEED_TOOL

ITHACA = {"lat": 42.44, "lon": -76.50, "name": "Ithaca, New York, United States"}
ERA5 = [{"provider": "openmeteo", "dataset": "era5"}]


def run(main):
    asyncio.run(main())


async def change(h, part):
    await h.choose(f"change:{part}")


async def to_plan_review(h, text="AMY 2018 for Ithaca, NY"):
    await h.say(text)
    await h.approve()
    await h.choose("era5-openmeteo")


def plan_hashes(h):
    return [plan["plan_hash"] for plan in h.session.facts.plans]


def test_guided_change_years_keeps_place_and_products_and_back_undoes_it(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            assert h.form.gate == "review_plan"
            assert {option.id for option in h.form.options} == {
                "change:place", "change:preference", "change:products", "change:years"}
            assert [entry["status"] for entry in h.form.data["parts"]] == ["confirmed"] * 4
            first = plan_hashes(h)
            await change(h, "years")
            assert h.form.gate == "years" and h.form.data["change"] == "years"
            assert "(now 2018)" in h.form.data["hint"] and h.session.facts.plans == []
            await h.session.back()                          # Back undoes the Change
            assert h.form.gate == "review_plan" and plan_hashes(h) == first
            await change(h, "years")
            await h.reply("2019")
            facts = h.session.facts
            assert h.form.gate == "review_plan" and facts.years == [2019]
            assert [offer["id"] for offer in facts.chosen] == ["era5-openmeteo"] and not facts.recheck
            assert facts.approved_key == facts.review["key"] and plan_hashes(h) != first
            assert facts.plans[0]["years"] == [2019]
    run(main)


def test_guided_change_products_preselects_the_current_choice(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            await change(h, "products")
            assert h.form.kind == "product_choice" and h.form.data["selected"] == ["era5-openmeteo"]
            assert "[selected]" in render_form(h.form)
            answer = parse_reply(h.form, "ok")
            assert answer is not None and answer.choice_ids == ["era5-openmeteo"]
            await h.session.answer(answer)
            assert h.form.gate == "review_plan"
    run(main)


def test_guided_change_place_rechecks_products_and_keeps_years(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            await change(h, "place")
            assert h.form.kind == "map_input" and "Now: Ithaca" in h.form.summary
            await h.reply("Boston")
            assert h.form.gate == "review_location"
            assert status(h.session.facts, "products") == "recheck" and h.session.facts.years == [2018]
            await h.approve()
            assert h.form.kind == "product_choice" and h.form.data["recheck"]
            assert h.form.data["selected"] == ["era5-openmeteo"]
            await h.choose("era5-openmeteo")
            assert h.form.gate == "review_plan" and "Boston" in h.form.summary
    run(main)


def test_a_question_at_the_years_form_needs_the_summary_and_a_plain_year_does_not(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("AMY for Ithaca, NY")
            await h.approve()
            await h.choose("era5-openmeteo")
            assert h.form.gate == "years"
            await h.reply("Is 2018 available?")
            facts = h.session.facts
            assert facts.proposed_years == [2018] and facts.plans == []
            assert h.form.kind == "request_summary" and "weather_plan" not in h.tools()
            await h.approve()
            assert h.form.gate == "review_plan"
            assert h.session.facts.proposed_years == [] and h.session.facts.plans[0]["years"] == [2018]
        async with Harness(tmp_path / "plain") as h:
            await h.say("AMY for Ithaca, NY")
            await h.approve()
            await h.choose("era5-openmeteo")
            await h.reply("2018")
            assert h.form.gate == "review_plan" and h.session.facts.plans[0]["years"] == [2018]
    run(main)


def test_showing_the_request_with_nothing_proposed_keeps_the_plan(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            first, planned = plan_hashes(h), h.tools().count("weather_plan")
            await h.session.show_request()
            assert h.form.kind == "request_summary" and h.form.data["return_to"]["gate"] == "review_plan"
            assert "Approve to keep it as it is" in h.form.summary
            await h.approve()
            assert h.form.gate == "review_plan" and plan_hashes(h) == first
            assert h.tools().count("weather_plan") == planned
            await h.say("show my request")                 # the guided phrase does the same
            assert h.form.kind == "request_summary"
    run(main)


def test_change_is_refused_after_a_job_started(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            plans = [{**plan, "job_id": "j1"} for plan in h.session.facts.plans]
            h.session.facts.plans = plans
            await host.change_part(h.session, "years", h.policy.advance)
            assert [event.data.get("code") for event in h.session.events()][-1] == "JOB_STARTED"
            assert h.session.facts.plans == plans
    run(main)


def agent(tmp_path, steps):
    model = ScriptedModel(steps)
    return Harness(tmp_path, policy=ModelPolicy(model, turn_seconds=30)), model


def tool_results(model, name):
    found = {}
    for request in model.requests:
        for item in request["items"]:
            if item["type"] == "tool_result" and item["name"] == name:
                found[item["call_id"]] = json.loads(item["output"])
    return list(found.values())


def test_agent_change_years_runs_without_the_model_and_closes_its_question(tmp_path):
    steps = [call("weather_geocode", {"query": "Ithaca, NY"}), call("review_location", {"locations": ITHACA}),
             call("choose_products", {}),
             call("weather_plan", {"request": {"product": "historical", "years": [2018], "dataset_selections": ERA5}}),
             call("review_plan"), say("Done; not certified simulation-ready (simulation_ready=false).")]

    async def main():
        h, model = agent(tmp_path, steps)
        async with h:
            await to_plan_review(h)
            assert h.form.gate == "review_plan" and "call_id" in h.form.data
            calls = len(model.requests)
            await change(h, "years")
            assert len(model.requests) == calls                       # Change makes no model call
            assert h.session.state.pending_call is None
            closed = [item for item in h.session.state.turn if item["type"] == "tool_result"
                      and item["name"] == "review_plan"]
            assert json.loads(closed[-1]["output"]) == {"status": "person_changed", "part": "years"}
            await h.say("2019")                                        # answers the Change form, not the model
            assert len(model.requests) == calls
            assert h.form.gate == "review_plan" and "call_id" not in h.form.data
            assert h.session.facts.plans[0]["years"] == [2019]
            await h.approve()
            assert h.session.facts.job_ids
    run(main)


def test_agent_question_is_proposed_and_a_plan_with_it_is_refused(tmp_path):
    steps = [call("weather_geocode", {"query": "Ithaca, NY"}), call("review_location", {"locations": ITHACA}),
             call("choose_products", {}), call("ask_text", {"prompt": "Which years?", "purpose": "years"}),
             call("weather_plan", {"request": {"product": "historical", "years": [2018], "dataset_selections": ERA5}}),
             say("Please confirm 2018 first.")]

    async def main():
        h, model = agent(tmp_path, steps)
        async with h:
            await h.say("AMY for Ithaca, NY")
            await h.approve()
            await h.choose("era5-openmeteo")
            await h.reply("What's available for 2018 here?")
            replied = tool_results(model, "ask_text")[-1]
            assert replied["proposed_years"] == [2018] and "review_request" in replied["next"]
            gate = tool_results(model, "weather_plan")[-1]
            assert gate["code"] == "GATE_REQUIRED" and gate["need"] == "review_request"
            assert h.session.facts.plans == [] and h.session.facts.proposed_years == [2018]
            block = model.requests[-1]["items"][0]["text"]
            assert "Request parts (authoritative; plans use only confirmed parts):" in block
            assert "- years: proposed (confirmed none; proposed [2018]" in block
    run(main)


def test_agent_summary_approval_confirms_and_tells_the_model_to_plan(tmp_path):
    steps = [call("weather_geocode", {"query": "Ithaca, NY"}), call("review_location", {"locations": ITHACA}),
             call("choose_products", {}), call("ask_text", {"prompt": "Which years?", "purpose": "years"}),
             call("review_request"), say("Confirmed.")]

    async def main():
        h, model = agent(tmp_path, steps)
        async with h:
            await h.say("AMY for Ithaca, NY")
            await h.approve()
            await h.choose("era5-openmeteo")
            await h.reply("2018?")
            assert h.form.kind == "request_summary" and "call_id" in h.form.data
            await h.approve()
            result = tool_results(model, "review_request")[-1]
            assert result["confirmed"] and "weather_plan" in result["next"]
            assert h.session.facts.confirmed_years == [2018]
    run(main)


def test_the_instructions_and_tools_name_the_request_summary():
    assert "review_request" in ASK_TOOLS and NEED_TOOL["confirm_request"] == "review_request"
    for system in (SYSTEM, SYSTEM_WITHOUT_KNOWLEDGE):
        assert "review_request" in system and "Can I get" in system and "same turn" in system


def test_cli_reads_ok_and_change_on_the_summary_and_plan_review():
    summary = Interaction(kind="request_summary", prompt="Is this your request?", summary="Years: 2018",
                          options=[Option(id=f"change:{part}", label=f"Change {part}")
                                   for part in ("place", "preference", "years")])
    assert "'ok' to confirm" in render_form(summary)
    assert parse_reply(summary, "ok").approve
    assert parse_reply(summary, "change years").choice_ids == ["change:years"]
    assert parse_reply(summary, "Change the year.").choice_ids == ["change:years"]
    assert parse_reply(summary, "change product preference").choice_ids == ["change:preference"]
    assert parse_reply(summary, "change products") is None          # not offered before approval
    plan = Interaction(kind="plan_review", prompt="?", options=[Option(id="change:place", label="Change place")])
    assert parse_reply(plan, "change place").choice_ids == ["change:place"]
    assert parse_reply(plan, "run").approve
    assert parse_reply(plan, "change the plan please") is None
    products = Interaction(kind="product_choice", prompt="?", multi=True, options=[Option(id="a", label="A")])
    assert parse_reply(products, "ok") is None                      # nothing preselected


def test_an_answer_to_a_host_summary_in_agent_mode_returns_to_the_models_form(tmp_path):
    steps = [call("weather_geocode", {"query": "Ithaca, NY"}), call("review_location", {"locations": ITHACA}),
             call("choose_products", {}), call("ask_text", {"prompt": "Which years?", "purpose": "years"})]

    async def main():
        h, model = agent(tmp_path, steps)
        async with h:
            await h.say("AMY for Ithaca, NY")
            await h.approve()
            await h.choose("era5-openmeteo")
            asked = h.form
            assert asked.gate == "ask_text"
            await h.session.show_request()
            assert h.form.kind == "request_summary" and "call_id" not in h.form.data
            calls = len(model.requests)
            form = h.form
            await h.session.answer(Answer(interaction_id=form.id, revision=form.revision, approve=True))
            assert h.form.gate == "ask_text" and h.form.data["call_id"] == asked.data["call_id"]
            assert h.session.state.pending_call is not None and len(model.requests) == calls
    run(main)
