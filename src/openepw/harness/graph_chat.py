"""Checkpointed conversation orchestration over the existing MCP reference agent."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Protocol, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ..models import OpenEPWError
from ..places.parse import apply_edit, classify_places, describe_place_set
from .agent import AgentIntent, ReferenceAgent, safe_prompt
from .chat import ChatSession
from .mcp_client import MCPToolFailure
from .model import ModelUnavailable
from .trace import ArtifactPort, LangSmithTrace


class TurnParser(Protocol):
    def parse_many(self, prompt: str) -> list[AgentIntent]: ...

    def parse(self, prompt: str) -> AgentIntent: ...


class GraphState(TypedDict, total=False):
    turn_id: str
    chat: dict[str, Any]
    intents: list[dict[str, Any]]
    waiting: list[dict[str, Any]]
    direct: bool
    # Place input: {"rows": [...]} for an editable preview, or {"set": draft} while a
    # descriptive set waits for clarification. "handled" ends the turn early.
    places: dict[str, Any]
    handled: bool


PREVIEW_LINES = 25


class GraphChatSession:
    """Use LangGraph checkpoints for facts; keep raw user text outside checkpoints."""

    def __init__(self, agent: ReferenceAgent, port: ArtifactPort,
                 parser: TurnParser, checkpoint_path: str | Path, *,
                 thread_id: str = "console", auto_submit: bool = True,
                 tracer: LangSmithTrace | None = None):
        self.agent = agent
        self.port = port
        self.parser = parser
        self.checkpoint_path = Path(checkpoint_path)
        self.thread_id = thread_id
        self.tracer = tracer
        self.chat = ChatSession(agent, port, parser, auto_submit=auto_submit)
        self._line = ""
        self._answer = ""
        self._forced: list[AgentIntent] | None = None
        self._graph: Any = None
        self._checkpoint_context: Any = None

    async def __aenter__(self) -> GraphChatSession:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_context = AsyncSqliteSaver.from_conn_string(str(self.checkpoint_path))
        checkpointer = await self._checkpoint_context.__aenter__()
        await checkpointer.setup()
        builder = StateGraph(GraphState)
        builder.add_node("gate", self._gate)
        builder.add_node("extract", self._extract)
        builder.add_node("think", self._think)
        builder.add_node("respond", self._respond)
        # gate answers pending place questions and list edits without the model; think
        # routes new place text to a preview or clarification before the normal flow.
        builder.add_edge(START, "gate")
        builder.add_conditional_edges("gate", lambda state: END if state.get("handled") else "extract")
        builder.add_edge("extract", "think")
        builder.add_conditional_edges("think", lambda state: END if state.get("handled") else "respond")
        builder.add_edge("respond", END)
        self._graph = builder.compile(checkpointer=checkpointer)
        saved = await self._graph.aget_state(self._config())
        if saved.values.get("chat"):
            self.chat.import_state(saved.values["chat"])
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self._checkpoint_context.__aexit__(exc_type, exc_value, traceback)
        self._graph = None

    def _config(self) -> dict[str, Any]:
        return {"configurable": {"thread_id": self.thread_id}}

    @property
    def draft(self) -> AgentIntent | None:
        return self.chat.draft

    @property
    def exit_requested(self) -> bool:
        return self.chat.exit_requested

    @property
    def auto_submit(self) -> bool:
        return self.chat.auto_submit

    @property
    def choices(self) -> tuple[dict[str, Any], ...]:
        return self.chat.pending_choices

    def menu(self) -> list[tuple[str, str]]:
        if self.chat.pending_view_family:
            return [("variable:" + key, label)
                    for key, label in self.chat.pending_view_options] + [("other", "Other…")]
        if self.chat.pending_view_active:
            return [("family:" + key, label) for key, label in (
                ("time_series", "Hourly time series"),
                ("monthly_series", "Monthly series"),
                ("annual_series", "Annual series"),
                ("histogram", "Histogram"),
                ("spatial", "Spatial comparison"))] + [("other", "Other…")]
        if self.chat.pending_choices:
            choices = [("location:" + str(item.get("id", index)),
                        str(item.get("name", "unnamed")))
                       for index, item in enumerate(self.chat.pending_choices, start=1)]
            return choices + [("other", "Other…")]
        if (self.chat.draft is not None and self.chat.draft.kind == "weather"
                and self.chat.draft.product is None and self.chat.pending_question
                and "product" in self.chat.pending_question.lower()):
            return [("product:" + value, label) for value, label in (
                ("historical", "Actual year (AMY)"),
                ("tmy", "TMY (reference year)"),
                ("tmyx", "TMYx (published reference)"),
                ("published", "Other published EPW"),
            )] + [("other", "Other…")]
        return []

    async def handle_choice(self, choice_id: str) -> str:
        if choice_id.startswith("family:") and any(
                value == choice_id for value, _ in self.menu()):
            return await self.handle(choice_id.partition(":")[2].replace("_", " "))
        if choice_id.startswith("variable:") and any(
                value == choice_id for value, _ in self.menu()):
            return await self.handle(choice_id.partition(":")[2])
        if choice_id.startswith("location:"):
            for index, item in enumerate(self.chat.pending_choices, start=1):
                if choice_id == "location:" + str(item.get("id", index)):
                    return await self.handle(str(index))
        if choice_id.startswith("product:") and any(
                value == choice_id for value, _ in self.menu()):
            product = choice_id.partition(":")[2]
            self._forced = [AgentIntent(kind="unknown", product=product)]
            return await self.handle(product)
        raise ValueError("Choice is no longer available")

    async def handle(self, line: str) -> str:
        if self._graph is None:
            raise RuntimeError("Open GraphChatSession with async with first")
        if not line.strip():
            return ""
        if self.tracer:
            return await self.tracer.run_turn(line, self._handle)
        return await self._handle(line)

    async def _handle(self, line: str) -> str:
        self._line = line.strip()
        self._answer = ""
        try:
            await self._graph.ainvoke({"turn_id": uuid.uuid4().hex, "handled": False}, self._config())
            return self._answer
        except ModelUnavailable as error:
            return f"[model unavailable] {error}"
        except MCPToolFailure as error:
            return f"[{error.code}] {error}"
        finally:
            self._line = ""
            self._forced = None

    def _is_direct(self) -> bool:
        line = self._line
        if line.startswith("/"):
            return True
        if self.chat.pending_view_active or self.chat.is_view_request(line):
            return True
        if self.chat.pending_choices and re.fullmatch(r"(?:18|19|20|21)\d{2}", line):
            return False
        if self.chat.pending_choices and (line.isdecimal() or
                self.chat._choice(line) is not None or
                re.search(r"\b(?:location|option|choice)\s+\d+\b", line, re.I)):
            return bool(re.fullmatch(r"\d+", line) or self.chat._choice(line))
        if re.fullmatch(r"(?:what(?:'s| is)\s+)?(?:my\s+)?(?:download\s+)?"
                        r"(?:status|progress|downloaded\s+file|file|epw)\??", line, re.I):
            return True
        if self.agent.job_id and line.casefold().rstrip(".!?") in (
                "ok", "okay", "thanks", "thank you"):
            return True
        return False

    async def _extract(self, state: GraphState) -> GraphState:
        direct = False
        if self._forced is not None:
            intents = self._forced
        elif self._is_direct():
            intents = []
            direct = True
        else:
            if len(self._line) > 4000:
                raise ModelUnavailable("Message is too long; split it into shorter requests")
            run = (self.tracer.start_step("openepw.intent", "llm", {})
                   if self.tracer else None)
            try:
                intents = self.parser.parse_many(safe_prompt(self._line, limit=4000))
                intents = [self._ground_weather_time(intent, self._line)
                           for intent in intents]
            except Exception as error:
                if self.tracer:
                    self.tracer.end_step(run, error=type(error).__name__)
                raise
            if self.tracer:
                self.tracer.end_step(run, outputs={
                    "request_count": len(intents),
                    "kinds": [intent.kind for intent in intents],
                    "products": [intent.product for intent in intents if intent.product],
                })
        return {"intents": [item.model_dump(mode="json") for item in intents],
                "direct": direct}

    def _apply_preview(self, preview: dict[str, Any]) -> list[dict[str, Any]]:
        """Put previewed points into the draft; return the rows kept for text edits."""
        rows = preview.get("rows", [])
        locations = [{"lat": row["lat"], "lon": row["lon"], "name": row["name"]}
                     for row in rows if row.get("status") == "resolved"]
        if locations:
            self.chat._merge(AgentIntent(kind="weather", locations=locations))
            self.chat.draft.place = None
            self.chat.draft.lat = self.chat.draft.lon = None
        self.chat.pending_choices = ()
        self.chat.selected_location = None
        return rows

    @staticmethod
    def _preview_text(preview: dict[str, Any]) -> str:
        rows = preview.get("rows", [])
        lines = [f"Previewed {preview.get('resolved', 0)} of {len(rows)} places. Fix anything by text, "
                 "for example 'replace 2 with Portland, Oregon', 'remove 3' or 'add Reno'."]
        for row in rows[:PREVIEW_LINES]:
            if row.get("status") != "resolved":
                lines.append(f"{row['index']}. '{row['input']}' not found; replace or remove it")
                continue
            detail = f" ({row['lat']:.4f}, {row['lon']:.4f})" if row.get("source") != "coordinates" else ""
            note = (f"; top of {row['candidate_count']} matches, check it" if row.get("ambiguous") else "")
            population = f"; population {row['population']:,}" if row.get("population") else ""
            lines.append(f"{row['index']}. {row['name']}{detail}{population}{note}")
        if len(rows) > PREVIEW_LINES:
            lines.append(f"... and {len(rows) - PREVIEW_LINES} more")
        lines.extend(preview.get("attribution", []))
        return "\n".join(lines)

    @staticmethod
    def _questions_text(result: dict[str, Any]) -> str:
        lines = ["Before listing those places I need a few details:"]
        for question in result.get("questions", []):
            options = [option.get("label") or next((f"{value:,}" if isinstance(value, int) else str(value))
                                                    for value in option.values() if value is not None)
                       for option in question.get("options", [])]
            choices = ("; ".join(f"{index}. {label}" for index, label in enumerate(options, start=1))
                       if options else "")
            lines.append(f"- {question['prompt']}" + (f" Options: {choices}." if choices else ""))
        return "\n".join(lines)

    async def _preview_places(self, places: dict[str, Any], preview: dict[str, Any]) -> GraphState:
        rows = self._apply_preview(preview)
        self._answer = self._preview_text(preview)
        return {"places": {"rows": rows}, "handled": True, "chat": self.chat.export_state()}

    async def _gate(self, state: GraphState) -> GraphState:
        """Answer a pending place-set question or apply a list edit without the model."""
        places = dict(state.get("places") or {})
        if self._line == "/reset":
            return {"places": {}, "handled": False}
        if self._forced is not None or self._line.startswith("/"):
            return {"handled": False}
        if state.get("chat"):
            self.chat.import_state(state["chat"])
        if places.get("set"):
            result = await self.agent.mcp.call("weather_places_interpret", text=self._line,
                                               draft=places["set"])
            if result.get("questions"):
                self._answer = self._questions_text(result)
                return {"places": {"set": result["draft"]}, "handled": True}
            preview = await self.agent.mcp.call("weather_place_set", query=result["query"])
            return await self._preview_places(places, preview)
        if places.get("rows"):
            rows = places["rows"]
            labels = [row.get("name") or row["input"] for row in rows]
            try:
                edited = apply_edit(labels, self._line)
            except OpenEPWError as error:
                self._answer = error.issue.message
                return {"handled": True}
            if edited is not None:
                if not edited:
                    self._answer = "The place list is now empty; give places or coordinates."
                    return {"places": {}, "handled": True}
                # Unchanged rows go back pinned so they are never re-geocoded; new text is resolved.
                by_label = {label: row for label, row in zip(labels, rows)}
                items = [by_label.get(label, label) for label in edited]
                preview = await self.agent.mcp.call("weather_places_preview", places=items)
                return await self._preview_places(places, preview)
        return {"handled": False}

    async def _think(self, state: GraphState) -> GraphState:
        """Route new place text: lists and coordinates preview, sets ask, one name continues."""
        if state.get("direct") or self._forced is not None:
            return {}
        intents = [AgentIntent.model_validate(item) for item in state.get("intents", [])]
        target = next((intent for intent in intents if intent.kind != "future" and intent.place), None)
        text = target.place if target else (self._line if describe_place_set(self._line) else None)
        if not text:
            return {}
        # Route locally first so a single place keeps the existing choice flow unchanged.
        try:
            local = classify_places(text)
        except OpenEPWError:
            local = {"kind": "invalid"}
        if local["kind"] == "single" or (local["kind"] == "coordinates" and len(local["points"]) == 1):
            return {}
        result = await self.agent.mcp.call("weather_places_interpret", text=text)
        kind = result.get("kind")
        if kind == "single" or (kind == "coordinates" and len(result.get("points", [])) == 1):
            return {}
        if state.get("chat"):
            self.chat.import_state(state["chat"])
        if target is not None:
            # Keep product, years and other facts from the same message.
            self.chat._merge(target.model_copy(update={"place": None, "kind": "weather"}))
        rest = [intent.model_dump(mode="json") for intent in intents if intent is not target]
        common = {"intents": [], "waiting": list(state.get("waiting", [])) + rest, "handled": True}
        if kind == "invalid":
            self._answer = result["issue"]["message"]
            return common | {"chat": self.chat.export_state()}
        if kind == "descriptive":
            if result.get("questions"):
                self._answer = self._questions_text(result)
                return common | {"places": {"set": result["draft"]}, "chat": self.chat.export_state()}
            preview = await self.agent.mcp.call("weather_place_set", query=result["query"])
        else:
            items = (result.get("items") if kind == "list" else
                     [f"{lat}, {lon}" for lat, lon in result.get("points", [])])
            preview = await self.agent.mcp.call("weather_places_preview", places=items)
        return common | await self._preview_places({}, preview)

    @staticmethod
    def _ground_weather_time(intent: AgentIntent, line: str) -> AgentIntent:
        """Do not let model-only years or dates initiate provider retrieval."""
        explicit = set()
        for match in re.finditer(r"\b(?:18|19|20|21)\d{2}\b", line):
            if not re.match(r"\s+buildings?\b", line[match.end():], re.I):
                explicit.add(int(match.group()))
        for match in re.finditer(
                r"\b((?:18|19|20|21)\d{2})\s*(?:-|–|—|to|through)\s*"
                r"((?:18|19|20|21)\d{2})\b", line, re.I):
            start, end = int(match.group(1)), int(match.group(2))
            if 0 <= end - start <= 100:
                explicit.update(range(start, end + 1))
        grounded = intent.model_copy(deep=True)
        grounded.years = [year for year in intent.years if year in explicit]
        if grounded.start and not any(grounded.start.startswith(str(year))
                                     for year in explicit):
            grounded.start = None
        if grounded.end and not any(grounded.end.startswith(str(year))
                                   for year in explicit):
            grounded.end = None
        product_evidence = {
            "historical": bool(explicit or re.search(
                r"\b(?:historical|amy|actual.year)\b", line, re.I)),
            "tmy": bool(re.search(
                r"\b(?:tmy|typical (?:meteorological )?(?:weather )?year)\b",
                line, re.I)),
            "tmyx": bool(re.search(r"\btmyx\b", line, re.I)),
            "published": bool(re.search(r"\bpublished\b", line, re.I)),
        }
        if grounded.product and not product_evidence.get(grounded.product, False):
            grounded.product = None
        return grounded

    async def _respond(self, state: GraphState) -> GraphState:
        if state.get("chat"):
            self.chat.import_state(state["chat"])
        waiting = [AgentIntent.model_validate(item) for item in state.get("waiting", [])]
        intents = [AgentIntent.model_validate(item) for item in state.get("intents", [])]
        answers: list[str] = []
        if not intents:
            answer = (await self.chat.handle(self._line) if state.get("direct") else
                      await self.chat.handle_intent("request", AgentIntent(kind="unknown")))
            answers.append(answer)
            if self._line == "/reset":
                waiting = []
            elif self._finished(answer) and waiting:
                answers.extend(await self._drain(waiting))
        else:
            # The current reply fills the active draft before queued requests run.
            first, *rest = intents
            if re.search(r"\bmy\s+(?:download|job)\s+(?:status|progress)\b",
                         self._line, re.I):
                answers.append(await self.chat.handle("/status"))
            if re.search(r"\bmy\s+(?:downloaded\s+)?(?:file|epw)\b",
                         self._line, re.I):
                answers.append(await self.chat.handle("/inspect last"))
            if (first.kind == "weather" and self._refers_to_prior_location(self._line)):
                first = self._with_last_location(first)
            if (first.kind == "future" and not first.baseline_artifact_id and
                    re.search(r"\b(that|this|last|previous|uploaded|fetched|it)\b",
                              self._line, re.I)):
                baseline = self.chat.selected_baseline_id
                if baseline is None and len(self.chat.weather_artifacts) == 1:
                    baseline = self.chat.weather_artifacts[0]
                if baseline:
                    first = first.model_copy(update={"baseline_artifact_id": baseline})
            synthetic = self._line if self.chat.pending_choices else "request"
            answer = await self.chat.handle_intent(synthetic, first)
            answers.append(answer)
            if self._finished(answer):
                if waiting:
                    answers.extend(await self._drain(waiting))
                rest_list = list(rest)
                answers.extend(await self._drain(rest_list))
                waiting.extend(rest_list)
            else:
                waiting.extend(rest)
        self._answer = "\n".join(answer for answer in answers if answer)
        return {"chat": self.chat.export_state(),
                "waiting": [item.model_dump(mode="json") for item in waiting],
                "intents": []}

    @staticmethod
    def _finished(answer: str) -> bool:
        return answer.startswith(("[completed]", "[partially_completed]",
                                  "[no_executable_output]", "[blocked]",
                                  "[visualization]", "[unsupported]"))

    @staticmethod
    def _refers_to_prior_location(line: str) -> bool:
        return bool(re.search(r"\b(?:same (?:place|location|city)|there)\b", line, re.I))

    def _with_last_location(self, intent: AgentIntent) -> AgentIntent:
        if (intent.place or intent.locations or intent.lat is not None or
                not self.chat.last_weather_location):
            return intent
        selected = self.chat.last_weather_location
        intent = intent.model_copy(deep=True)
        if "place" in selected:
            intent.place = str(selected["place"])
        elif "id" in selected:
            intent.locations = [selected]
        else:
            intent.lat = selected.get("lat")
            intent.lon = selected.get("lon")
        return intent

    async def _drain(self, pending: list[AgentIntent]) -> list[str]:
        replies: list[str] = []
        while pending:
            intent = self._with_last_location(pending[0])
            if (intent.kind == "future" and not intent.baseline_artifact_id
                    and len(self.chat.weather_artifacts) == 1):
                intent.baseline_artifact_id = self.chat.weather_artifacts[0]
            response = await self.chat.handle_intent("future that" if intent.kind == "future"
                                                     else "request", intent)
            replies.append(response)
            pending.pop(0)
            if not self._finished(response):
                break
        return replies
