"""After a download (phase 5): listing files, offering downloads, retrying failed outputs and the
follow-ups that ask for them. None of them plans or submits new weather."""

import asyncio
import hashlib
import json

import pytest
from harness import Harness

from openepw.agent.cli import file_name, offered_files, save_files
from openepw.agent.model_port import ModelReply, ScriptedModel, ToolCall
from openepw.agent.outputs import read_follow_up
from openepw.agent.policy_model import ModelPolicy

BOSTON = (42.36, -71.06)


def run(tmp_path, scenario, **options):
    async def main():
        async with Harness(tmp_path, **options) as h:
            await scenario(h)
    asyncio.run(main())


async def results(h, text="Boston, Denver 2016 2017"):
    """Run a guided request to its results: four outputs (two places, two years)."""
    await h.say(text)
    await h.approve()                                    # the location review
    await h.choose("era5-openmeteo")
    await h.approve()                                    # Run
    await h.session.follow_jobs(timeout=120)
    assert h.form.gate == "next_steps", h.texts("assistant")[-3:]


def counted(h, *names):
    return {name: h.tools().count(name) for name in names}


@pytest.mark.parametrize("text,kind,years,place,everything", [
    ("What did I get?", "list", (), "", False),
    ("which one is 2016", "list", (2016,), "", False),
    ("Download the Boston 2016 file", "download", (2016,), "boston", False),
    ("download all", "download", (), "", True),
    ("What happened to 2017?", "failed", (2017,), "", False),
    ("retry the failed ones", "retry", (), "", False),
    ("try again", "retry", (), "", False),
    ("how is it going", "status", (), "", False),
])
def test_follow_ups_are_read_with_their_filters(text, kind, years, place, everything):
    asked = read_follow_up(text)
    assert asked is not None and (asked.kind, asked.years, asked.place, asked.everything) == (
        kind, years, place, everything)


@pytest.mark.parametrize("text", ["download AMY 2019 for Boston", "Boston 2019", "TMY for Denver",
                                  "AMY 2018 for Ithaca NY", "what is DNI"])
def test_requests_are_not_read_as_follow_ups(text):
    assert read_follow_up(text) is None


def test_listing_names_place_year_status_and_failure_codes(tmp_path):
    async def scenario(h):
        await results(h)
        before = counted(h, "weather_plan", "weather_submit")
        await h.say("What did I get?")
        listing = h.texts("assistant")[-1]
        assert listing.startswith("Your files:") and listing.count("\n") >= 4
        assert "Denver" in listing and "2016" in listing and "file openepw-" in listing
        assert "Boston" in listing and "failed (PROVIDER_ERROR" in listing
        assert "Failed outputs can be retried." in listing
        await h.say("which one is 2016")
        assert "2017" not in h.texts("assistant")[-1].split("\n", 1)[1]
        await h.say("What happened to 2017?")
        failed = h.texts("assistant")[-1]
        assert failed.startswith("Failed outputs") and "Boston" in failed and "Denver" not in failed
        assert counted(h, "weather_plan", "weather_submit") == before        # nothing planned or run
        assert h.form.gate == "next_steps"                                  # the form stays open

    run(tmp_path, scenario, fail_near=[BOSTON])


def test_download_offers_only_files_that_exist(tmp_path):
    async def scenario(h):
        await results(h)
        await h.say("Download the Denver 2016 file")
        offer = [event for event in h.session.events() if event.type == "download"][-1]
        assert [item["label"].split(" (")[0] for item in offer.data["files"]] == ["Denver, Colorado, United States"]
        item = offer.data["files"][0]
        assert len(item["artifact_id"]) == 32 and item["filename"].endswith(".epw") and len(item["sha256"]) == 64
        await h.say("download the Boston 2016 file")                  # it failed: nothing to offer
        assert h.texts("assistant")[-1] == "No finished file matches that."
        await h.say("download all")
        assert len([event for event in h.session.events() if event.type == "download"][-1].data["files"]) == 2
        assert counted(h, "weather_plan", "weather_submit") == {"weather_plan": 1, "weather_submit": 1}

    run(tmp_path, scenario, fail_near=[BOSTON])


