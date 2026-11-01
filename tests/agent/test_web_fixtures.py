"""Snapshots of every form kind, written for the web renderer's tests (design §6.3).

`web/chat-ui/tests/fixtures/agent-forms.json` holds one real `/v2` snapshot per form kind, made by
the agent host on the offline stub providers; vitest renders each one. This test fails when the
file is stale. Regenerate it with OPENEPW_WRITE_FIXTURES=1.
"""

import json
import os
import re
from pathlib import Path

from test_web_host import OWNER, answer, idle, step

from openepw.agent.interactions import Interaction
from openepw.agent.web import WebInput

FIXTURE = Path(__file__).resolve().parents[2] / "web" / "chat-ui" / "tests" / "fixtures" / "agent-forms.json"
KINDS = ("map_input", "choice", "location_review", "product_choice", "text", "plan_review", "request_summary",
         "upload")
VOLATILE = re.compile(r"(^|_)(at|time|checked)$")


def normalise(value, ids):
    """Fixed ids and no timestamps, so the file only changes when the shape or wording does."""
    if isinstance(value, dict):
        return {key: ("<time>" if VOLATILE.search(key) and isinstance(item, str) else normalise(item, ids))
                for key, item in value.items()}
    if isinstance(value, list):
        return [normalise(item, ids) for item in value]
    if isinstance(value, str):
        for real, fixed in ids.items():
            value = value.replace(real, fixed)
    return value


def snapshots(make_host):
    host = make_host()
    found = {}

    def keep(snapshot):
        kind = snapshot["form"]["kind"]
        found.setdefault(kind, {**snapshot, "events": [], "cursor": 0})
        return snapshot

    session_id = host.create(OWNER)
    keep(idle(host, session_id))                                              # map_input
    keep(step(host, session_id, WebInput(type="text", text="Springfield")))     # choice (candidates)
    first = host.snapshot(session_id)["form"]["options"][0]["id"]
    snapshot = keep(step(host, session_id, answer(host.snapshot(session_id), choice_ids=[first])))   # review
    snapshot = keep(step(host, session_id, answer(snapshot, approve=True)))   # product_choice
    snapshot = keep(step(host, session_id, answer(snapshot, choice_ids=["era5-openmeteo"])))   # text (years)
    snapshot = keep(step(host, session_id, WebInput(type="text", text="2018")))    # plan_review
    keep(step(host, session_id, WebInput(type="request")))                    # request_summary
    # The model's upload form (agent mode only): the snapshot around it is the same.
    upload = Interaction(kind="upload", gate="ask_upload", prompt="Attach the EPW you want to compare.",
                         data={"call_id": "call_upload"})
    found["upload"] = {**found["request_summary"], "mode": "agent", "model_available": True,
                       "form": upload.model_dump(mode="json")}
    ids = {session_id: "session-1"}
    for kind, item in found.items():
        ids[item["form"]["id"]] = f"form-{kind}"
    return {kind: normalise(found[kind], ids) for kind in KINDS}


def test_the_web_fixture_has_every_form_kind_and_is_current(make_host):
    current = snapshots(make_host)
    assert sorted(current) == sorted(KINDS)
    text = json.dumps(current, indent=1, sort_keys=True) + "\n"
    if os.environ.get("OPENEPW_WRITE_FIXTURES") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.is_file(), "run with OPENEPW_WRITE_FIXTURES=1 to write the web fixture"
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == json.loads(text), (
        "web/chat-ui/tests/fixtures/agent-forms.json is stale; regenerate with OPENEPW_WRITE_FIXTURES=1")
