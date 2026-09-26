"""Checkpointed conversation orchestration over the existing MCP reference agent."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Protocol, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

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
        builder.add_node("extract", self._extract)
        builder.add_node("respond", self._respond)
        builder.add_edge(START, "extract")
        builder.add_edge("extract", "respond")
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
            await self._graph.ainvoke({"turn_id": uuid.uuid4().hex}, self._config())
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
                                  "[no_executable_output]", "[blocked]"))

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
