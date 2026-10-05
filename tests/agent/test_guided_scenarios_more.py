"""S5, S9, S15, S17, S18, S21 and one-shot approvals."""

import asyncio
import sys
from pathlib import Path

import pytest
from harness import Harness

from openepw.agent.interactions import Answer
from openepw.agent.mcp_port import ToolFailure
from openepw.epw.writer import epw_bytes

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic  # noqa: E402


async def to_plan_review(h):
    await h.say("AMY 2018 for Ithaca NY")
    await h.approve()
    await h.choose("era5-openmeteo")
    assert h.form.gate == "review_plan"


def test_s5_a_descriptive_set_asks_before_listing(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("all cities in Texas")
            assert h.form.gate == "place_set"
            for _ in range(4):
                if h.form.gate != "place_set":
                    break
                await h.choose(h.form.options[0].id)
            assert h.form.gate == "review_location" and h.form.data["point_count"] >= 1
            assert h.tools().index("weather_places_interpret") < h.tools().index("weather_place_set")
    asyncio.run(main())


def test_s9_changing_the_year_after_review_needs_a_new_plan(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            first = h.session.facts.plans[0]["plan_hash"]
            await h.say("2019 instead")
            assert h.form.gate == "review_plan" and h.session.facts.years == [2019]
            assert h.session.facts.plans[0]["plan_hash"] != first
            assert h.approvals.pending == frozenset()
    asyncio.run(main())


def test_s15_an_uploaded_epw_can_be_charted(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.session.upload_epw(epw_bytes(synthetic(2023, 8760)), "site.epw")
            assert h.form.gate == "next_steps" and h.session.facts.artifact_ids
            await h.choose("view:monthly_series")
            views = [event for event in h.session.events() if event.type == "view"]
            assert views and views[-1].data["view_id"]
            assert h.form.gate == "next_steps"
    asyncio.run(main())


def test_s17_a_stale_answer_is_refused(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("Springfield 2018")
            form = h.form
            await h.session.answer(Answer(interaction_id=form.id, revision=form.revision - 1,
                                          choice_ids=[form.options[0].id]))
            assert h.form == form and h.session.events()[-1].data["code"] == "STALE_FORM"
    asyncio.run(main())


def test_s18_a_restarted_session_keeps_its_open_form(tmp_path):
    async def first():
        async with Harness(tmp_path) as h:
            await h.say("AMY 2018 for Ithaca NY")
            await h.approve()
            return h.session.id, h.form

    async def second(session_id):
        async with Harness(tmp_path, session_id=session_id) as h:
            return h.form

    session_id, form = asyncio.run(first())
    assert asyncio.run(second(session_id)) == form


def test_s21_back_returns_to_the_location_review(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("AMY 2018 for Ithaca NY")
            await h.approve()
            assert h.form.gate == "choose_products"
            await h.session.back()
            assert h.form.gate == "review_location" and h.session.facts.approved_key is None
            await h.session.back()
            assert h.form.gate == "where"
            await h.session.back()
            assert h.session.events()[-1].data["code"] == "NOTHING_TO_UNDO"
    asyncio.run(main())


def test_an_approval_answers_exactly_one_submission(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            plan_hash = h.session.facts.plans[0]["plan_hash"]
            await h.approve()
            assert h.session.facts.job_ids
            with pytest.raises(ToolFailure) as refused:
                await h.port.call("weather_submit", plan_hash=plan_hash)
            assert refused.value.code == "APPROVAL_DECLINED"
    asyncio.run(main())


def test_an_unknown_choice_is_refused(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("Springfield 2018")
            form = h.form
            await h.choose("nope")
            assert h.form == form and h.session.events()[-1].data["code"] == "UNKNOWN_CHOICE"
    asyncio.run(main())


def test_a_failed_submission_leaves_no_approval_pending(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            real = h.port.call

            async def refuse(name, **arguments):
                if name == "weather_submit":
                    raise ToolFailure("NO_EXECUTABLE_OUTPUTS", "nothing to run")
                return await real(name, **arguments)

            h.port.call = refuse
            await h.approve()
            assert h.session.events()[-1].data["code"] == "NO_EXECUTABLE_OUTPUTS"
            assert h.approvals.pending == frozenset() and not h.session.facts.job_ids
            assert h.form.gate == "review_plan"
    asyncio.run(main())
