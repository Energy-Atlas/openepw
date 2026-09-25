"""Small local conversation layer over the reference MCP agent."""

from __future__ import annotations

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
        self.draft: AgentIntent | None = None
        self.selected_location: dict[str, Any] | None = None
        self.pending_choices: tuple[dict[str, Any], ...] = ()
        self.pending_exploration = False
        self.pending_question: str | None = None
        self.reviewed_intent: AgentIntent | None = None
        self.reviewed_location: dict[str, Any] | None = None
        self.reviewed_reply: str | None = None
        self.tracer = tracer

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

    def _remember(self, result: AgentResult) -> str:
        if result.artifact_ids:
            self.weather_artifacts = result.artifact_ids
        self.pending_choices = result.location_choices
        self.pending_question = (result.message if result.status == "needs_clarification"
                                 else None)
        if result.status == "review_required" and self.draft is not None:
            self.reviewed_intent = self.draft.model_copy(deep=True)
            self.reviewed_location = self.selected_location.copy() if self.selected_location else None
            self.reviewed_reply = self._format(result)
        if result.status in ("completed", "partially_completed"):
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
        return ("Historical/AMY use actual years; TMY/TMYx/published are reference "
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
                    f"weather for {years}. Choose historical/AMY for {years}, or "
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
            return ("Weather choices include historical/AMY actual years and "
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
            geocode = await self.mcp.call("weather_geocode", query=intent.place)
            choices = tuple(geocode.get("candidates", [])[:10])
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
            return ("Historical/AMY require an actual year; TMY/TMYx/published are "
                    "reference products without an actual-year request. Which year do you need?")
        lines = ["Catalog support only means retrieval is eligible to try; weather quality "
                 "and simulation readiness require QC."]
        for product in ("historical", "amy", "tmy", "tmyx", "published"):
            request: dict[str, Any] = {"locations": location, "product": product}
            if product in ("historical", "amy"):
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

    @staticmethod
    def _unquote(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]
        return value

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
            choice_match = (re.fullmatch(
                r"(?:(?:location|option|choice)\s+)?(\d+)\b(?:\s*[,;:]\s*|\s+)?(.*)",
                line, re.IGNORECASE) if self.pending_choices else None)
            choice: dict[str, Any] | None
            if choice_match:
                index = int(choice_match.group(1))
                if not 1 <= index <= len(self.pending_choices):
                    return self._choices_text(self.pending_choices)
                choice = self.pending_choices[index - 1]
                remainder = choice_match.group(2).strip()
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
                    conflict = self._product_year_conflict(self.draft)
                    if conflict:
                        return conflict
                    return self._remember(await self.agent.run_intent(
                        self.draft, auto_submit=self.auto_submit,
                        location_override=self.selected_location))
            if self.pending_choices and (line.isdecimal() or any(
                    str(item.get("name", "")).casefold().startswith(line.casefold())
                    for item in self.pending_choices)):
                return self._choices_text(self.pending_choices)
            refers_back = bool(re.search(r"\b(that|this|last|previous|uploaded|fetched|it)\b",
                                         line, re.IGNORECASE))
            future_request = bool(re.search(r"\b(future|baseline|morph|climate)\b",
                                            line, re.IGNORECASE))
            if (refers_back and future_request and len(self.weather_artifacts) > 1
                    and not self.selected_baseline_id):
                return "Several EPWs are available. Choose one with /baseline <artifact_id>."
            explicit_id = bool(re.search(r"\b[0-9a-f]{32}\b", line, re.IGNORECASE))
            baseline = (self.selected_baseline_id if future_request and not explicit_id
                        else None)
            if (baseline is None and future_request and refers_back
                    and len(self.weather_artifacts) == 1 and not explicit_id):
                baseline = self.weather_artifacts[0]
            delta = self.model.parse(line)
            intent = self._merge(delta)
            if delta.action == "explore" or re.search(
                    r"\bwhat do you have\b|\bwhat(?:'s| is) available\b|"
                    r"\bwhich sources\b|\byou tell me\b|\brecommend\b",
                    line, re.IGNORECASE):
                return await self._explore(intent)
            if self.pending_choices and self.selected_location is None:
                self.pending_exploration = False
                return self._choices_text(self.pending_choices)
            conflict = self._product_year_conflict(intent)
            if conflict:
                return conflict
            if (intent.kind == "weather" and intent.years and
                    delta.product is None and intent.product == "historical"):
                interpretation = "Interpreting the requested actual year as historical weather. "
            else:
                interpretation = ""
            if (self.reviewed_reply and intent == self.reviewed_intent
                    and self.selected_location == self.reviewed_location):
                return self.reviewed_reply
            result = await self.agent.run_intent(
                intent, auto_submit=self.auto_submit, baseline_override=baseline,
                location_override=self.selected_location)
            if interpretation and result.status not in ("needs_clarification", "blocked"):
                result.message = interpretation + result.message
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
                "Type a weather or future request; short clarification replies fill the current draft.\n"
                "Ask 'what do you have?' for read-only catalog options. New plans execute automatically.\n"
                "/auto off|on  /submit  /status [job_id]  /cancel  /retry\n"
                "/upload <EPW path>  /baseline <artifact_id>  /inspect [id|last]\n"
                "/save <id|last> <path>  /reset  /quit\n"
                "EPW bytes stay outside model prompts; inspect QC before simulation."
            )
        if command == "/reset":
            self.draft = None
            self.pending_choices = ()
            self.selected_location = None
            self.pending_question = None
            self.pending_exploration = False
            self.reviewed_intent = None
            self.reviewed_reply = None
            return "Current draft cleared. Start a new weather or future request."
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
            if kind not in ("weather", "future"):
                return "Stored plan kind is unavailable; submission stopped."
            return self._remember(await self.agent.submit_plan(kind))
        if command in ("/status", "/resume"):
            return self._remember(await self.agent.resume(argument or None))
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
            retried = await self.mcp.call("job_retry_failed", job_id=self.agent.job_id)
            return self._remember(await self.agent.resume(retried["id"]))
        if command == "/upload":
            if not argument:
                return "Use /upload <EPW path>."
            self.selected_baseline_id = await self.mcp.upload_file(self._unquote(argument))
            return ("Uploaded and selected baseline artifact: " +
                    self.selected_baseline_id)
        if command == "/baseline":
            if not argument:
                return "Use /baseline <EPW artifact ID>."
            selected_id = argument.strip()
            inspected = await self.mcp.call("artifact_inspect", artifact_id=selected_id)
            if inspected.get("role") != "weather":
                return "Selected artifact is not an EPW."
            self.selected_baseline_id = selected_id
            return "Selected baseline artifact: " + selected_id
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
