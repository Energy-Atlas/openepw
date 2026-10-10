"""Moderation of messages, form answers, uploads and (optionally) model replies."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest
from harness import Harness

from openepw.agent.model_port import ScriptedModel, say
from openepw.agent.moderation import (
    FLAG_MARKER,
    ModerationUnavailable,
    OpenAIModeration,
    StubModeration,
)
from openepw.agent.policy_config import load_policy
from openepw.agent.policy_model import ModelPolicy
from openepw.epw.writer import epw_bytes

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic  # noqa: E402

KEY = "sk-test-moderation-not-real"


def openai(handler):
    return OpenAIModeration(KEY, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_the_openai_port_sends_all_texts_and_reports_categories():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"results": [
            {"flagged": False, "categories": {"violence": False}},
            {"flagged": True, "categories": {"harassment": True, "violence": False}}]})

    result = asyncio.run(openai(handler).check(["hello", "bad"]))
    assert result.flagged and result.categories == ("harassment",)
    assert seen["body"] == {"model": "omni-moderation-latest", "input": ["hello", "bad"]}
    assert seen["auth"] == "Bearer " + KEY


@pytest.mark.parametrize("response", [httpx.Response(500, text=f"error {KEY}"),
                                      httpx.Response(200, content=b"not json")])
def test_openai_failures_are_unavailable_without_the_body(response):
    with pytest.raises(ModerationUnavailable) as error:
        asyncio.run(openai(lambda request: response).check(["x"]))
    assert KEY not in str(error.value)


def test_no_key_is_unavailable():
    with pytest.raises(ModerationUnavailable):
        asyncio.run(OpenAIModeration("").check(["x"]))


def run(tmp_path, scenario, *, security="hosted", moderation=None, policy=None):
    async def main():
        async with Harness(tmp_path, policy=policy) as h:
            h.session.security = load_policy(security) if isinstance(security, str) else security
            h.session.moderation = moderation if moderation is not None else StubModeration()
            await scenario(h)
    asyncio.run(main())


def codes(h):
    return [event.data.get("code") for event in h.session.events()]


def test_a_flagged_message_is_withheld_refused_and_struck(tmp_path):
    async def scenario(h):
        await h.say(f"AMY 2018 for Ithaca NY {FLAG_MARKER}")
        users = [event.text for event in h.session.events() if event.type == "user"]
        assert users[-1] == "[message withheld by moderation]" and FLAG_MARKER not in json.dumps(
            [event.model_dump(mode="json") for event in h.session.events()])
        assert "MODERATION_FLAG" in codes(h) and h.session.state.strikes == 1
        assert h.tools() == [] and h.form.gate == "where"            # guided mode never saw it

    run(tmp_path, scenario)


def test_unavailable_moderation_blocks_or_allows_by_profile(tmp_path):
    async def blocked(h):
        await h.say("AMY 2018 for Ithaca NY")
        assert h.session.events()[-1].data["code"] == "MODERATION_UNAVAILABLE" and h.tools() == []

    run(tmp_path, blocked, moderation=StubModeration(unavailable=True))

    async def allowed(h):
        await h.say("AMY 2018 for Ithaca NY")
        await h.say("2019 instead")
        assert codes(h).count("MODERATION_UNAVAILABLE") == 1                 # one notice per session
        assert h.form.gate == "review_location"

    run(tmp_path / "local", allowed, security="local", moderation=StubModeration(unavailable=True))


def test_form_answers_and_uploads_are_checked(tmp_path):
    async def scenario(h):
        await h.say("Springfield 2018")
        await h.reply(f"the first one {FLAG_MARKER}")
        assert h.session.state.strikes == 1 and h.form.gate == "choose_location"
        epw = epw_bytes(synthetic(2023, 8760)).replace(b"LOCATION,", f"LOCATION,{FLAG_MARKER} ".encode(), 1)
        await h.session.upload_epw(epw, "site.epw")
        assert h.session.state.strikes == 2 and "epw_upload" not in h.tools()
        await h.session.upload_epw(epw_bytes(synthetic(2023, 8760)), f"{FLAG_MARKER}.epw")
        assert "epw_upload" not in h.tools()                                  # the filename too

    run(tmp_path, scenario, security="local")


def test_disabled_or_unchecked_kinds_are_not_sent(tmp_path):
    path = tmp_path / "mod.local.yaml"
    path.write_text("extends: hosted\nmoderation:\n  check: [upload_text]\n", encoding="utf-8")
    stub = StubModeration()

    async def scenario(h):
        await h.say(f"AMY 2018 for Ithaca NY {FLAG_MARKER}")
        assert stub.calls == [] and "MODERATION_FLAG" not in codes(h)

    run(tmp_path, scenario, security=load_policy(file=path), moderation=stub)


def test_model_replies_are_checked_only_when_configured(tmp_path):
    path = tmp_path / "out.local.yaml"
    path.write_text("extends: hosted\nmoderation:\n  check: [input, model_output]\n", encoding="utf-8")

    async def scenario(h):
        await h.say("AMY 2018 for Ithaca NY")
        replies = [event for event in h.session.events() if event.type == "assistant"]
        assert replies[-1].text == "I can't show that reply." and h.session.state.strikes == 0
        assert FLAG_MARKER not in json.dumps([event.model_dump(mode="json") for event in h.session.events()])

    model = ScriptedModel([say(f"Here you go {FLAG_MARKER}")])
    run(tmp_path, scenario, security=load_policy(file=path), policy=ModelPolicy(model))


def test_chat_will_not_start_hosted_without_a_moderation_key(tmp_path, monkeypatch):
    from fakes import scenario_service

    from openepw.agent.cli import chat_moderation, main_chat

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    port, problem = chat_moderation(load_policy("hosted"), env_file=tmp_path / "none.env")
    assert port is None and "OPENAI_API_KEY" in problem and "on_error" in problem
    port, problem = chat_moderation(load_policy("local"), env_file=tmp_path / "none.env")
    assert problem is None
    output = []
    code = asyncio.run(main_chat(scenario_service(tmp_path), read=lambda prompt: "/quit", write=output.append,
                                 security=load_policy("local"), moderation=port))
    assert code == 0


def test_upload_moderation_reads_the_header_as_the_epw_reader_does():
    from openepw.agent.moderation import FLAG_MARKER, epw_text_fields

    rest = ",NY,USA,src,725155,42.4,-76.5,-5,300\n"
    bom = ("﻿LOCATION,Ithaca " + FLAG_MARKER + rest).encode("utf-8")
    assert any(FLAG_MARKER in field for field in epw_text_fields(bom))
    quoted = ('LOCATION,"a,b,c,d,' + FLAG_MARKER + '"' + rest).encode("utf-8")
    assert "a,b,c,d," + FLAG_MARKER in epw_text_fields(quoted)
    accented = ("LOCATION,Zürich" + rest + "COMMENTS 1,Données horaires\n").encode("utf-8")
    fields = epw_text_fields(accented)
    assert "Zürich" in fields and "Données horaires" in fields and "42.4" not in fields


# A plain threat that OpenAI's moderation endpoint flags (violence or harassment); used only by
# the opt-in live test below.
LIVE_THREAT = "I am going to kill you and everyone you love."


@pytest.mark.live
def test_the_real_moderation_endpoint_flags_and_the_session_withholds(tmp_path):
    """OPENEPW_RUN_LIVE=1 and an OpenAI key: the real endpoint passes a weather request, flags a
    threat, and a hosted session withholds the flagged message and records a strike."""
    from openepw.agent.model_port import load_openai_key

    key = load_openai_key(".env")
    if not key:
        pytest.skip("OPENAI_API_KEY is not set in the environment or .env")
    hosted = load_policy("hosted")
    port = OpenAIModeration(key, model=hosted.moderation.model)
    assert not asyncio.run(port.check(["AMY 2018 for Ithaca, NY"])).flagged
    flagged = asyncio.run(OpenAIModeration(key, model=hosted.moderation.model).check([LIVE_THREAT]))
    assert flagged.flagged and flagged.categories

    async def scenario(h):
        await h.say("AMY 2018 for Ithaca NY")
        assert "MODERATION_FLAG" not in codes(h)
        await h.say(LIVE_THREAT)
        users = [event.text for event in h.session.events() if event.type == "user"]
        assert users[-1] == "[message withheld by moderation]" and "MODERATION_FLAG" in codes(h)
        assert h.session.state.strikes == 1
        assert LIVE_THREAT not in json.dumps([event.model_dump(mode="json") for event in h.session.events()])

    run(tmp_path, scenario, moderation=OpenAIModeration(key, model=hosted.moderation.model))