def test_retry_runs_only_after_the_person_approves_its_scope(tmp_path):
    async def scenario(h):
        await results(h)
        assert "retry" in [option.id for option in h.form.options]
        await h.choose("retry")
        form = h.form
        assert form.gate == "review_retry" and form.kind == "choice"
        assert "Boston" in form.summary and "Denver" not in form.summary and "PROVIDER_ERROR" in form.summary
        assert [option.label for option in form.options] == ["Retry 2 failed output(s)", "Not now"]
        assert "job_retry_failed" not in h.tools()
        await h.choose("cancel")
        assert h.form.gate == "next_steps" and "job_retry_failed" not in h.tools()
        h.service.providers["openmeteo"].fail_near.clear()                 # the outage is over
        await h.say("retry")
        assert h.form.gate == "review_retry"
        await h.choose("retry")
        assert h.tools().count("job_retry_failed") == 1 and h.form is None
        assert not h.session.approvals.pending                            # the approval was used once
        retry_job = h.session.facts.job_ids[-1]
        assert h.session.facts.retry_of[retry_job] == h.session.facts.finished_job_ids[0]
        await h.session.follow_jobs(timeout=120)
        assert h.form.gate == "next_steps" and "retry" not in [option.id for option in h.form.options]
        await h.say("What did I get?")
        listing = h.texts("assistant")[-1]
        assert "failed" not in listing and listing.count(". ") >= 4     # the retry's files replace the failures
        assert "Failed outputs can be retried." not in listing
        await h.say("retry")
        assert h.texts("assistant")[-1] == "There are no failed outputs to retry."
        assert h.tools().count("weather_submit") == 1

    run(tmp_path, scenario, fail_near=[BOSTON])


def test_retries_stop_after_the_limit(tmp_path):
    async def scenario(h):
        await results(h)
        for _ in range(3):                                                 # the outage goes on
            await h.say("retry")
            await h.choose("retry")
            await h.session.follow_jobs(timeout=120)
        await h.say("retry")
        assert "already retried 3 times" in h.texts("assistant")[-1]
        assert h.tools().count("job_retry_failed") == 3

    run(tmp_path, scenario, fail_near=[BOSTON])


def test_a_follow_up_in_a_new_request_keeps_the_plan_review(tmp_path):
    async def scenario(h):
        await results(h)
        await h.choose("new")
        await h.say("Boston 2019")
        await h.approve()
        await h.choose("era5-openmeteo")
        plan = h.form
        assert plan.gate == "review_plan"
        await h.say("download the Denver 2016 file")
        assert h.form.id == plan.id and h.session.facts.years == [2019]     # the request is untouched
        assert [event for event in h.session.events() if event.type == "download"]
        await h.say("what did I get")
        assert h.form.id == plan.id and h.session.facts.plans

    run(tmp_path, scenario, fail_near=[BOSTON])


def test_export_is_offered_as_a_download(tmp_path):
    async def scenario(h):
        await results(h, "Denver 2016")
        await h.choose("export")
        offer = [event for event in h.session.events() if event.type == "download"][-1]
        assert offer.data["files"][0]["label"] == "Compact ZIP of the outputs"
        assert offer.data["files"][0]["filename"].endswith(".zip")

    run(tmp_path, scenario)


def test_cli_download_checks_the_checksum_and_never_overwrites(tmp_path):
    async def scenario(h):
        await results(h, "Denver 2016")
        await h.say("download all")
        files = offered_files(h.session.events())
        written = []
        folder = tmp_path / "saved"
        assert await save_files(h.port, files, folder, written.append) == 1
        target = folder / file_name(files[0])
        body = target.read_bytes()
        assert hashlib.sha256(body).hexdigest() == files[0]["sha256"] and written == [f"Saved {target}"]
        # A second save keeps the first file; a wrong checksum writes nothing.
        assert await save_files(h.port, files, folder, written.append) == 0
        assert "not overwritten" in written[-1] and target.read_bytes() == body
        bad = [{**files[0], "sha256": "0" * 64}]
        assert await save_files(h.port, bad, tmp_path / "other", written.append) == 0
        assert "CHECKSUM_MISMATCH" in written[-1] and not list((tmp_path / "other").iterdir())
        # Paths never reach the conversation.
        assert str(folder) not in json.dumps([event.model_dump() for event in h.session.events()])

    run(tmp_path, scenario)


