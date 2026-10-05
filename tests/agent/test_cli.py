import asyncio

from fakes import scenario_service

from openepw.agent.cli import main_chat, parse_reply, render_event, render_form
from openepw.agent.interactions import Event, Interaction, Option


def test_every_form_kind_renders_as_text():
    choice = Interaction(kind="choice", gate="choose_location", prompt="Which location do you mean?",
                         options=[Option(id="1", label="Springfield, Illinois", detail="39.8000, -89.6400")])
    assert "1. Springfield, Illinois" in render_form(choice)
    products = Interaction(kind="product_choice", prompt="Which weather products?", multi=True,
                           options=[Option(id="era5-openmeteo", label="ERA5")])
    assert "comma" in render_form(products)
    review = Interaction(kind="location_review", prompt="Is this the right location?", summary="1. Ithaca")
    assert "1. Ithaca" in render_form(review) and "'a' to approve" in render_form(review)
    plan = Interaction(kind="plan_review", prompt="Review the plan", summary="Actual year: plan_hash x")
    assert "'run'" in render_form(plan)
    where = Interaction(kind="map_input", prompt="Where do you need weather?", data={"hint": "e.g. Ithaca"})
    assert "e.g. Ithaca" in render_form(where)
    years = Interaction(kind="text", prompt="Which actual year or years?", data={"hint": "e.g. 2018"})
    assert "e.g. 2018" in render_form(years)
    upload = Interaction(kind="upload", prompt="Attach an EPW")
    assert "/upload" in render_form(upload)


def test_replies_map_to_answers():
    choice = Interaction(kind="product_choice", prompt="?", multi=True,
                         options=[Option(id="a", label="A"), Option(id="b", label="B")])
    assert parse_reply(choice, "1, 2").choice_ids == ["a", "b"]
    assert parse_reply(choice, "7") is None and parse_reply(choice, "ERA5 please") is None
    single = Interaction(kind="choice", prompt="?", options=[Option(id="a", label="A"), Option(id="b", label="B")])
    assert parse_reply(single, "1, 2") is None
    review = Interaction(kind="location_review", prompt="?")
    assert parse_reply(review, "a").approve and parse_reply(review, "remove 2") is None
    plan = Interaction(kind="plan_review", prompt="?")
    assert parse_reply(plan, "run").approve


def test_events_render_without_echoing_the_person_or_tool_calls():
    assert render_event(Event(seq=1, type="user", text="hi")) is None
    assert render_event(Event(seq=2, type="tool", text="weather_geocode", data={"phase": "call"})) is None
    assert render_event(Event(seq=3, type="tool", text="1 candidate", data={"phase": "result"})) == "  · 1 candidate"
    assert render_event(Event(seq=4, type="error", text="STALE_FORM: x")).startswith("✗")


def test_a_cli_conversation_runs_a_plan_and_reports_qc(tmp_path):
    lines = iter(["AMY 2018 for Ithaca NY", "a", "1", "run", "/quit"])
    output = []
    code = asyncio.run(main_chat(scenario_service(tmp_path), read=lambda prompt: next(lines),
                                 write=output.append, poll_seconds=0.05))
    text = "\n".join(output)
    assert code == 0
    assert "Is this the right location?" in text and "Which weather products?" in text
    assert "simulation_ready=false" in text and "What next?" in text


def test_the_console_survives_a_narrow_encoding_and_hides_request_logs():
    import io
    import logging

    from openepw.agent.cli import prepare_console

    levels = {name: logging.getLogger(name).level for name in ("mcp", "httpx")}
    try:
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        prepare_console(stream)
        stream.write("✗ STALE_FORM · x")
        stream.flush()
        assert stream.buffer.getvalue().startswith(b"? STALE_FORM")
        assert all(logging.getLogger(name).level == logging.WARNING for name in levels)
    finally:
        for name, level in levels.items():
            logging.getLogger(name).setLevel(level)


def test_an_unknown_session_is_reported_without_a_traceback(tmp_path):
    output = []
    code = asyncio.run(main_chat(scenario_service(tmp_path), session_id="missing",
                                 read=lambda prompt: "/quit", write=output.append))
    assert code == 2 and "SESSION_NOT_FOUND" in output[-1]


def test_ctrl_c_at_the_prompt_saves_and_ends_the_chat(tmp_path):
    output = []

    def interrupt(prompt):
        raise KeyboardInterrupt

    code = asyncio.run(main_chat(scenario_service(tmp_path), read=interrupt, write=output.append))
    assert code == 0 and "saved. Resume with" in output[-1]


def test_uploads_are_checked_before_reading(tmp_path):
    big = tmp_path / "big.epw"
    big.write_bytes(b"x" * 5_000_001)
    lines = iter([f"/upload {tmp_path / 'missing.epw'}", f"/upload {big}", "/quit"])
    output = []
    asyncio.run(main_chat(scenario_service(tmp_path), read=lambda prompt: next(lines), write=output.append))
    assert "✗ No such file." in output and any("RESOURCE_LIMIT" in line for line in output)


def test_the_command_returns_130_when_interrupted(tmp_path, monkeypatch):
    import openepw.agent.cli as agent_cli
    from openepw.cli.main import main

    async def interrupted(service, **options):
        raise KeyboardInterrupt

    monkeypatch.setattr(agent_cli, "main_chat", interrupted)
    monkeypatch.setattr(agent_cli, "prepare_console", lambda: None)
    assert main(["--data-root", str(tmp_path), "chat"]) == 130
