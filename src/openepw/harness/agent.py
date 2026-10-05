"""A small reference agent driven only by the public MCP tool contract."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from .mcp_client import MCPToolFailure


class AgentIntent(BaseModel):
    kind: Literal["weather", "future", "unknown"]
    action: Literal["retrieve", "explore"] = "retrieve"
    place: str | None = None
    locations: list[dict[str, float | str]] | None = None
    lat: float | None = None
    lon: float | None = None
    product: Literal["historical", "amy", "tmy", "tmyx", "published"] | None = None
    years: list[int] = Field(default_factory=list)
    start: str | None = None
    end: str | None = None
    provider: str | None = None
    product_id: str | None = None
    missing_policy: Literal["warn", "error"] = "warn"
    baseline_artifact_id: str | None = None
    signals_artifact_id: str | None = None
    method: Literal["morph", "climate_profile"] | None = None
    climate_scenario: Literal["ssp126", "ssp245", "ssp370", "ssp585",
                              "rcp45", "rcp85"] | None = None
    climate_period: tuple[int, int] | None = None
    reference_period: tuple[int, int] | None = None

    @field_validator("product", mode="before")
    @classmethod
    def actual_year_alias(cls, value):
        # Existing prompts and checkpoints may say AMY; the console has one
        # actual-year product, with historical as its stable request value.
        return "historical" if value == "amy" else value


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
    location_choices: tuple[dict[str, Any], ...] = ()


def _batch_row_label(row: dict[str, Any]) -> str:
    index = row.get("occurrence_index")
    location = f"location {index + 1}" if isinstance(index, int) else None
    start = row.get("period_start")
    end = row.get("period_end")
    if start:
        start, end = str(start), str(end) if end else None
        if (end and start.endswith("-01-01") and end.endswith("-12-31")
                and start[:4] == end[:4]):
            period = start[:4]
        else:
            period = f"{start}–{end}" if end else start
        return f"{location}, {period}" if location else period
    return location or "output"


def safe_prompt(text: str, *, limit: int = 1000) -> str:
    """Remove credential assignments and absolute paths before model input."""
    text = re.sub(
        r"(?i)\b(?:[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)|"
        r"api[_-]?key|bearer[_-]?token|access[_-]?token|secret|password)"
        r"[\"']?\s*[=:]\s*[\"']?\S+|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}\b",
        "[redacted]", text,
    )
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:home|Users)/[^\s]+",
                  "[local path]", text)
    return text[:limit]


class ReferenceAgent:
    def __init__(self, mcp: MCPPort, model: IntentParser, *,
                 record_path: str | Path | None = None,
                 on_progress: Callable[[dict[str, Any]], None] | None = None,
                 stream_jobs: bool = False):
        self.mcp = mcp
        self.model = model
        self.record_path = Path(record_path) if record_path else None
        self.conversation_id = uuid.uuid4().hex
        self.events: list[dict[str, Any]] = []
        self.plan_hash: str | None = None
        self.job_id: str | None = None
        self.on_progress = on_progress
        self.stream_jobs = stream_jobs

    @classmethod
    def restore(cls, mcp: MCPPort, model: IntentParser, record_path: str | Path, *,
                on_progress: Callable[[dict[str, Any]], None] | None = None,
                stream_jobs: bool = False):
        """Resume from safe local IDs; canonical job facts are re-read from MCP."""
        agent = cls(mcp, model, record_path=record_path,
                    on_progress=on_progress, stream_jobs=stream_jobs)
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
        temporary = self.record_path.with_name(".tmp-" + uuid.uuid4().hex)
        try:
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temporary.replace(self.record_path)
        finally:
            temporary.unlink(missing_ok=True)

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

    async def geocode_candidates(self, place: str) -> list[dict[str, Any]]:
        """Retry a bare city/state abbreviation in the provider's accepted form."""
        result = await self._call("weather_geocode", query=place)
        candidates = result.get("candidates", [])
        if not candidates:
            match = re.fullmatch(r"\s*(.+?)[\s,]+([A-Za-z]{2})\s*", place)
            if match:
                normalized = f"{match.group(1).rstrip(', ')}, {match.group(2).upper()}"
                if normalized != place:
                    result = await self._call("weather_geocode", query=normalized)
                    candidates = result.get("candidates", [])
        return candidates

    async def run(self, prompt: str, *, auto_submit: bool = False,
                  baseline_override: str | None = None) -> AgentResult:
        intent = self.model.parse(safe_prompt(prompt))
        return await self.run_intent(intent, auto_submit=auto_submit,
                                     baseline_override=baseline_override)

    async def run_intent(self, intent: AgentIntent, *, auto_submit: bool = False,
                         baseline_override: str | None = None,
                         location_override: dict[str, Any] | None = None) -> AgentResult:
        intent = intent.model_copy(deep=True)
        if baseline_override:
            intent.baseline_artifact_id = baseline_override
        if intent.kind == "unknown":
            return AgentResult("needs_clarification",
                               "Please specify actual-year or published weather.")
        if intent.kind == "future":
            return AgentResult("blocked", "FEATURE_SUSPENDED: Future-weather MCP "
                               "workflows are temporarily unavailable.")
        try:
            return await self._weather(intent, auto_submit, location_override)
        except MCPToolFailure as error:
            return AgentResult("blocked", f"{error.code}: {error}",
                               self.plan_hash, self.job_id)

    async def _weather(self, intent: AgentIntent, auto_submit: bool,
                       location_override: dict[str, Any] | None) -> AgentResult:
        if intent.product is None:
            return AgentResult("needs_clarification", "Which weather product do you need?")
        if intent.product in ("historical", "amy") and not (intent.years or intent.start):
            return AgentResult("needs_clarification", "Which actual year or dates do you need?")
        location: Any
        if location_override:
            location = location_override
        elif intent.locations:
            location = intent.locations
        elif intent.lat is None or intent.lon is None:
            if not intent.place:
                return AgentResult("needs_clarification", "Which location do you mean?")
            candidates = await self.geocode_candidates(intent.place)
            if not candidates:
                return AgentResult("needs_clarification",
                                   "No location matched. Give coordinates or a more specific place.")
            if len(candidates) != 1:
                shown = candidates[:10]
                names = "; ".join(
                    f"{index}. {candidate.get('name', 'unnamed')}"
                    for index, candidate in enumerate(shown, start=1))
                return AgentResult("needs_clarification",
                                   f"Choose a specific {intent.place} location: {names}",
                                   location_choices=tuple(shown))
            location = candidates[0]
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
            request["providers"] = [intent.provider.casefold()]
        if intent.product_id:
            request["product_id"] = intent.product_id
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
        candidate_sources = list(dict.fromkeys(
            candidate.get("source", {}).get("provider", "unknown")
            for candidate in discovery.get("candidates", [])[:10]
        ))
        if len(candidate_sources) > 1:
            assessment += " Source alternatives: " + ", ".join(candidate_sources) + "."
        if any(candidate.get("source", {}).get("provisional") or
               candidate.get("missing_fields")
               for candidate in discovery.get("candidates", [])):
            assessment += " Some discovered alternatives have provisional identity or missing coverage/fields."
        plan = await self._call("weather_plan", request=request)
        self.plan_hash = plan["plan_hash"]
        self._persist()
        detail = await self._call("plan_inspect", plan_hash=self.plan_hash)
        selected = detail.get("selected_candidates", [])
        if selected:
            source = selected[0].get("source", {})
            assessment += (f" Selected {source.get('provider', 'unknown')}/"
                           f"{source.get('dataset', 'unknown')}.")
            if selected[0].get("product_id"):
                assessment += f" Exact product {selected[0]['product_id']}."
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

    async def submit_plan(self, kind: Literal["weather", "future"], *,
                          preface: str = "") -> AgentResult:
        if kind == "future":
            return AgentResult("blocked", "FEATURE_SUSPENDED: Future-weather MCP "
                               "workflows are temporarily unavailable.")
        if not self.plan_hash:
            return AgentResult("needs_clarification", "No stored plan to submit.")
        approve = getattr(self.mcp, "approve", None)
        if callable(approve):
            approve(self.plan_hash)
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
        self._emit_progress(job)
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
        polls = 0
        while self.stream_jobs or polls < 40:
            if job.get("state") not in ("queued", "running"):
                break
            await asyncio.sleep(1.0 if self.stream_jobs else 0.25)
            job = await self._call("job_inspect", job_id=selected)
            self._emit_progress(job)
            polls += 1
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
            message += " Per-output outcomes: " + "; ".join(
                f"{_batch_row_label(row)} {row.get('status')}"
                + (f" ({', '.join(row['issue_codes'])})" if row.get("issue_codes") else "")
                for row in rows
            ) + ". Full mapping remains in the job manifest."
        return AgentResult(job.get("state", "unknown"), message, self.plan_hash,
                           selected, artifact_ids)

    def _emit_progress(self, job: dict[str, Any]) -> None:
        if self.on_progress is None:
            return
        self.on_progress({
            "job_id": str(job.get("id", self.job_id or "")),
            "state": str(job.get("state", "unknown")),
            "total": int(job.get("total") or 0),
            "completed": int(job.get("completed") or 0),
            "failed": int(job.get("failed") or 0),
        })
