"""A small reference agent driven only by the public MCP tool contract."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from .mcp_client import MCPToolFailure


class AgentIntent(BaseModel):
    kind: Literal["weather", "future", "unknown"]
    place: str | None = None
    lat: float | None = None
    lon: float | None = None
    product: Literal["historical", "amy", "tmy", "tmyx", "published"] | None = None
    years: list[int] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    provider: str | None = None
    missing_policy: Literal["warn", "error"] = "warn"
    baseline_artifact_id: str | None = None
    signals_artifact_id: str | None = None
    method: Literal["morph", "climate_profile"] | None = None
    climate_scenario: str | None = None
    climate_period: tuple[int, int] | None = None
    reference_period: tuple[int, int] | None = None


class IntentParser(Protocol):
    def parse(self, prompt: str) -> AgentIntent: ...


class MCPPort(Protocol):
    async def call(self, name: str, **arguments: Any) -> dict[str, Any]: ...


@dataclass
class AgentResult:
    status: str
    message: str
    plan_hash: str | None = None
    job_id: str | None = None
    artifact_ids: tuple[str, ...] = ()


def safe_prompt(text: str) -> str:
    """Remove credential assignments and absolute paths before model input."""
    text = re.sub(
        r"(?i)\b(?:OPENAI_API_KEY|LANGCHAIN_API_KEY|LANGSMITH_API_KEY|OPENEPW_[A-Z_]*KEY)"
        r"\s*[=:]\s*\S+|\bsk-[A-Za-z0-9_-]{8,}\b",
        "[redacted]", text,
    )
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:home|Users)/[^\s]+",
                  "[local path]", text)
    return text[:1000]


class ReferenceAgent:
    def __init__(self, mcp: MCPPort, model: IntentParser, *,
                 record_path: str | Path | None = None):
        self.mcp = mcp
        self.model = model
        self.record_path = Path(record_path) if record_path else None
        self.conversation_id = uuid.uuid4().hex
        self.events: list[dict[str, Any]] = []
        self.plan_hash: str | None = None
        self.job_id: str | None = None

    @classmethod
    def restore(cls, mcp: MCPPort, model: IntentParser, record_path: str | Path):
        """Resume from safe local IDs; canonical job facts are re-read from MCP."""
        agent = cls(mcp, model, record_path=record_path)
        raw = json.loads(Path(record_path).read_text(encoding="utf-8"))
        agent.conversation_id = raw["conversation_id"]
        agent.plan_hash = raw.get("plan_hash")
        agent.job_id = raw.get("job_id")
        agent.events = raw.get("events", [])
        return agent

    def _persist(self):
        if self.record_path is None:
            return
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "conversation_id": self.conversation_id,
            "plan_hash": self.plan_hash,
            "job_id": self.job_id,
            "events": self.events[-100:],
        }
        temporary = self.record_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.record_path)

    async def _call(self, name: str, **arguments: Any) -> dict[str, Any]:
        result = await self.mcp.call(name, **arguments)
        # Persist only opaque IDs and tool names, never raw arguments or responses.
        fields = ("plan_hash", "job_id", "artifact_id")
        event = {"tool": name}
        event.update({key: arguments[key] for key in fields
                      if isinstance(arguments.get(key), str)})
        self.events.append(event)
        self._persist()
        return result

    async def run(self, prompt: str, *, auto_submit: bool = False,
                  baseline_override: str | None = None) -> AgentResult:
        intent = self.model.parse(safe_prompt(prompt))
        if baseline_override:
            intent.baseline_artifact_id = baseline_override
        if intent.kind == "unknown":
            return AgentResult("needs_clarification",
                               "Please specify historical/published weather or future weather.")
        try:
            if intent.kind == "weather":
                return await self._weather(intent, auto_submit)
            return await self._future(intent, auto_submit)
        except MCPToolFailure as error:
            return AgentResult("blocked", f"{error.code}: {error}",
                               self.plan_hash, self.job_id)

    async def _weather(self, intent: AgentIntent, auto_submit: bool) -> AgentResult:
        if intent.product is None:
            return AgentResult("needs_clarification", "Which weather product do you need?")
        if intent.product in ("historical", "amy") and not (intent.years or intent.start):
            return AgentResult("needs_clarification", "Which actual year or dates do you need?")
        if intent.lat is None or intent.lon is None:
            if not intent.place:
                return AgentResult("needs_clarification", "Which location do you mean?")
            geocode = await self._call("weather_geocode", query=intent.place)
            candidates = geocode.get("candidates", [])
            if len(candidates) != 1:
                names = ", ".join(c.get("name", "unnamed") for c in candidates[:5])
                return AgentResult("needs_clarification",
                                   f"Choose a specific {intent.place} location: {names}")
            location = {"lat": candidates[0]["lat"], "lon": candidates[0]["lon"]}
        else:
            location = {"lat": intent.lat, "lon": intent.lon}
        request: dict[str, Any] = {
            "locations": location, "product": intent.product,
            "missing_policy": intent.missing_policy,
        }
        if intent.years:
            request["years"] = intent.years
        if intent.start and intent.end:
            request.update({"start": intent.start, "end": intent.end})
        if intent.provider:
            request["providers"] = [intent.provider]
        discovery = await self._call("weather_discover", request=request)
        statuses = {
            option.get("eligibility", {}).get("status")
            for option in discovery.get("availability", {}).get("options", [])
        }
        assessment = ("Catalog support is eligible only to try retrieval; "
                      "retrieved quality requires QC.")
        if "unknown" in statuses:
            assessment += " Some availability is unknown."
        if "unsupported" in statuses or "excluded" in statuses:
            assessment += " Some alternatives are unsupported."
        plan = await self._call("weather_plan", request=request)
        self.plan_hash = plan["plan_hash"]
        self._persist()
        detail = await self._call("plan_inspect", plan_hash=self.plan_hash)
        selected = detail.get("selected_candidates", [])
        if selected:
            source = selected[0].get("source", {})
            assessment += (f" Selected {source.get('provider', 'unknown')}/"
                           f"{source.get('dataset', 'unknown')}.")
            reasons = selected[0].get("selection_reasons", [])
            if reasons:
                assessment += " Selection reasons: " + ", ".join(reasons[:3]) + "."
        if not plan.get("output_count"):
            return AgentResult("no_executable_output",
                               assessment + " The plan has no executable output.",
                               self.plan_hash)
        if not auto_submit:
            return AgentResult(
                "review_required",
                assessment + f" Review plan {self.plan_hash} and its "
                f"{plan.get('estimated_calls', 0)} estimated source calls before submission.",
                self.plan_hash,
            )
        return await self.submit_plan("weather", preface=assessment)

    async def _future(self, intent: AgentIntent, auto_submit: bool) -> AgentResult:
        if not intent.baseline_artifact_id:
            return AgentResult("needs_clarification",
                               "Provide an uploaded or fetched baseline artifact ID.")
        if not intent.method or not intent.climate_scenario or not intent.climate_period:
            return AgentResult("needs_clarification",
                               "Specify the future method, scenario and climate window.")
        request: dict[str, Any] = {
            "baseline": intent.baseline_artifact_id,
            "method": intent.method,
            "climate_scenario": intent.climate_scenario,
            "climate_period": list(intent.climate_period),
        }
        if intent.reference_period:
            request["reference_period"] = list(intent.reference_period)
        if intent.signals_artifact_id:
            request["signals"] = intent.signals_artifact_id
        plan = await self._call("future_plan", request=request)
        self.plan_hash = plan["plan_hash"]
        self._persist()
        baseline = plan.get("baseline_ref") or {}
        preface = (f"Future {intent.method} for {intent.climate_scenario} "
                   f"{intent.climate_period[0]}–{intent.climate_period[1]}; "
                   f"baseline origin {baseline.get('origin', 'unknown')}.")
        if not auto_submit:
            return AgentResult("review_required", preface +
                               f" Review plan {self.plan_hash} before submission.",
                               self.plan_hash)
        return await self.submit_plan("future", preface=preface)

    async def submit_plan(self, kind: Literal["weather", "future"], *,
                          preface: str = "") -> AgentResult:
        if not self.plan_hash:
            return AgentResult("needs_clarification", "No stored plan to submit.")
        job = await self._call(f"{kind}_submit", plan_hash=self.plan_hash)
        self.job_id = job["id"]
        self._persist()
        return await self.resume(preface=preface)

    async def resume(self, job_id: str | None = None, *, preface: str = "") -> AgentResult:
        selected = job_id or self.job_id
        if not selected:
            return AgentResult("needs_clarification", "Provide a job ID to resume.")
        self.job_id = selected
        job = await self._call("job_inspect", job_id=selected)
        if job.get("plan_hash"):
            self.plan_hash = job["plan_hash"]
        self._persist()
        if not preface and self.plan_hash:
            detail = await self._call("plan_inspect", plan_hash=self.plan_hash)
            if detail.get("kind") == "future":
                request = detail.get("request", {})
                baseline = detail.get("baseline_ref") or {}
                preface = (
                    f"Future {request.get('method', 'unknown')} "
                    f"{request.get('climate_scenario', 'unknown')} "
                    f"{request.get('climate_period', 'unknown')}; "
                    f"baseline origin {baseline.get('origin', 'unknown')}."
                )
            else:
                request = detail.get("request", {})
                preface = (f"Weather {request.get('product', 'unknown')} "
                           f"{request.get('years') or [request.get('start'), request.get('end')]}.")
        for _ in range(100):
            if job.get("state") not in ("queued", "running"):
                break
            await asyncio.sleep(0.1)
            job = await self._call("job_inspect", job_id=selected)
        if job.get("state") in ("queued", "running"):
            return AgentResult("running", f"Job {selected} is still running.",
                               self.plan_hash, selected)
        artifact_ids = tuple(job.get("artifacts", {}).get("weather", []))
        inspected = [await self._call("artifact_inspect", artifact_id=artifact_id)
                     for artifact_id in artifact_ids[:20]]
        issue_codes = {code for item in inspected for code in item.get("qc_issue_codes", [])}
        issue_codes.update(code for row in job.get("batch_rows", [])
                           for code in row.get("issue_codes", []))
        message = (preface + " " if preface else "")
        message += (f"Job {job.get('state')}: {job.get('completed', 0)} completed, "
                    f"{job.get('failed', 0)} failed; {len(artifact_ids)} EPW artifacts.")
        if not artifact_ids:
            message += " No EPW was emitted for failed outputs."
        if "MISSING_CRITICAL_VARIABLE" in issue_codes:
            message += " Data gap: missing sentinels and QC require review."
        if any(item.get("simulation_ready") is False for item in inspected):
            message += " simulation_ready=false."
        if job.get("batch_rows"):
            rows = job["batch_rows"][:10]
            message += " Per-occurrence outcomes: " + "; ".join(
                f"{row.get('occurrence_index')} {row.get('status')}"
                + (f" ({', '.join(row['issue_codes'])})" if row.get("issue_codes") else "")
                for row in rows
            ) + ". Full mapping remains in the job manifest."
        return AgentResult(job.get("state", "unknown"), message, self.plan_hash,
                           selected, artifact_ids)
