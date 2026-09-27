"""Going back one step, product option details and the markdown plan summary."""

import pytest
from test_chat_sessions import Parser, Service

from openepw.chat.coordinator import ChatActionError, ChatCoordinator, plan_summary_markdown


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


def test_product_choices_name_the_products_behind_each_type(tmp_path):
    class NoProduct(Parser):
        def parse_many(self, text):
            from openepw.harness.agent import AgentIntent
            return [AgentIntent(kind="weather", lat=42.0, lon=-71.0)]

    chat = ChatCoordinator(Service(), parser=NoProduct(), path=tmp_path / "chat.sqlite")
    state = chat.create()
    card = chat.turn(state["id"], "42, -71", 0, "one")["active_card"]
    assert card["prompt"] == "Which weather product?"
    details = {option["id"]: option["detail"] for option in card["options"]}
    assert "ERA5" in details["historical"] and "NOAA ISD" in details["historical"]
    assert "NSRDB" in details["tmy"] and "PVGIS" in details["tmy"]
    assert "OneBuilding" in details["tmyx"] and "OneBuilding" in details["published"]


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
