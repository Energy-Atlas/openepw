"""Strikes count over the session; the profile decides what the limit does."""

import asyncio

from harness import Harness

from openepw.agent.policy_config import load_policy


def policy(tmp_path, text):
    path = tmp_path / "override.local.yaml"
    path.write_text(text, encoding="utf-8")
    return load_policy(file=path)


def strike_texts(h):
    return [event.text for event in h.session.events() if event.data.get("code") in
            ("STRIKE_WARNING", "SESSION_ENDED", "STRIKE_LIMIT")]


def run_with(tmp_path, security, scenario):
    async def main():
        async with Harness(tmp_path) as h:
            h.session.security = security
            await scenario(h)
    asyncio.run(main())


def test_hosted_warns_at_two_and_ends_the_session_at_three(tmp_path):
    async def scenario(h):
        s = h.session
        assert await s.strike("out_of_scope", "That is outside what I can help with.")
        assert s.events()[-1].text.endswith("(strike 1 of 3)")
        await s.strike("moderation", "That message can't be processed.")
        assert "One more" in strike_texts(h)[-1] and "ends this session" in strike_texts(h)[-1]
        await s.strike("offtopic_clamp", "Off topic.")
        assert s.state.ended and s.form is None and "has ended" in strike_texts(h)[-1]
        await h.say("AMY 2018 for Ithaca NY")
        assert s.events()[-1].data["code"] == "SESSION_ENDED" and "weather_geocode" not in h.tools()
        await s.back()
        await s.new_request()
        assert [event.data.get("code") for event in s.events()[-2:]] == ["SESSION_ENDED", "SESSION_ENDED"]

    run_with(tmp_path, load_policy("hosted"), scenario)


def test_local_only_warns(tmp_path):
    async def scenario(h):
        for _ in range(4):
            await h.session.strike("out_of_scope", "Out of scope.")
        assert not h.session.state.ended and h.session.state.strikes == 4
        assert any("limit" in text for text in strike_texts(h))
        await h.say("AMY 2018 for Ithaca NY")
        assert h.form.gate == "review_location"

    run_with(tmp_path, load_policy("local"), scenario)


def test_the_guided_action_switches_mode(tmp_path):
    async def scenario(h):
        for _ in range(3):
            await h.session.strike("out_of_scope", "Out of scope.")
        assert h.session.state.mode == "guided" and not h.session.state.ended

    run_with(tmp_path, policy(tmp_path, "extends: hosted\nstrikes:\n  action: guided\n"), scenario)


def test_sources_not_in_the_profile_do_not_count(tmp_path):
    async def scenario(h):
        assert not await h.session.strike("host_tool_attempt", "Refused.")
        assert h.session.state.strikes == 0

    run_with(tmp_path, policy(tmp_path, "extends: hosted\nstrikes:\n  sources: [moderation]\n"), scenario)


def test_consecutive_counting_resets_after_a_normal_turn(tmp_path):
    async def scenario(h):
        await h.session.strike("out_of_scope", "Out of scope.")
        await h.say("AMY 2018 for Ithaca NY")                 # a normal turn
        assert h.session.state.strikes == 0

    run_with(tmp_path, policy(tmp_path, "extends: hosted\nstrikes:\n  counting: consecutive\n"), scenario)


def test_session_counting_survives_normal_turns_and_back(tmp_path):
    async def scenario(h):
        await h.say("AMY 2018 for Ithaca NY")
        await h.session.strike("out_of_scope", "Out of scope.")
        await h.approve()
        await h.session.back()
        assert h.session.state.strikes == 1

    run_with(tmp_path, load_policy("hosted"), scenario)


def test_the_count_can_be_hidden(tmp_path):
    async def scenario(h):
        await h.session.strike("out_of_scope", "Out of scope.")
        assert h.session.events()[-1].text == "Out of scope."

    run_with(tmp_path, policy(tmp_path, "extends: hosted\nstrikes:\n  show_count: false\n"), scenario)


def test_an_ended_session_reopens_only_when_the_profile_allows(tmp_path):
    async def end(h):
        for _ in range(3):
            await h.session.strike("out_of_scope", "Out of scope.")
        return h.session.id

    async def first():
        async with Harness(tmp_path) as h:
            h.session.security = load_policy("hosted")
            return await end(h)

    session_id = asyncio.run(first())

    async def resume(security):
        async with Harness(tmp_path, session_id=session_id) as h:
            h.session.security = security
            reopened = await h.session.reopen()
            return reopened, h.session.state.ended, h.session.state.strikes

    assert asyncio.run(resume(load_policy("hosted")))[0] is False
    assert asyncio.run(resume(load_policy("local"))) == (True, None, 0)


def test_the_cli_closes_an_ended_session_and_refuses_to_resume_it(tmp_path):
    from fakes import scenario_service

    from openepw.agent.cli import main_chat
    from openepw.agent.model_port import ScriptedModel, call
    from openepw.agent.moderation import StubModeration

    model = ScriptedModel([call("out_of_scope", {"category": "unrelated"}) for _ in range(3)])
    lines = iter(["solve dy/dx = 3y", "write a poem", "tell me a joke", "AMY 2018 for Ithaca", "/quit"])
    output = []
    asyncio.run(main_chat(scenario_service(tmp_path), read=lambda prompt: next(lines), write=output.append,
                          model=model, security=load_policy("hosted"), moderation=StubModeration()))
    text = "\n".join(output)
    assert "strike 3 of 3" in text and "has ended" in text and output[-1].endswith("openepw chat")
    session_id = output[-1].split()[1]
    output = []
    code = asyncio.run(main_chat(scenario_service(tmp_path), session_id=session_id, read=lambda prompt: "/quit",
                                 write=output.append, security=load_policy("hosted"), reopen=True))
    assert code == 2 and "does not allow reopening" in output[-1]
    output = []
    code = asyncio.run(main_chat(scenario_service(tmp_path), session_id=session_id, read=lambda prompt: "/quit",
                                 write=output.append, security=load_policy("local"), reopen=True))
    assert code == 0 and any("reopened" in line for line in output)
