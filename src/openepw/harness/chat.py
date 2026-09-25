"""Small local conversation layer over the reference MCP agent."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .agent import AgentIntent, AgentResult, ReferenceAgent
from .mcp_client import MCPToolFailure, StdioMCPPort
from .model import ModelUnavailable, OpenAIIntentParser


def load_model_key(env_file: str | Path = ".env") -> str:
    """Use a shell key or read the existing .env; never write either source."""
    existing = os.environ.get("OPENAI_API_KEY", "").strip()
    if existing:
        return existing
    source = Path(env_file)
    if source.is_file():
        for line in source.read_text(encoding="utf-8-sig").splitlines():
            if re.match(r"^\s*OPENAI_API_KEY\s*=", line):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    raise ModelUnavailable("OPENAI_API_KEY is missing from the shell and .env")


class SessionParser:
    """Add only compact confirmed facts when resolving a follow-up reference."""

    def __init__(self, model: OpenAIIntentParser, session: ChatSession):
        self.model = model
        self.session = session
        self.last_intent: AgentIntent | None = None

    def parse(self, prompt: str) -> AgentIntent:
        context = self.session.confirmed_context()
        if context:
            prompt += ("\nPrior confirmed context for resolving references only; "
                       "the current request is the task: " +
                       json.dumps(context, separators=(",", ":")))
        intent = self.model.parse(prompt)
        self.last_intent = intent
        return intent


class ChatSession:
    """One terminal conversation; the MCP service remains the source of truth."""

    def __init__(self, agent: ReferenceAgent, mcp: StdioMCPPort,
                 model: OpenAIIntentParser, *, auto_submit: bool = True):
        self.agent = agent
        self.mcp = mcp
        self.parser = SessionParser(model, self)
        self.agent.model = self.parser
        self.auto_submit = auto_submit
        self.exit_requested = False
        self.selected_baseline_id: str | None = None
        self.weather_artifacts: tuple[str, ...] = ()
        self.last_intent: AgentIntent | None = None

    def confirmed_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {}
        if self.last_intent:
            allowed = ("kind", "place", "locations", "lat", "lon", "product",
                       "years", "start", "end", "provider", "product_id",
                       "method", "climate_scenario", "climate_period",
                       "reference_period")
            context["prior_choices"] = {
                key: value for key, value in self.last_intent.model_dump(mode="json").items()
                if key in allowed and value not in (None, [], "")
            }
        if self.selected_baseline_id:
            context["selected_baseline_artifact_id"] = self.selected_baseline_id
        if len(self.weather_artifacts) == 1:
            context["last_epw_artifact_id"] = self.weather_artifacts[0]
        elif self.weather_artifacts:
            context["last_epw_artifact_count"] = len(self.weather_artifacts)
        return context

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
        if result.status in ("review_required", "completed", "partially_completed"):
            if self.parser.last_intent is not None:
                self.last_intent = self.parser.last_intent
        if result.artifact_ids:
            self.weather_artifacts = result.artifact_ids
        return self._format(result)

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
        line = line.strip()
        if not line:
            return ""
        try:
            if line.startswith("/"):
                return await self._command(line)
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
            result = await self.agent.run(
                line, auto_submit=self.auto_submit, baseline_override=baseline)
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
                "Type a weather or future request. New plans execute automatically.\n"
                "/auto off|on  /submit  /status [job_id]  /cancel  /retry\n"
                "/upload <EPW path>  /baseline <artifact_id>  /inspect [id|last]\n"
                "/save <id|last> <path>  /quit\n"
                "EPW bytes stay outside model prompts; inspect QC before simulation."
            )
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
