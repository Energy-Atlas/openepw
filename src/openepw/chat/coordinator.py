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
from ..models import Location, WeatherRequest
from ..visualization.models import VisualizationRequest


class StaleSession(Exception):
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        super().__init__("Session changed; review the current question")


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
        coordinates = re.search(r"(?<!\d)(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", text)
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

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self) -> dict:
        state = {"schema_version": "0.1", "id": uuid.uuid4().hex, "revision": 0,
                 "facts": {}, "events": [], "active_card": None, "plan_hash": None,
                 "job_id": None, "view_ids": []}
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
            raise ValueError("An idempotency key is required")
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
            state["revision"] += 1
            update(state)
            serialized = json.dumps(state, allow_nan=False)
            db.execute("UPDATE sessions SET state=? WHERE id=?", (serialized, session_id))
            db.execute("INSERT INTO actions VALUES (?, ?, ?)", (session_id, key, serialized))
            return state

    def _question(self, state: dict):
        facts = state["facts"]
        card = None
        if facts.get("candidates") and not facts.get("location"):
            card = {"kind": "choice", "prompt": "Choose a location", "options": [
                {"id": item["id"], "label": item.get("name") or item["id"]}
                for item in facts["candidates"]]}
        elif not facts.get("location") and not facts.get("geography"):
            card = {"kind": "text", "prompt": "Where do you need weather?"}
        elif not facts.get("product"):
            card = {"kind": "choice", "prompt": "Which weather product?", "options": [
                {"id": "historical", "label": "Actual-year weather"},
                {"id": "tmy", "label": "TMY reference"},
                {"id": "tmyx", "label": "TMYx published reference"},
                {"id": "published", "label": "Other published EPW"}]}
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

    def turn(self, session_id: str, text: str, revision: int, key: str) -> dict:
        if not text.strip() or len(text) > 4000:
            raise ValueError("Message must contain 1–4000 characters")

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
                if getattr(intent, "lat", None) is not None and getattr(intent, "lon", None) is not None:
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
            if choice_id not in [option["id"] for option in card["options"]]:
                raise ValueError("Unknown choice")
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
            self._event(state, "message", choice_id, {"role": "user", "choice": True})
            self._question(state)

        return self._change(session_id, question_revision, key, update)

    @staticmethod
    def _request(facts: dict) -> WeatherRequest:
        location = facts.get("geography") or facts.get("location")
        if not location or not facts.get("product"):
            raise ValueError("Location and weather product are required")
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
            card = {"id": uuid.uuid4().hex, "revision": state["revision"],
                    "kind": "plan_review", "prompt": "Review these outputs, then select Run",
                    "data": {"plan_hash": plan.plan_hash, "request": request.model_dump(mode="json"),
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
                raise ValueError("A current reviewed plan is required")
            plan = self.service.plan_store.get(plan_hash)
            job = runner.submit(plan, f"chat:{session_id}:{key}")
            state["job_id"] = job.id
            self._event(state, "tool", "Submitting reviewed plan", {"tool": "weather_jobs", "phase": "call",
                                                                "plan_hash": plan_hash})
            self._event(state, "job", "Weather job started", {"job_id": job.id,
                                                                "plan_hash": plan_hash})
            state["active_card"] = None

        return self._change(session_id, revision, key, update)

    def attach_upload(self, session_id: str, revision: int, key: str,
                      artifact_id: str) -> dict:
        ref, _ = self.service.artifacts.resolve(artifact_id)
        if ref.role != "baseline":
            raise ValueError("Upload must refer to a registered user EPW")

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
            if state.get("job_id"):
                job = runner.store.get(state["job_id"])
                if job.bundle:
                    allowed.update(ref.id for ref in job.bundle.weather)
            if not set(request.artifact_ids) <= allowed:
                raise ValueError("View artifacts must come from this session's job or upload")
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
