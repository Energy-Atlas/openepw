"""Small local conversation layer over the reference MCP agent."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .agent import AgentIntent, AgentResult, IntentParser, ReferenceAgent
from .mcp_client import MCPToolFailure
from .model import ModelUnavailable
from .trace import ArtifactPort, LangSmithTrace


def _read_key(name: str, env_file: str | Path) -> str | None:
    """Read a key from the shell or existing dotenv without modifying it."""
    existing = os.environ.get(name, "").strip()
    if existing:
        return existing
    source = Path(env_file)
    if source.is_file():
        for line in source.read_text(encoding="utf-8-sig").splitlines():
            if re.match(r"^\s*" + re.escape(name) + r"\s*=", line):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return None


def load_model_key(env_file: str | Path = ".env") -> str:
    key = _read_key("OPENAI_API_KEY", env_file)
    if key:
        return key
    raise ModelUnavailable("OPENAI_API_KEY is missing from the shell and .env")


def load_trace_key(env_file: str | Path = ".env") -> str | None:
    return _read_key("LANGSMITH_API_KEY", env_file)


class ChatSession:
    """One terminal conversation; the MCP service remains the source of truth."""

    def __init__(self, agent: ReferenceAgent, mcp: ArtifactPort,
                 model: IntentParser, *, auto_submit: bool = True,
                 tracer: LangSmithTrace | None = None):
        self.agent = agent
        self.mcp = mcp
        self.model = model
        self.auto_submit = auto_submit
        self.exit_requested = False
        self.selected_baseline_id: str | None = None
        self.weather_artifacts: tuple[str, ...] = ()
        self.last_weather_location: dict[str, Any] | None = None
        self.draft: AgentIntent | None = None
        self.selected_location: dict[str, Any] | None = None
        self.pending_choices: tuple[dict[str, Any], ...] = ()
        self.pending_exploration = False
        self.pending_question: str | None = None
        self.pending_view_active = False
        self.pending_view_family: str | None = None
        self.pending_view_options: tuple[tuple[str, str], ...] = ()
        self.reviewed_intent: AgentIntent | None = None
        self.reviewed_location: dict[str, Any] | None = None
        self.reviewed_reply: str | None = None
        self.tracer = tracer
        self._given_delta: AgentIntent | None = None

    def export_state(self) -> dict[str, Any]:
        """Return only typed conversation facts for a durable local checkpoint."""
        return {
            "draft": self.draft.model_dump(mode="json") if self.draft else None,
            "selected_location": self.selected_location,
            "pending_choices": list(self.pending_choices),
            "pending_exploration": self.pending_exploration,
            "pending_question": self.pending_question,
            "pending_view_active": self.pending_view_active,
            "pending_view_family": self.pending_view_family,
            "pending_view_options": list(self.pending_view_options),
            "reviewed_intent": (self.reviewed_intent.model_dump(mode="json")
                                if self.reviewed_intent else None),
            "reviewed_location": self.reviewed_location,
            "reviewed_reply": self.reviewed_reply,
            "selected_baseline_id": self.selected_baseline_id,
            "weather_artifacts": list(self.weather_artifacts),
            "last_weather_location": self.last_weather_location,
            "auto_submit": self.auto_submit,
            "plan_hash": self.agent.plan_hash,
            "job_id": self.agent.job_id,
        }

    def import_state(self, state: dict[str, Any]) -> None:
        self.draft = AgentIntent.model_validate(state["draft"]) if state.get("draft") else None
        self.selected_location = state.get("selected_location")
        self.pending_choices = tuple(state.get("pending_choices") or ())
        self.pending_exploration = bool(state.get("pending_exploration"))
        self.pending_question = state.get("pending_question")
        self.pending_view_active = bool(state.get("pending_view_active"))
        self.pending_view_family = state.get("pending_view_family")
        self.pending_view_options = tuple(tuple(item) for item in
                                          state.get("pending_view_options") or ())
        self.reviewed_intent = (AgentIntent.model_validate(state["reviewed_intent"])
                                if state.get("reviewed_intent") else None)
        self.reviewed_location = state.get("reviewed_location")
        self.reviewed_reply = state.get("reviewed_reply")
        self.selected_baseline_id = state.get("selected_baseline_id")
        self.weather_artifacts = tuple(state.get("weather_artifacts") or ())
        self.last_weather_location = state.get("last_weather_location")
        self.auto_submit = bool(state.get("auto_submit", self.auto_submit))
        # The agent's ID record is written during tool calls; it may be newer
        # than a graph checkpoint if the process stopped mid-turn.
        self.agent.plan_hash = self.agent.plan_hash or state.get("plan_hash")
        self.agent.job_id = self.agent.job_id or state.get("job_id")

    async def handle_intent(self, line: str, delta: AgentIntent) -> str:
        """Handle a previously extracted delta without a second model call."""
        self._given_delta = delta
        try:
            return await self.handle(line)
        finally:
            self._given_delta = None

    @staticmethod
    def _format(result: AgentResult) -> str:
        lines = [f"[{result.status}] {result.message}"]
        if result.plan_hash:
            lines.append("plan_hash: " + result.plan_hash)
        if result.job_id:
            lines.append("job_id: " + result.job_id)
        if result.artifact_ids:
            lines.append("EPW artifact IDs: " + ", ".join(result.artifact_ids))
        return "\n".join(lines)

    def _remember(self, result: AgentResult, *, update_request: bool = True) -> str:
        if result.artifact_ids:
            self.weather_artifacts = result.artifact_ids
        if not update_request:
            return self._format(result)
        self.pending_choices = result.location_choices
        self.pending_question = (result.message if result.status == "needs_clarification"
                                 else None)
        if result.status == "review_required" and self.draft is not None:
            self.reviewed_intent = self.draft.model_copy(deep=True)
            self.reviewed_location = self.selected_location.copy() if self.selected_location else None
            self.reviewed_reply = self._format(result)
        if result.status in ("completed", "partially_completed"):
            if self.draft and self.draft.kind == "weather":
                if self.selected_location:
                    self.last_weather_location = self.selected_location.copy()
                elif self.draft.locations and len(self.draft.locations) == 1:
                    self.last_weather_location = dict(self.draft.locations[0])
                elif self.draft.lat is not None and self.draft.lon is not None:
                    self.last_weather_location = {"lat": self.draft.lat, "lon": self.draft.lon}
                elif self.draft.place:
                    self.last_weather_location = {"place": self.draft.place}
            self.draft = None
            self.selected_location = None
            self.reviewed_intent = None
            self.reviewed_reply = None
        return self._format(result)

    @staticmethod
    def _choices_text(choices: tuple[dict[str, Any], ...]) -> str:
        listed = "; ".join(
            f"{index}. {item.get('name', 'unnamed')}"
            for index, item in enumerate(choices, start=1))
        return "Choose a location by number or exact name: " + listed

    def _explore_choices_text(self) -> str:
        return ("Actual-year weather (AMY) uses calendar years; TMY/TMYx/published are reference "
                "products. I need one location to assess catalog options. " +
                self._choices_text(self.pending_choices))

    def _choice(self, line: str) -> dict[str, Any] | None:
        if not self.pending_choices:
            return None
        if line.isdecimal():
            index = int(line)
            return (self.pending_choices[index - 1]
                    if 1 <= index <= len(self.pending_choices) else None)
        matches = [item for item in self.pending_choices
                   if self._place_key(str(item.get("name", ""))) == self._place_key(line)]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _product_year_conflict(intent: AgentIntent) -> str | None:
        if intent.product in ("tmy", "tmyx", "published") and intent.years:
            years = ", ".join(str(year) for year in intent.years)
            return (f"{intent.product.upper()} is a reference product, not actual-year "
                    f"weather for {years}. Choose actual-year weather for {years}, or "
                    "request the reference product without a year.")
        return None

    @staticmethod
    def _place_key(place: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", place.casefold())

    def _merge(self, delta: AgentIntent) -> AgentIntent:
        weather_fields = (delta.place, delta.locations, delta.lat, delta.lon,
                          delta.product, delta.years, delta.start, delta.end)
        future_fields = (delta.method, delta.climate_scenario, delta.climate_period,
                         delta.baseline_artifact_id)
        kind = delta.kind
        if kind == "unknown":
            kind = ("future" if any(future_fields) else
                    "weather" if any(weather_fields) else
                    self.draft.kind if self.draft else "unknown")
        if self.draft is None or (self.draft.kind != kind and kind != "unknown"):
            self.draft = AgentIntent(kind=kind)
            self.pending_choices = ()
            self.selected_location = None
        fields = ("place", "locations", "lat", "lon", "product", "years", "start", "end",
                  "provider", "product_id", "baseline_artifact_id", "signals_artifact_id",
                  "method", "climate_scenario", "climate_period", "reference_period")
        for field in fields:
            value = getattr(delta, field)
            if value not in (None, [], ""):
                if (field == "place" and self.draft.place
                        and self._place_key(self.draft.place) != self._place_key(value)):
                    self.pending_choices = ()
                    self.selected_location = None
                setattr(self.draft, field, value)
        if delta.product in ("tmy", "tmyx", "published") and not delta.years:
            self.draft.years = []
            self.draft.start = self.draft.end = None
        if self.draft.kind == "weather" and self.draft.years and self.draft.product is None:
            self.draft.product = "historical"
        return self.draft

    async def _explore(self, intent: AgentIntent) -> str:
        if intent.kind != "weather":
            return ("Weather choices include actual-year (AMY) weather and "
                    "TMY/TMYx/published products. Give a location and year to assess sources.")
        location = self.selected_location
        if location is None and intent.lat is not None and intent.lon is not None:
            location = {"lat": intent.lat, "lon": intent.lon}
        if location is None and intent.locations and len(intent.locations) == 1:
            location = intent.locations[0]
        if location is None and self.pending_choices:
            self.pending_exploration = True
            return self._explore_choices_text()
        if location is None and intent.place:
            choices = tuple((await self.agent.geocode_candidates(intent.place))[:10])
            if len(choices) != 1:
                self.pending_choices = choices
                self.pending_exploration = True
                return (self._explore_choices_text() if choices else
                        "No location matched. Give coordinates or a more specific place.")
            location = choices[0]
            self.selected_location = location
        if location is None:
            return "Give a location to assess available weather sources."
        if not intent.years:
            return ("Actual-year weather requires a year; TMY/TMYx/published are "
                    "reference products without an actual-year request. Which year do you need?")
        lines = ["Catalog support only means retrieval is eligible to try; weather quality "
                 "and simulation readiness require QC."]
        for product in ("historical", "tmy", "tmyx", "published"):
            request: dict[str, Any] = {"locations": location, "product": product}
            if product == "historical":
                request["years"] = intent.years
            result = await self.mcp.call(
                "weather_assess", query={"kind": "weather", "request": request,
                                         "purpose": "building_energy", "refresh": "never"})
            options_by_id = {option.get("id"): option for option in result.get("options", [])}
            locations = result.get("locations", [])
            ranked_ids = locations[0].get("ranked_option_ids", []) if locations else []
            options = ([options_by_id[option_id] for option_id in ranked_ids
                        if option_id in options_by_id] if ranked_ids else result.get("options", []))
            if any(issue.get("code") == "CATALOG_UNAVAILABLE"
                   for issue in result.get("issues", [])) and product == "historical":
                lines.append("Local inventory is not loaded; bundled contracts only.")
            snapshots = result.get("snapshots", [])
            if snapshots and product == "historical":
                lines.append("Catalog snapshot: " + str(snapshots[0].get("created_at", "unknown")) + ".")
            if not options:
                lines.append(f"{product}: no ranked catalog option; support unknown.")
                continue
            shown = []
            for option in options[:2]:
                source = option.get("product", {})
                eligibility = option.get("eligibility", {})
                detail = (f"{source.get('provider', 'unknown')}/{source.get('dataset', 'unknown')} "
                          f"{eligibility.get('status', 'unknown')} "
                          f"(access {eligibility.get('access', 'unknown')})")
                if eligibility.get("stale"):
                    detail += ", stale evidence"
                if eligibility.get("unknowns"):
                    detail += ", unknown: " + ", ".join(eligibility["unknowns"][:2])
                shown.append(detail)
            lines.append(f"{product}: " + ", ".join(shown) + ".")
        return "\n".join(lines)

    def _last_artifact(self) -> str | None:
        if len(self.weather_artifacts) == 1:
            return self.weather_artifacts[0]
        return self.selected_baseline_id

    def _block_future(self) -> str:
        self.draft = None
        self.pending_choices = ()
        self.pending_exploration = False
        self.pending_view_active = False
        self.pending_view_family = None
        self.pending_view_options = ()
        return "[blocked] FEATURE_SUSPENDED: Future-weather MCP workflows are temporarily unavailable."

    @staticmethod
    def _unquote(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]
        return value

    @staticmethod
    def is_view_request(line: str) -> bool:
        return bool(re.search(r"\b(?:visuali[sz]\w*|plot|chart|graph)\b", line,
                              re.IGNORECASE))

    @staticmethod
    def _view_family(line: str) -> str | None:
        lowered = line.casefold().replace("_", " ")
        if "wind rose" in lowered:
            return "wind_rose"
        if "monthly" in lowered or "month by month" in lowered:
            return "monthly_series"
        if "annual" in lowered or "yearly" in lowered or "year over year" in lowered:
            return "annual_series"
        if "histogram" in lowered or "distribution" in lowered:
            return "histogram"
        if "spatial" in lowered or "map" in lowered or "across locations" in lowered:
            return "spatial"
        if "hourly" in lowered or "time series" in lowered:
            return "time_series"
        return None

    @staticmethod
    def _view_variable(line: str) -> str | None:
        aliases = (
            ("dry_bulb", r"\b(?:dry[ _-]?bulb|air temperature|temperature)\b"),
            ("dew_point", r"\bdew[ _-]?point\b"),
            ("relative_humidity", r"\b(?:relative[ _-]?humidity|humidity)\b"),
            ("pressure", r"\bpressure\b"),
            ("wind_speed", r"\bwind[ _-]?speed\b"),
            ("wind_direction", r"\bwind[ _-]?direction\b"),
            ("ghi", r"\b(?:ghi|global horizontal irradiance)\b"),
            ("dni", r"\b(?:dni|direct normal irradiance)\b"),
            ("dhi", r"\b(?:dhi|diffuse horizontal irradiance)\b"),
        )
        return next((key for key, pattern in aliases if re.search(pattern, line, re.I)), None)

    async def _handle_view(self, line: str) -> str:
        if re.search(r"\b(?:future|climate scenario|ssp126|ssp245|ssp370|ssp585|"
                     r"rcp45|rcp85)\b", line, re.I):
            return self._block_future()
        family = self._view_family(line) or self.pending_view_family
        if family is None:
            self.pending_view_active = True
            return ("Which view do you need: hourly time series, monthly or annual "
                    "series, histogram, or spatial comparison?")
        capabilities = await self.mcp.call("weather_visualization_capabilities")
        families = {item["family"]: item["status"]
                    for item in capabilities.get("families", [])}
        if families.get(family) == "planned":
            self.pending_view_active = False
            self.pending_view_family = None
            self.pending_view_options = ()
            return (f"[unsupported] {family} is planned. Available views: hourly "
                    "time series, monthly or annual series, histogram, and spatial.")
        variable = self._view_variable(line)
        variables = capabilities.get("variables", {})
        if variable not in variables:
            self.pending_view_active = True
            self.pending_view_family = family
            self.pending_view_options = tuple(
                (key, f"{key} ({item['unit']})") for key, item in variables.items())
            options = ", ".join(key for key, _ in self.pending_view_options)
            return (f"Which weather variable should I use for the {family} view? "
                    f"Choose: {options}.")
        artifact_ids = list(self.weather_artifacts)
        if not artifact_ids and self.selected_baseline_id:
            artifact_ids = [self.selected_baseline_id]
        if not artifact_ids:
            return "No completed EPW artifact is selected. Retrieve or upload an EPW first."
        result = await self.mcp.call("weather_visualize", request={
            "artifact_ids": artifact_ids, "family": family, "variable": variable})
        self.pending_view_active = False
        self.pending_view_family = None
        self.pending_view_options = ()
        return "[visualization] " + json.dumps(result, sort_keys=True, allow_nan=False)

    async def handle(self, line: str) -> str:
        if self.tracer and line.strip():
            return await self.tracer.run_turn(line, self._handle)
        return await self._handle(line)

    async def _handle(self, line: str) -> str:
        line = line.strip()
        if not line:
            return ""
        try:
            if line.startswith("/"):
                return await self._command(line)
            if self.pending_view_active or self.is_view_request(line):
                return await self._handle_view(line)
            if re.search(r"\b(?:status|progress)\b", line, re.IGNORECASE) and re.search(
                    r"\b(?:my|job|download|request)\b", line, re.IGNORECASE):
                return await self._command("/status")
            if re.search(r"\b(?:downloaded\s+file|my\s+(?:downloaded\s+)?"
                         r"(?:file|epw)|where\s+is\s+(?:my|the)\s+(?:file|epw))\b",
                         line, re.IGNORECASE):
                if len(self.weather_artifacts) == 1:
                    return (await self._command("/inspect last") +
                            "\nUse /save last <output path> to write the EPW to a local file.")
                if self.weather_artifacts:
                    return "Several EPWs are available. Specify an artifact ID with /inspect or /save."
                return "No EPW artifact is selected. Use /status to check the current job."
            if self.agent.job_id and line.casefold().rstrip(".!?") in (
                    "ok", "okay", "thanks", "thank you"):
                return ("Use /status to check the job, /inspect last to review EPW QC, "
                        "or /save last <output path> to write a local file.")
            embedded_choice = (re.search(
                r"\b(?:for\s+)?(?:location|option|choice)\s+(\d+)\b", line,
                re.IGNORECASE) if self.pending_choices else None)
            year_reply = bool(re.fullmatch(r"(?:18|19|20|21)\d{2}", line))
            choice_match = (embedded_choice or re.fullmatch(
                r"(\d+)\b(?:\s*[,;:]\s*|\s+)?(.*)", line, re.IGNORECASE)
                if self.pending_choices and not year_reply else None)
            choice: dict[str, Any] | None
            if choice_match:
                index = int(choice_match.group(1))
                if not 1 <= index <= len(self.pending_choices):
                    return self._choices_text(self.pending_choices)
                choice = self.pending_choices[index - 1]
                remainder = ((line[:choice_match.start()] + " " + line[choice_match.end():])
                             if embedded_choice else choice_match.group(2)).strip(" ,;:")
            else:
                choice = self._choice(line)
                remainder = ""
            if choice is not None and self.draft is not None:
                self.selected_location = choice
                self.pending_choices = ()
                was_exploring = self.pending_exploration
                self.pending_exploration = False
                if remainder:
                    line = remainder
                elif was_exploring:
                    return await self._explore(self.draft)
                else:
                    if self.draft.kind == "future":
                        return self._block_future()
                    conflict = self._product_year_conflict(self.draft)
                    if conflict:
                        return conflict
                    return self._remember(await self.agent.run_intent(
                        self.draft, auto_submit=self.auto_submit,
                        location_override=self.selected_location))
            if self.pending_choices and ((line.isdecimal() and not year_reply) or any(
                    str(item.get("name", "")).casefold().startswith(line.casefold())
                    for item in self.pending_choices)):
                return self._choices_text(self.pending_choices)
            refers_back = bool(re.search(r"\b(that|this|last|previous|uploaded|fetched|it)\b",
                                         line, re.IGNORECASE))
            future_request = bool(re.search(r"\b(future|baseline|morph|climate)\b",
                                            line, re.IGNORECASE))
            explicit_id = bool(re.search(r"\b[0-9a-f]{32}\b", line, re.IGNORECASE))
            baseline = (self.selected_baseline_id if future_request and not explicit_id
                        else None)
            if (baseline is None and future_request and refers_back
                    and len(self.weather_artifacts) == 1 and not explicit_id):
                baseline = self.weather_artifacts[0]
            delta = self._given_delta or self.model.parse(line)
            intent = self._merge(delta)
            if intent.kind == "future":
                return self._block_future()
            if delta.action == "explore" or (self._given_delta is None and re.search(
                r"\bwhat do you have\b|\bwhat(?:'s| is) available\b|"
                r"\bwhich sources\b|\byou tell me\b|\brecommend\b",
                line, re.IGNORECASE)):
                return await self._explore(intent)
            if self.pending_choices and self.selected_location is None:
                self.pending_exploration = False
                return self._choices_text(self.pending_choices)
            conflict = self._product_year_conflict(intent)
            if conflict:
                return conflict
            if (self.reviewed_reply and intent == self.reviewed_intent
                    and self.selected_location == self.reviewed_location):
                return self.reviewed_reply
            self.pending_exploration = False
            result = await self.agent.run_intent(
                intent, auto_submit=self.auto_submit, baseline_override=baseline,
                location_override=self.selected_location)
            return self._remember(result)
        except (MCPToolFailure, ModelUnavailable, OSError, ValueError) as error:
            if isinstance(error, MCPToolFailure):
                return f"[{error.code}] {error}"
            if isinstance(error, ModelUnavailable):
                return f"[model unavailable] {error}"
            return f"[local error] {error}"

    async def _command(self, line: str) -> str:
        command, _, argument = line.partition(" ")
        argument = argument.strip()
        if command in ("/quit", "/exit"):
            self.exit_requested = True
            return "Session ended. Jobs and artifacts remain in the data root."
        if command == "/help":
            return (
                "Type a weather request; short clarification replies fill the current draft.\n"
                "Ask 'what do you have?' for read-only catalog options. New plans execute automatically.\n"
                "/auto off|on  /submit  /status [job_id]  /cancel  /retry\n"
                "/upload <EPW path>  /inspect [id|last]\n"
                "Ask to visualize monthly, annual, hourly, histogram, or spatial "
                "weather from completed EPWs.\n"
                "/save <id|last> <path>  /reset  /quit\n"
                "Ctrl+C exits the console and requests cancellation of an active job.\n"
                "EPW bytes stay outside model prompts; inspect QC before simulation."
            )
        if command == "/reset":
            self.draft = None
            self.pending_choices = ()
            self.selected_location = None
            self.pending_question = None
            self.pending_view_active = False
            self.pending_view_family = None
            self.pending_view_options = ()
            self.pending_exploration = False
            self.reviewed_intent = None
            self.reviewed_reply = None
            return "Current draft cleared. Start a new weather request."
        if command == "/auto":
            if argument not in ("on", "off"):
                return "Use /auto on or /auto off."
            self.auto_submit = argument == "on"
            return "Automatic submission on." if self.auto_submit else "Plan review is manual."
        if command == "/submit":
            if not self.agent.plan_hash:
                return "No plan is ready for submission."
            detail = await self.mcp.call("plan_inspect", plan_hash=self.agent.plan_hash)
            kind = detail.get("kind")
            if kind == "future":
                return self._block_future()
            if kind != "weather":
                return "Stored plan kind is unavailable; submission stopped."
            return self._remember(await self.agent.submit_plan(kind))
        if command in ("/status", "/resume"):
            saved_plan, saved_job = self.agent.plan_hash, self.agent.job_id
            try:
                result = await self.agent.resume(argument or None)
            finally:
                if self.draft is not None:
                    self.agent.plan_hash, self.agent.job_id = saved_plan, saved_job
                    self.agent._persist()
            return self._remember(result, update_request=False)
        if command == "/cancel":
            if not self.agent.job_id:
                return "No job is selected."
            job = await self.mcp.call("job_cancel", job_id=self.agent.job_id)
            return ("Cancellation requested; completed outputs remain available."
                    if job.get("cancellation_requested") else
                    f"Job is already {job.get('state', 'finished')}.")
        if command == "/retry":
            if not self.agent.job_id:
                return "No job is selected."
            # The server confirms a retry against the original job's reviewed plan; asking
            # for /retry is the person's approval of that plan.
            original = await self.mcp.call("job_inspect", job_id=self.agent.job_id)
            approve = getattr(self.mcp, "approve", None)
            if callable(approve) and original.get("plan_hash"):
                approve(original["plan_hash"])
            retried = await self.mcp.call("job_retry_failed", job_id=self.agent.job_id)
            saved_plan, saved_job = self.agent.plan_hash, self.agent.job_id
            try:
                result = await self.agent.resume(retried["id"])
            finally:
                if self.draft is not None:
                    self.agent.plan_hash, self.agent.job_id = saved_plan, saved_job
                    self.agent._persist()
            return self._remember(result, update_request=False)
        if command == "/upload":
            if not argument:
                return "Use /upload <EPW path>."
            self.selected_baseline_id = await self.mcp.upload_file(self._unquote(argument))
            return ("Uploaded EPW artifact: " +
                    self.selected_baseline_id)
        if command == "/baseline":
            return "FEATURE_SUSPENDED: Future-weather MCP workflows are temporarily unavailable."
        if command == "/inspect":
            artifact_id = argument if argument and argument != "last" else self._last_artifact()
            if not artifact_id:
                return "No single EPW is selected; provide an artifact ID."
            inspected = await self.mcp.call("artifact_inspect", artifact_id=artifact_id)
            return (f"Artifact {artifact_id}: role={inspected.get('role')}, "
                    f"bytes={inspected.get('bytes')}, sha256={inspected.get('sha256')}, "
                    f"simulation_ready={inspected.get('simulation_ready')}, "
                    f"QC={inspected.get('qc_issue_codes', [])}.")
        if command == "/save":
            first, _, destination = argument.partition(" ")
            if not first or not destination:
                return "Use /save <artifact_id|last> <output path>."
            save_id = self._last_artifact() if first == "last" else first
            if not save_id:
                return "No single EPW is selected; provide an artifact ID."
            inspected = await self.mcp.call("artifact_inspect", artifact_id=save_id)
            if inspected.get("role") != "weather":
                return "Only EPW weather artifacts can be saved with /save."
            target = Path(self._unquote(destination)).expanduser()
            data = await self.mcp.read_artifact(save_id)
            with target.open("xb") as output:
                output.write(data)
            return f"EPW saved to {target}. Inspect QC before simulation."
        return "Unknown command. Type /help for available commands."
