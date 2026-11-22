"""Data gaps in the chat (owner, 2026-11-22): a chosen source that lacks requested weather is
shown on a data-gaps form before the plan review; the person fills a group from another source,
uses the station's pressure reports or leaves it missing, and finished files report what is
still missing."""

import json

from test_web_host import OWNER, answer, finish_jobs, idle, step

from openepw.agent.cli import parse_reply, render_form
from openepw.agent.interactions import Interaction
from openepw.agent.revisions import read_fill
from openepw.agent.web import WebInput


def _to_gaps(host, text="AMY 2018 for Ithaca NY"):
    session_id = host.create(OWNER)
    idle(host, session_id)
    snapshot = step(host, session_id, WebInput(type="text", text=text))
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["form"]["kind"] == "product_choice"
    snapshot = step(host, session_id, answer(snapshot, choice_ids=["noaa-isd"]))
    return session_id, snapshot


def _rows(snapshot):
    return {row["group"]: row for row in snapshot["form"]["data"]["rows"]}


def test_noaa_gaps_are_decided_before_the_plan_review(make_host):
    host = make_host()
    session_id, snapshot = _to_gaps(host)
    form = snapshot["form"]
    assert form["kind"] == "data_gaps" and form["gate"] == "fill_gaps"
    rows = _rows(snapshot)
    assert set(rows) == {"solar", "pressure"}
    assert rows["solar"]["selected"] == "source:openmeteo:era5"         # recommended: no key
    assert rows["pressure"]["selected"] == "station_reports"           # the station's own reports
    assert {option["id"] for option in rows["solar"]["options"]} == {"source:openmeteo:era5", "leave_missing"}

    snapshot = step(host, session_id, answer(snapshot, approve=True))   # the recommended choices
    assert snapshot["form"]["kind"] == "plan_review"
    summary = snapshot["form"]["summary"]
    assert "Data gaps:" in summary and "Fill from Open-Meteo ERA5" in summary
    assert "Use the station's own pressure reports" in summary
    assert "change:gaps" in {option["id"] for option in snapshot["form"]["options"]}

    snapshot = step(host, session_id, answer(snapshot, approve=True))   # Run
    snapshot = finish_jobs(host, session_id)
    assert snapshot["form"]["gate"] == "next_steps"
    texts = [event["text"] for event in host.snapshot(session_id)["events"] if event["type"] == "assistant"]
    assert any(text.startswith("Data gaps: ") for text in texts)
    assert not any("Missing values after retrieval" in text for text in texts)   # nothing left missing


def test_leaving_solar_missing_is_reported_after_the_run_and_a_fill_offered(make_host):
    host = make_host()
    session_id, snapshot = _to_gaps(host)
    rows = _rows(snapshot)
    snapshot = step(host, session_id, answer(snapshot, approve=True, value={"choices": {
        rows["solar"]["id"]: "leave_missing"}}))
    assert snapshot["form"]["kind"] == "plan_review"
    assert "Leave missing" in snapshot["form"]["summary"]
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    snapshot = finish_jobs(host, session_id)
    events = host.snapshot(session_id)["events"]
    report = next(event for event in events if event["data"].get("code") == "DATA_GAPS_AFTER")
    assert "GHI all 8760 h, DNI all 8760 h, DHI all 8760 h" in report["text"]
    fill = next(option for option in snapshot["form"]["options"] if option["id"].startswith("fill:"))
    assert fill["label"].startswith("Fill from Open-Meteo ERA5 for solar radiation")

    snapshot = step(host, session_id, answer(snapshot, choice_ids=[fill["id"]]))   # plan again with it
    assert snapshot["form"]["kind"] == "plan_review"
    assert "Fill from Open-Meteo ERA5" in snapshot["form"]["summary"]


def test_gap_choices_typed_in_words(make_host):
    host = make_host()
    session_id, snapshot = _to_gaps(host)
    snapshot = step(host, session_id, WebInput(type="text", text="leave pressure missing"))
    assert snapshot["form"]["kind"] == "plan_review"
    summary = snapshot["form"]["summary"]
    assert "Leave missing" in summary and "Fill from Open-Meteo ERA5" in summary   # solar kept recommended
    # On the plan review, a typed change naming a group reopens nothing: it is applied.
    snapshot = step(host, session_id, WebInput(type="text", text="fill pressure from open-meteo"))
    assert snapshot["form"]["kind"] == "plan_review"
    assert "Leave missing" not in snapshot["form"]["summary"]