def test_unsafe_file_names_fall_back_to_the_artifact_id():
    assert file_name({"artifact_id": "a" * 32, "filename": "../../evil.epw"}) == "evil.epw"
    assert file_name({"artifact_id": "a" * 32, "filename": "..\\x;rm.epw"}) == f"openepw-{'a' * 12}.epw"
    assert file_name({"artifact_id": "b" * 32, "filename": None}) == f"openepw-{'b' * 12}.epw"


def scripted(*steps):
    return ScriptedModel([step if isinstance(step, ModelReply) else ModelReply(tool_calls=[
        ToolCall(f"c{index}", step[0], json.dumps(step[1]))]) for index, step in enumerate(steps)])


def test_agent_lists_offers_and_retries_with_host_tools(tmp_path):
    model = scripted(
        ("list_outputs", {"years": [2016]}),
        ModelReply(text="Denver 2016 is listed."),
        ("offer_download", {"numbers": [1, 2, 3, 4]}),
        ModelReply(text="Saved links above."),
        ("offer_download", {"numbers": [99]}),
        ModelReply(text="I'll list them first."),
        ("review_retry", {}),
    )

    async def scenario(h):
        h.session.state.mode = "guided"                                    # the request itself by forms
        await results(h)
        h.session.state.mode = "agent"
        await h.say("Which file is 2016?")
        listing = h.texts("assistant")[-2]
        assert listing.startswith("Your files:") and "2017" not in listing
        result = json.loads(next(item["output"] for item in h.session.state.turn
                                 if item.get("name") == "list_outputs"))
        assert {row["year"] for row in result["tool_data"]["outputs"]} == {2016}
        await h.say("download it")
        assert [event for event in h.session.events() if event.type == "download"]
        await h.say("and number 99")
        refused = json.loads(next(item["output"] for item in h.session.state.turn
                                  if item.get("name") == "offer_download"))
        assert refused["code"] == "UNKNOWN_OUTPUT"
        await h.say("retry the failed ones")
        assert h.form.gate == "review_retry" and "call_id" in h.form.data
        await h.choose("retry")
        assert h.tools().count("job_retry_failed") == 1 and h.form is None
        assert h.tools().count("weather_plan") == 1 and h.tools().count("weather_submit") == 1

    run(tmp_path, scenario, fail_near=[BOSTON], policy=ModelPolicy(model))


def test_agent_sees_the_values_of_a_view(tmp_path):
    model = scripted(
        ("list_outputs", {}),
        ModelReply(text="ok"),
    )

    async def scenario(h):
        h.session.state.mode = "guided"
        await results(h, "Denver 2016 2017")
        h.session.state.mode = "agent"
        ids = h.session.facts.artifact_ids
        model.steps += [ModelReply(tool_calls=[ToolCall("v", "weather_visualize", json.dumps({"request": {
            "artifact_ids": ids, "family": "month_of_year_profile", "variable": "dry_bulb"}}))]),
            ModelReply(text="January averages 10.0 °C over 2016 and 2017.")]
        await h.say("files?")
        await h.say("average January temperature over those years?")
        output = json.loads(next(item["output"] for item in h.session.state.turn
                                 if item.get("name") == "weather_visualize"))
        values = output["tool_data"]["values"]
        assert output["tool_data"]["family"] == "month_of_year_profile" and output["tool_data"]["unit"]
        assert values[0]["period"] == "month-01" and values[0]["value"] == 10.0
        assert values[0]["years"] == [2016, 2017] and values[0]["quality"] == "complete"
        assert [event for event in h.session.events() if event.type == "view"]

    run(tmp_path, scenario, policy=ModelPolicy(model))
