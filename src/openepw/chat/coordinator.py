"""Small durable coordinator. Weather facts remain separate from transcript text."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..availability import WeatherAvailabilityQuery
from ..harness.agent import safe_prompt
from ..models import Location, OpenEPWError, WeatherRequest
from ..places.models import PlacePreview, PlaceSetQuery
from ..places.parse import apply_edit, classify_places, describe_place_set
from ..visualization.models import VisualizationRequest


class StaleSession(Exception):
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        super().__init__("Session changed; review the current question")


class ChatActionError(ValueError):
    """Safe, controlled feedback for a user action in the local chat API."""


class SimpleIntent:
    def __init__(self, **values):
        self.__dict__.update(values)


class OfflineParser:
    """Grounded fallback when no optional model credential/runtime is configured."""

    def parse_many(self, text: str) -> list[SimpleIntent]:
        year_tokens = []
        for match in re.finditer(r"\b(?:18|19|20|21)\d{2}\b", text):
            if not re.match(r"\s+buildings?\b", text[match.end():], re.I):
                year_tokens.append(int(match.group()))
        years = sorted(set(year_tokens))
        if len(years) == 2 and 0 < years[1] - years[0] <= 30 and re.search(
            rf"\b{years[0]}\s*(?:-|–|—|to|through)\s*{years[1]}\b", text, re.I
        ):
            years = list(range(years[0], years[1] + 1))
        product = None
        if re.search(r"\b(?:historical|amy|actual.year)\b", text, re.I) or years:
            product = "historical"
        for token in ("tmyx", "tmy", "published"):
            if re.search(rf"\b{token}\b", text, re.I):
                product = token
                break
        coordinates = re.search(r"(?<!\d)(-?\d{1,2}(?:\.\d+)?)\s*,\s*"
                                r"(-?\d{1,3}(?:\.\d+)?)(?!\d)", text)
        place = None
        match = re.search(r"\b(?:in|for|at|near)\s+([A-Za-z][A-Za-z ]{2,35})(?:,\s*([A-Za-z]{2}))?", text, re.I)
        if match:
            place = match.group(1).strip() + (", " + match.group(2) if match.group(2) else "")
            place = re.split(r"\b(?:for|from|during|years?|with|amy|historical)\b", place,
                             maxsplit=1, flags=re.I)[0].strip()
        if not place and re.fullmatch(r"[A-Za-z][A-Za-z ]+[,]?\s*[A-Za-z]{2}", text.strip()):
            place = text.strip()
        if not any((product, years, coordinates, place)):
            return []
        return [SimpleIntent(kind="weather", place=place, product=product, years=years,
                             lat=float(coordinates.group(1)) if coordinates else None,
                             lon=float(coordinates.group(2)) if coordinates else None,
                             provider=None, product_id=None)]


# Years, product words and filler removed so "Boston; Denver 2018 historical" routes as a list.
_PLACE_NOISE = re.compile(
    r"\b(?:(?:18|19|20|21)\d{2}(?:\s*(?:-|–|—|to|through)\s*(?:18|19|20|21)\d{2})?"
    r"|historical|amy|actual[- ]year|tmyx|tmy|published|epw|weather|data|files?|please"
    r"|get|give me|i need|for|in|at|near)\b", re.I)
PREVIEW_LINES = 25


def place_text(text: str) -> str:
    """The place part of a message; newlines are kept because they separate list items."""
    stripped = re.sub(r"[ \t]+", " ", _PLACE_NOISE.sub(" ", text))
    return "\n".join(line.strip(" ,.;:!?") for line in stripped.splitlines()).strip()


def preview_listing(preview: PlacePreview) -> str:
    rows = preview.rows
    lines = [f"Previewed {len(preview.locations)} of {len(rows)} places. Fix anything by text, for example "
             "'replace 2 with Portland, Oregon', 'remove 3' or 'add Reno'."]
    for row in rows[:PREVIEW_LINES]:
        if row.status != "resolved":
            lines.append(f"{row.index}. '{row.input}' not found; replace or remove it")
            continue
        detail = f" ({row.lat:.4f}, {row.lon:.4f})" if row.source != "coordinates" else ""
        population = f"; population {row.population:,}" if row.population else ""
        note = f"; top of {row.candidate_count} matches, check it" if row.ambiguous else ""
        lines.append(f"{row.index}. {row.name}{detail}{population}{note}")
    if len(rows) > PREVIEW_LINES:
        lines.append(f"... and {len(rows) - PREVIEW_LINES} more")
    # A blank line keeps the attribution out of the numbered markdown list.
    return "\n".join(lines + ([""] + preview.attribution if preview.attribution else []))


HISTORY_LIMIT = 50
# The products behind each weather type, as named in the local catalog and adapters.
PRODUCT_DETAILS = {
    "historical": "ERA5 and ERA5-Land (CDS, Open-Meteo), NSRDB actual years, NOAA ISD stations",
    "tmy": "NSRDB TMY/TDY/TGY, PVGIS TMY",
    "tmyx": "OneBuilding TMYx files",
    "published": "OneBuilding TMY3, TMY2 and other published EPWs",
}


def plan_summary_markdown(request: dict, rows: list[dict]) -> str:
    """One markdown bullet per planned download: place, period, source and status."""
    locations = request.get("locations")
    locations = locations if isinstance(locations, list) else [locations] if isinstance(locations, dict) else []
    lines = []
    for row in rows:
        index = row.get("occurrence_index")
        place = locations[index] if isinstance(index, int) and index < len(locations) else None
        label = (place.get("name") or f"{place['lat']:.4f}, {place['lon']:.4f}") if place else f"Location {index}"
        start = row.get("period_start")
        period = str(start)[:4] if start else "reference"
        selection = row.get("dataset_selection") or {}
        source = f"{selection['provider']}/{selection['dataset']}" if selection.get("provider") else "no source"
        status = row.get("status", "unknown")
        codes = f" ({', '.join(row['issue_codes'])})" if row.get("issue_codes") else ""
        lines.append(f"- **{label}** · {period} · {source} · {status}{codes}")
    return "\n".join(lines)


def explicit_weather_years(text: str) -> set[int]:
    """A building count must not turn into a weather year, even if a model proposes it."""
    years = set()
    for match in re.finditer(r"\b(?:18|19|20|21)\d{2}\b", text):
        if not re.match(r"\s+buildings?\b", text[match.end():], re.I):
            years.add(int(match.group()))
    for match in re.finditer(r"\b((?:18|19|20|21)\d{2})\s*(?:-|–|—|to|through)\s*"
                             r"((?:18|19|20|21)\d{2})\b", text, re.I):
        start, end = int(match.group(1)), int(match.group(2))
        if 0 <= end - start <= 30:
            years.update(range(start, end + 1))
    return years


class ChatCoordinator:
    def __init__(self, service: Any, *, parser: Any = None, path: str | Path | None = None):
        self.service = service
        self.parser = parser or OfflineParser()
        self.path = Path(path or service.config.data_root / "chat" / "sessions.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS actions (session_id TEXT, key TEXT, response TEXT, "
                       "PRIMARY KEY (session_id, key))")
            # The state before each change, so the user can go back one step at a time.
            db.execute("CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                       "session_id TEXT, state TEXT)")
        self.queue_path = self.path.with_name("turns.sqlite")
        self.queue_lock = threading.Lock()
        self.queue_wake = threading.Event()
        self.queue_worker: threading.Thread | None = None
        with self._queue_db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS turns (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                       "id TEXT UNIQUE, session_id TEXT, key TEXT, text TEXT, state TEXT, "
                       "error_code TEXT, UNIQUE(session_id, key))")
            db.execute("UPDATE turns SET state='queued' WHERE state='running'")
            pending = db.execute("SELECT 1 FROM turns WHERE state='queued' LIMIT 1").fetchone()
        if pending:
            self._ensure_queue_worker()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def _queue_db(self):
        db = sqlite3.connect(self.queue_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue_turn(self, session_id: str, text: str, key: str) -> dict:
        if not text.strip() or len(text) > 4000:
            raise ChatActionError("Message must contain 1–4000 characters")
        if not key or len(key) > 100:
            raise ChatActionError("An idempotency key is required")
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise ChatActionError("Invalid session ID")
        with self._queue_db() as db:
            previous = db.execute("SELECT id, state FROM turns WHERE session_id=? AND key=?",
                                  (session_id, key)).fetchone()
            if previous:
                if previous["state"] == "failed":
                    db.execute("UPDATE turns SET state='queued', error_code=NULL WHERE id=?",
                               (previous["id"],))
                queue_id = previous["id"]
            else:
                count = db.execute("SELECT COUNT(*) FROM turns WHERE session_id=? AND "
                                   "state IN ('queued', 'running')", (session_id,)).fetchone()[0]
                if count >= 10:
                    raise ChatActionError("Too many waiting messages")
                queue_id = uuid.uuid4().hex
                db.execute("INSERT INTO turns (id, session_id, key, text, state) "
                           "VALUES (?, ?, ?, ?, 'queued')",
                           (queue_id, session_id, key, safe_prompt(text, limit=4000)))
        self._ensure_queue_worker()
        self.queue_wake.set()
        return self.queued_turn(queue_id)

    def queued_turn(self, queue_id: str) -> dict:
        with self._queue_db() as db:
            row = db.execute("SELECT seq, id, session_id, state, error_code FROM turns "
                             "WHERE id=?", (queue_id,)).fetchone()
            if row is None:
                raise KeyError(queue_id)
            position = db.execute("SELECT COUNT(*) FROM turns WHERE session_id=? AND "
                                  "state IN ('queued', 'running') AND seq<=?",
                                  (row["session_id"], row["seq"])).fetchone()[0]
        return {"queue_id": row["id"], "session_id": row["session_id"],
                "state": row["state"], "position": position,
                "error_code": row["error_code"]}

    def withdraw_turn(self, queue_id: str) -> dict:
        with self._queue_db() as db:
            row = db.execute("SELECT state FROM turns WHERE id=?", (queue_id,)).fetchone()
            if row is None:
                raise KeyError(queue_id)
            if row["state"] == "queued":
                db.execute("UPDATE turns SET state='cancelled' WHERE id=?", (queue_id,))
            elif row["state"] == "running":
                raise ChatActionError("This message is already running")
        return self.queued_turn(queue_id)

    def _ensure_queue_worker(self):
        with self.queue_lock:
            if self.queue_worker and self.queue_worker.is_alive():
                return
            self.queue_worker = threading.Thread(target=self._drain_turns,
                                                  name="openepw-chat-turns", daemon=True)
            self.queue_worker.start()

    def _drain_turns(self):
        while True:
            with self._queue_db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT id, session_id, key, text FROM turns AS candidate "
                                 "WHERE state='queued' AND NOT EXISTS (SELECT 1 FROM turns "
                                 "AS active WHERE active.session_id=candidate.session_id "
                                 "AND active.state='running') ORDER BY seq LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE turns SET state='running' WHERE id=? AND state='queued'",
                               (row["id"],))
            if row is None:
                self.queue_wake.wait(timeout=2)
                self.queue_wake.clear()
                continue
            state = "completed"
            error_code = None
            try:
                for attempt in range(2):
                    try:
                        revision = self.get(row["session_id"])["revision"]
                        self.turn(row["session_id"], row["text"], revision, row["key"])
                        break
                    except StaleSession:
                        if attempt:
                            raise
            except Exception:
                state = "failed"
                error_code = "TURN_FAILED"
            with self._queue_db() as db:
                db.execute("UPDATE turns SET state=?, error_code=? WHERE id=?",
                           (state, error_code, row["id"]))

    def create(self) -> dict:
        state = {"schema_version": "0.1", "id": uuid.uuid4().hex, "revision": 0,
                 "facts": {}, "events": [], "active_card": None, "plan_hash": None,
                 "job_id": None, "job_ids": [], "view_ids": []}
        with self.lock, self._db() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?)", (state["id"], json.dumps(state)))
        return state

    def get(self, session_id: str) -> dict:
        with self._db() as db:
            row = db.execute("SELECT state FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return json.loads(row["state"])

    def _event(self, state: dict, kind: str, text: str | None = None, data: dict | None = None):
        event = {"id": len(state["events"]) + 1, "type": kind}
        if text is not None:
            event["text"] = safe_prompt(text, limit=4000)
        if data is not None:
            event["data"] = data
        state["events"].append(event)

    def _change(self, session_id: str, revision: int, key: str, update):
        if not key or len(key) > 100:
            raise ChatActionError("An idempotency key is required")
        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT response FROM actions WHERE session_id=? AND key=?",
                                  (session_id, key)).fetchone()
            if previous:
                return json.loads(previous["response"])
            row = db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            state = json.loads(row["state"])
            if state["revision"] != revision:
                raise StaleSession(state)
            db.execute("INSERT INTO history (session_id, state) VALUES (?, ?)", (session_id, row["state"]))
            db.execute("DELETE FROM history WHERE session_id=? AND seq NOT IN (SELECT seq FROM history "
                       "WHERE session_id=? ORDER BY seq DESC LIMIT ?)", (session_id, session_id, HISTORY_LIMIT))
            state["revision"] += 1
            update(state)
            serialized = json.dumps(state, allow_nan=False)
            db.execute("UPDATE sessions SET state=? WHERE id=?", (serialized, session_id))
            db.execute("INSERT INTO actions VALUES (?, ?, ?)", (session_id, key, serialized))
            return state

    @staticmethod
    def _place_card(question: dict) -> dict:
        options, answers = [], {}
        for index, option in enumerate(question.get("options", []), start=1):
            if question["field"] == "region":
                label = option["label"]
                answer = str(index) if question.get("numbered") else label
            elif question["field"] == "definition":
                label, answer = f"{option['min_population']:,}", str(option["min_population"])
            else:
                label = "All (1,000)" if option["limit"] >= 1000 else str(option["limit"])
                answer = "all" if option["limit"] >= 1000 else f"top {option['limit']}"
            options.append({"id": f"place:{index}", "label": label})
            answers[f"place:{index}"] = answer
        return {"kind": "choice", "prompt": question["prompt"], "options": options,
                "data": {"place_answers": answers, "field": question["field"]}}

    def back(self, session_id: str, revision: int, key: str) -> dict:
        """Return to the state before the latest step; a started job cannot be undone."""
        if not key or len(key) > 100:
            raise ChatActionError("An idempotency key is required")
        with self.lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT response FROM actions WHERE session_id=? AND key=?",
                                  (session_id, key)).fetchone()
            if previous:
                return json.loads(previous["response"])
            row = db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            current = json.loads(row["state"])
            if current["revision"] != revision:
                raise StaleSession(current)
            earlier = db.execute("SELECT seq, state FROM history WHERE session_id=? ORDER BY seq DESC LIMIT 1",
                                 (session_id,)).fetchone()
            if earlier is None:
                raise ChatActionError("There is no earlier step to go back to")
            restored = json.loads(earlier["state"])
            if (restored.get("job_id") != current.get("job_id")
                    or restored.get("job_ids") != current.get("job_ids")):
                raise ChatActionError("A weather job already started in that step; start over instead")
            restored["revision"] = current["revision"] + 1
            serialized = json.dumps(restored, allow_nan=False)
            db.execute("DELETE FROM history WHERE seq=?", (earlier["seq"],))
            db.execute("UPDATE sessions SET state=? WHERE id=?", (serialized, session_id))
            db.execute("INSERT INTO actions VALUES (?, ?, ?)", (session_id, key, serialized))
            return restored

    def _question(self, state: dict):
        facts = state["facts"]
        card = None
        if facts.get("place_set"):
            card = self._place_card(facts["place_set"]["questions"][0])
        elif facts.get("candidates") and not facts.get("location"):
            card = {"kind": "choice", "prompt": "Choose a location", "options": [
                {"id": item["id"], "label": item.get("name") or item["id"]}
                for item in facts["candidates"]]}
        elif not facts.get("location") and not facts.get("geography"):
            card = {"kind": "text", "prompt": "Where do you need weather?"}
        elif not facts.get("product"):
            card = {"kind": "choice", "prompt": "Which weather product?", "options": [
                {"id": key, "label": label, "detail": PRODUCT_DETAILS[key]}
                for key, label in (("historical", "Actual-year weather"), ("tmy", "TMY reference"),
                                   ("tmyx", "TMYx published reference"),
                                   ("published", "Other published EPW"))]}
        elif facts["product"] == "historical" and not facts.get("years"):
            card = {"kind": "text", "prompt": "Which actual year or years?"}
        else:
            card = {"kind": "plan_review", "prompt": "Assess options and review a plan",
                    "data": {"facts": {key: facts.get(key) for key in
                                       ("location", "geography", "product", "years", "provider")}}}
        if card:
            card.update({"id": uuid.uuid4().hex, "revision": state["revision"]})
        state["active_card"] = card
        if card:
            self._event(state, "question" if card["kind"] != "plan_review" else "plan",
                        card["prompt"])

    def _apply_preview(self, state: dict, preview: PlacePreview) -> None:
        facts = state["facts"]
        ambiguous = sum(row.ambiguous for row in preview.rows)
        missing = sum(row.status != "resolved" for row in preview.rows)
        summary = f"Previewed {len(preview.locations)} of {len(preview.rows)} places"
        summary += f" · {ambiguous} ambiguous" if ambiguous else ""
        summary += f" · {missing} not found" if missing else ""
        self._event(state, "tool", summary, {"tool": "places", "phase": "result",
                                             "digest": preview.digest})
        points = [location.model_dump(mode="json") for location in preview.locations]
        facts["place_rows"] = [row.model_dump(mode="json", exclude_none=True) for row in preview.rows]
        facts.pop("location", None)
        facts.pop("candidates", None)
        if points:
            facts["geography"] = points
            facts["resolved_points"] = points
        else:
            facts.pop("geography", None)
            facts.pop("resolved_points", None)
        state["plan_hash"] = None
        facts.pop("availability", None)
        self._event(state, "message", preview_listing(preview), {"role": "assistant", "places": True})

    def _preview(self, state: dict, items: list) -> None:
        self._event(state, "tool", "Previewing places", {"tool": "places", "phase": "call"})
        self._apply_preview(state, self.service.preview_places(items))

    def _continue_place_set(self, state: dict, reply: str) -> None:
        facts = state["facts"]
        result = self.service.interpret_places(reply, facts["place_set"]["draft"])
        self._set_questions(state, result)

    def _set_questions(self, state: dict, result: dict) -> None:
        facts = state["facts"]
        if result["questions"]:
            questions = result["questions"]
            questions[0]["numbered"] = bool(result["draft"].get("region_options"))
            facts["place_set"] = {"draft": result["draft"], "questions": questions}
            return
        facts.pop("place_set", None)
        self._event(state, "tool", "Listing GeoNames places", {"tool": "places", "phase": "call"})
        self._apply_preview(state, self.service.place_set(PlaceSetQuery.model_validate(result["query"])))

    def _route_places(self, state: dict, text: str) -> bool:
        """Handle place lists, coordinate lists, sets and edits; False leaves the old flow."""
        facts = state["facts"]
        if facts.get("place_set"):
            self._continue_place_set(state, text)
            return True
        rows = facts.get("place_rows")
        if rows:
            labels = [row.get("name") or row["input"] for row in rows]
            edited = apply_edit(labels, text)
            if edited is not None:
                if not edited:
                    for key in ("place_rows", "geography", "resolved_points"):
                        facts.pop(key, None)
                    self._event(state, "message", "The place list is now empty; give places or coordinates.",
                                {"role": "assistant"})
                    return True
                by_label = dict(zip(labels, rows))
                self._preview(state, [by_label.get(label, label) for label in edited])
                return True
        if describe_place_set(text):
            self._set_questions(state, self.service.interpret_places(text))
            return True
        candidate = place_text(text)
        if not candidate:
            return False
        routed = classify_places(candidate)
        if routed["kind"] == "list":
            self._preview(state, routed["items"])
            return True
        if routed["kind"] == "coordinates" and len(routed["points"]) > 1:
            self._preview(state, [f"{lat}, {lon}" for lat, lon in routed["points"]])
            return True
        return False

    def turn(self, session_id: str, text: str, revision: int, key: str) -> dict:
        if not text.strip() or len(text) > 4000:
            raise ChatActionError("Message must contain 1–4000 characters")

        def update(state):
            self._event(state, "message", text, {"role": "user"})
            facts = state["facts"]
            lower = text.casefold().strip().rstrip("?!. ")
            if lower in ("hello", "hi", "hey", "ok", "okay", "thanks", "thank you"):
                self._event(state, "message", "Tell me a place, years, or a weather question.",
                            {"role": "assistant"})
                return
            if re.search(r"\b(?:future|ssp\d{3}|rcp\d{2})\b", text, re.I):
                self._event(state, "message", "Future-weather planning is temporarily unavailable.",
                            {"role": "assistant"})
                return
            if re.search(r"\b(?:where is|my file|my download|download status|progress)\b", text, re.I):
                self._event(state, "message", "Your current job and artifacts are shown below.",
                            {"role": "assistant", "job_id": state.get("job_id")})
                return
            # A clarification reply or a list edit is complete on its own; a new message
            # may also carry product and years for the parser.
            reply_or_edit = bool(facts.get("place_set")) or bool(facts.get("place_rows") and re.match(
                r"\s*(?:remove|drop|delete|replace|change|swap|add)\b", text, re.I))
            try:
                places_handled = self._route_places(state, text)
            except OpenEPWError as error:
                self._event(state, "message", error.issue.message, {"role": "assistant"})
                self._question(state)
                return
            if places_handled and reply_or_edit:
                self._question(state)
                return
            intents = self.parser.parse_many(safe_prompt(text, limit=4000))
            grounded_years = explicit_weather_years(text)
            for intent in intents[:5]:
                if getattr(intent, "kind", None) == "future":
                    self._event(state, "message", "Future-weather planning is temporarily unavailable.",
                                {"role": "assistant"})
                    continue
                if getattr(intent, "product", None):
                    facts["product"] = "historical" if intent.product == "amy" else intent.product
                if getattr(intent, "years", None):
                    confirmed = [year for year in intent.years if year in grounded_years]
                    if confirmed:
                        facts["years"] = confirmed
                if getattr(intent, "provider", None):
                    facts["provider"] = intent.provider
                if places_handled:
                    pass  # the place preview already set the geography for this message
                elif getattr(intent, "lat", None) is not None and getattr(intent, "lon", None) is not None:
                    facts["location"] = Location(lat=intent.lat, lon=intent.lon).model_dump(mode="json")
                    facts.pop("candidates", None)
                    facts.pop("geography", None)
                    facts.pop("resolved_points", None)
                elif getattr(intent, "locations", None):
                    request = WeatherRequest.model_validate({"locations": intent.locations,
                                                            "years": [2000]})
                    facts["geography"] = request.model_dump(mode="json")["locations"]
                    facts["resolved_points"] = [item.model_dump(mode="json")
                                                for item in self.service.locations(request)]
                    facts.pop("location", None)
                    facts.pop("candidates", None)
                elif getattr(intent, "place", None):
                    self._event(state, "tool", "Geocoding place", {"tool": "geocode", "phase": "call"})
                    geocoded = self.service.geocode(intent.place)
                    candidates = [c.model_dump(mode="json") for c in geocoded.candidates]
                    facts["candidates"] = candidates
                    facts.pop("location", None)
                    facts.pop("geography", None)
                    facts.pop("resolved_points", None)
                    self._event(state, "tool", f"Found {len(candidates)} location candidates",
                                {"tool": "geocode", "phase": "result"})
                if getattr(intent, "product_id", None):
                    facts["product_id"] = intent.product_id
            if intents:
                state["plan_hash"] = None
                facts.pop("availability", None)
            self._question(state)

        return self._change(session_id, revision, key, update)

    def answer(self, session_id: str, question_revision: int, choice_id: str, key: str) -> dict:
        def update(state):
            card = state["active_card"]
            if not card or card["revision"] != question_revision or card["kind"] != "choice":
                raise StaleSession(state)
            labels = {option["id"]: option["label"] for option in card["options"]}
            if choice_id not in labels:
                raise ChatActionError("Unknown choice")
            answers = (card.get("data") or {}).get("place_answers")
            if answers:
                self._event(state, "message", labels[choice_id],
                            {"role": "user", "choice": True, "choice_id": choice_id})
                try:
                    self._continue_place_set(state, answers[choice_id])
                except OpenEPWError as error:
                    self._event(state, "message", error.issue.message, {"role": "assistant"})
                self._question(state)
                return
            if state["facts"].get("candidates"):
                state["facts"]["location"] = next(item for item in state["facts"]["candidates"]
                                                  if item["id"] == choice_id)
                state["facts"].pop("candidates", None)
                state["facts"].pop("geography", None)
                state["facts"].pop("resolved_points", None)
            else:
                state["facts"]["product"] = choice_id
            state["plan_hash"] = None
            state["facts"].pop("availability", None)
            self._event(state, "message", labels[choice_id],
                        {"role": "user", "choice": True, "choice_id": choice_id})
            self._question(state)

        return self._change(session_id, question_revision, key, update)

    @staticmethod
    def _request(facts: dict) -> WeatherRequest:
        location = facts.get("geography") or facts.get("location")
        if not location or not facts.get("product"):
            raise ChatActionError("Location and weather product are required")
        return WeatherRequest.model_validate({
            "locations": location, "product": facts["product"],
            "years": facts.get("years", []), "providers": [facts["provider"]]
            if facts.get("provider") else [], "product_id": facts.get("product_id"),
        })

    def set_geography(self, session_id: str, geography: Any, revision: int, key: str) -> dict:
        # Validate through the canonical service request model, including sampling caps.
        validated = WeatherRequest.model_validate({"locations": geography, "years": [2000]})
        resolved = [point.model_dump(mode="json") for point in self.service.locations(validated)]

        def update(state):
            state["facts"]["geography"] = validated.model_dump(mode="json")["locations"]
            state["facts"]["resolved_points"] = resolved
            state["facts"].pop("location", None)
            state["facts"].pop("candidates", None)
            state["plan_hash"] = None
            state["facts"].pop("availability", None)
            self._event(state, "tool", "Geography accepted", {"tool": "geography", "phase": "result",
                                                          "point_count": len(resolved)})
            self._question(state)

        return self._change(session_id, revision, key, update)

    def prepare(self, session_id: str, revision: int, key: str) -> dict:
        def update(state):
            request = self._request(state["facts"])
            self._event(state, "tool", "Assessing catalog", {"tool": "availability", "phase": "call"})
            availability = self.service.assess_availability(WeatherAvailabilityQuery(request=request))
            assessment = {
                "checked_at": availability.checked_at.isoformat(),
                "snapshots": [snapshot.model_dump(mode="json") for snapshot in availability.snapshots],
                "options": [{"provider": option.product.provider,
                             "dataset": option.product.dataset,
                             "footprint": option.product.footprint,
                             "status": option.eligibility.status,
                             "access": option.eligibility.access,
                             "health": option.eligibility.health,
                             "evidence_ids": option.eligibility.evidence_ids,
                             "evidence_bases": option.eligibility.evidence_bases,
                             "unknowns": option.eligibility.unknowns,
                             "reasons": option.eligibility.reasons,
                             "rank": option.rank,
                             "occurrence_index": option.occurrence_index}
                            for option in sorted(availability.options,
                                                 key=lambda item: (item.occurrence_index,
                                                                   item.rank or 9999))[:30]],
                "issues": [issue.model_dump(mode="json") for issue in availability.issues],
            }
            state["facts"]["availability"] = assessment
            self._event(state, "tool", "Catalog assessment complete",
                        {"tool": "availability", "phase": "result",
                         "checked_at": assessment["checked_at"],
                         "option_count": len(availability.options),
                         "issues": assessment["issues"]})
            self._event(state, "tool", "Preparing weather plan", {"tool": "weather_plan", "phase": "call"})
            plan = self.service.plan(request)
            state["plan_hash"] = plan.plan_hash
            rows = [row.model_dump(mode="json") for row in plan.batch_rows]
            summary = plan_summary_markdown(request.model_dump(mode="json"), rows)
            card = {"id": uuid.uuid4().hex, "revision": state["revision"],
                    "kind": "plan_review", "prompt": "Review these outputs, then select Run",
                    "data": {"plan_hash": plan.plan_hash, "request": request.model_dump(mode="json"),
                             "summary": summary,
                             "outputs": [output.model_dump(mode="json") for output in plan.outputs],
                             "batch_rows": [row.model_dump(mode="json") for row in plan.batch_rows],
                             "availability": assessment,
                             "warnings": plan.warnings, "issues": [issue.model_dump(mode="json")
                                                                      for issue in plan.issues]}}
            state["active_card"] = card
            self._event(state, "plan", "Plan ready for review", card["data"])

        return self._change(session_id, revision, key, update)

    def run(self, session_id: str, revision: int, key: str, runner: Any) -> dict:
        def update(state):
            plan_hash = state.get("plan_hash")
            card = state.get("active_card")
            if not plan_hash or not card or card.get("data", {}).get("plan_hash") != plan_hash:
                raise ChatActionError("A current reviewed plan is required")
            plan = self.service.plan_store.get(plan_hash)
            job = runner.submit(plan, f"chat:{session_id}:{key}")
            state["job_id"] = job.id
            state["job_ids"] = [job.id]
            self._event(state, "tool", "Submitting reviewed plan", {"tool": "weather_jobs", "phase": "call",
                                                                "plan_hash": plan_hash})
            self._event(state, "job", "Weather job started", {"job_id": job.id,
                                                                "plan_hash": plan_hash})
            state["active_card"] = None

        return self._change(session_id, revision, key, update)

    def retry(self, session_id: str, revision: int, key: str, runner: Any) -> dict:
        def update(state):
            previous = state.get("job_id")
            if not previous:
                raise ChatActionError("No current weather job to retry")
            if len(state.get("job_ids") or [previous]) >= 10:
                raise ChatActionError("Retry chain limit reached; start a new plan")
            job = runner.retry_failed(previous, f"chat-retry:{session_id}:{key}")
            state["job_id"] = job.id
            state.setdefault("job_ids", [previous]).append(job.id)
            self._event(state, "tool", "Retrying failed outputs",
                        {"tool": "weather_jobs", "phase": "call", "retry_of": previous})
            self._event(state, "job", "Retry job started",
                        {"job_id": job.id, "retry_of": previous})

        return self._change(session_id, revision, key, update)

    def compact(self, session_id: str, runner: Any):
        state = self.get(session_id)
        job_ids = state.get("job_ids") or [state.get("job_id")]
        job_ids = [job_id for job_id in job_ids if job_id]
        if not job_ids:
            raise ChatActionError("No current weather job to download")
        if len(job_ids) == 1:
            return runner.export_compact(job_ids[0])
        from ..artifacts.export import export_compact_chain

        return export_compact_chain(runner, job_ids)

    def attach_upload(self, session_id: str, revision: int, key: str,
                      artifact_id: str) -> dict:
        ref, _ = self.service.artifacts.resolve(artifact_id)
        if ref.role != "baseline":
            raise ChatActionError("Upload must refer to a registered user EPW")

        def update(state):
            ids = state["facts"].setdefault("uploaded_artifact_ids", [])
            if artifact_id not in ids:
                ids.append(artifact_id)
            self._event(state, "artifacts", "User EPW registered for analysis",
                        {"artifact_id": artifact_id, "origin": "user_provided"})

        return self._change(session_id, revision, key, update)

    def view(self, session_id: str, revision: int, key: str, runner: Any,
             request: VisualizationRequest, *, prompt: str | None = None) -> dict:
        def update(state):
            if prompt:
                self._event(state, "message", prompt, {"role": "user"})
            allowed = set(state["facts"].get("uploaded_artifact_ids", []))
            for job_id in state.get("job_ids") or [state.get("job_id")]:
                if not job_id:
                    continue
                job = runner.store.get(job_id)
                if job.bundle:
                    allowed.update(ref.id for ref in job.bundle.weather)
            if not set(request.artifact_ids) <= allowed:
                raise ChatActionError("View artifacts must come from this session's job or upload")
            self._event(state, "tool", "Preparing existing weather data",
                        {"tool": "weather_visualize", "phase": "call"})
            page = self.service.visualize_weather(request)
            view_id = page["view_id"]
            if view_id not in state["view_ids"]:
                state["view_ids"].append(view_id)
            self._event(state, "view", "Prepared weather view",
                        {"view_id": view_id, "family": request.family,
                         "variable": request.variable, "artifact_ids": request.artifact_ids})

        return self._change(session_id, revision, key, update)