def test_the_plan_carries_the_fills_and_the_manifest_records_them(make_host):
    host = make_host()
    session_id, snapshot = _to_gaps(host)
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    plan_hash = snapshot["form"]["data"]["plans"][0]["plan_hash"]
    plan = host.runner.service.plan_store.get(plan_hash)
    assert sorted(fill.method for fill in plan.request.fills) == ["source", "station_reports"]
    assert {gap.status for gap in plan.gaps} == {"filled", "station_reports"}
    assert plan.tasks[0].parameters["derived"] == ["pressure"]           # the station task reads pressure
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    finish_jobs(host, session_id)
    job = host.runner.store.get(snapshot["job_ids"][0])
    path = host.runner.service.artifacts.resolve(job.bundle.manifest.id)[1]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    output = manifest["outputs"][0]
    assert {fill["group"] for fill in output["fills"]} == {"solar", "pressure"}
    assert output["missing_hours"]["ghi"] == 0 and output["missing_hours"]["pressure"] == 0
    assert output["lineage"]["ghi"]["filled"] is True


def test_typed_gap_choices_are_read():
    assert read_fill("ok") == [(None, "recommended")]
    assert read_fill("leave solar and pressure missing") == [("solar", "leave_missing"), ("pressure", "leave_missing")]
    assert read_fill("fill solar from Open-Meteo and leave pressure missing") == [
        ("solar", "source:openmeteo:era5"), ("pressure", "leave_missing")]
    assert read_fill("use the station's pressure reports") == [("pressure", "station_reports")]
    assert read_fill("take radiation from ERA5-Land") == [("solar", "source:openmeteo:era5_land")]
    assert read_fill("pressure from copernicus") == [("pressure", "source:cds:reanalysis-era5-single-levels")]
    assert read_fill("what is DNI?") is None
    assert read_fill("use ERA5 instead", need_group=True) is None          # a product change on the plan review
    assert read_fill("ok", need_group=True) is None


def test_the_cli_renders_and_reads_the_gaps_form():
    form = Interaction(kind="data_gaps", gate="fill_gaps", prompt="How should it be covered?", data={"rows": [
        {"id": "noaa|ISD|solar", "number": 1, "label": "Solar radiation (GHI, DNI, DHI)", "source": "NOAA ISD",
         "selected": "source:openmeteo:era5", "options": [
             {"id": "source:openmeteo:era5", "label": "Fill from Open-Meteo ERA5"},
             {"id": "leave_missing", "label": "Leave missing"}]}]})
    text = render_form(form)
    assert "a. Fill from Open-Meteo ERA5 [selected]" in text and "b. Leave missing" in text
    assert parse_reply(form, "ok").approve
    picked = parse_reply(form, "1b")
    assert picked is not None and picked.value == {"choices": {"noaa|ISD|solar": "leave_missing"}}
    assert parse_reply(form, "3a") is None                                  # no such gap


def test_in_agent_mode_review_plan_asks_about_the_gaps_first(make_host):
    from openepw.agent.model_port import ScriptedModel, call, say

    model = ScriptedModel([
        call("weather_geocode", {"query": "Ithaca, NY"}),
        call("review_location", {"locations": {"lat": 42.44, "lon": -76.5, "name": "Ithaca, New York"}}),
        call("choose_products", {}),
        call("weather_plan", {"request": {"product": "historical", "years": [2018], "dataset_selections": [
            {"provider": "noaa", "dataset": "ISD global-hourly"}]}}),
        call("review_plan", {}),
        say("The job finished; see QC."), say("Done."), say("Done.")])
    host = make_host(model=lambda: model)
    session_id = host.create(OWNER)
    idle(host, session_id)
    step(host, session_id, WebInput(type="mode", mode="agent"))
    snapshot = step(host, session_id, WebInput(type="text", text="AMY 2018 for Ithaca, NY"))
    assert snapshot["form"]["kind"] == "location_review"
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["form"]["kind"] == "product_choice"
    snapshot = step(host, session_id, answer(snapshot, choice_ids=["noaa-isd"]))
    form = snapshot["form"]
    assert form["kind"] == "data_gaps" and form["data"]["call_id"]      # under the model's review_plan
    call_id = form["data"]["call_id"]
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert snapshot["form"]["kind"] == "plan_review"
    assert snapshot["form"]["data"]["call_id"] == call_id                 # the same question stays open
    snapshot = step(host, session_id, answer(snapshot, approve=True))
    assert len(snapshot["job_ids"]) == 1
