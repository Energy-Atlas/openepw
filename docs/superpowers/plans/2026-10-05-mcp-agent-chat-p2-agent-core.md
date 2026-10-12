# MCP agent chat — P2 agent core, guided mode and CLI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Python agent core (`openepw.agent`) that is a genuine MCP client of the P1 server, shows renderer-neutral forms, enforces the host guard-rails, runs a rule-based **guided mode**, and is usable from a new `openepw chat` CLI — all offline-testable without a model.

**Architecture:** `AgentSession` keeps an SQLite event log and typed facts, talks to `create_server(service, runner=...)` through the MCP in-memory transport (`InProcessMCP`), and delegates decisions to a policy. P2 ships `GuidedPolicy` (rules); P3 adds a model policy with the same interface. Gates (`openepw.agent.gates`) decide the next required step and build plan requests from approved facts only (host substitution). The CLI renders every form as text.

**Tech Stack:** Python 3.11/3.13, pydantic v2, MCP Python SDK ≥1.30 (in-memory transport, elicitation callback), SQLite, pytest, ruff, mypy.

**Spec and decisions:** [design spec](../specs/2026-10-05-mcp-agent-chat-design.md) (§1 units, §2 modes, §3 forms and gates, §4 guided order, §6 tests); [ADR 0005](../../decisions/0005-mcp-agent-chat.md); [P1 plan](2026-10-05-mcp-agent-chat-p1-contract.md) and its "Execution notes" (deferred items P2 owns). P1 is merged into `feature/chat-ui` at `d32a449`.

**Pre-validation:** while writing this plan, all of its code was copied into a scratch copy of the repository at `d32a449` and run: the 45 tests in `tests/agent` passed, the existing chat tests still passed, and mypy was clean on `openepw.agent`. Treat the code as a strong starting point, not as already reviewed. TDD order, reviews and the full suite still apply.

## Global Constraints

- Work on branch `feature/mcp-agent-core` created from `feature/chat-ui` (see the handoff for the owner's override). Do not modify `main`, `deploy/staging`, `feature/account-login` or `feature/mcp-agent-chat`. Do not push unless the owner asks.
- Commit messages: `fix(topic): concise description`, normal configured human authorship, **no** agent or model co-author trailers (AGENTS.md).
- Python must run on 3.11 and 3.13; no 3.12-only syntax.
- `openepw.models`, `openepw.availability`, `openepw.planning`, `openepw.places` and `openepw.service` must not import FastAPI, MCP or xarray. `openepw.agent.text`, `.interactions`, `.state`, `.store` and `.gates` must not import MCP either (only `mcp_port`, `session`, `guided` and `cli` may).
- The agent calls the service **only through MCP tools**; it never imports `WeatherService` methods directly (the CLI builds the service, runner and server and hands the server to `InProcessMCP`).
- Guard-rails (spec §3): plans use only the user-approved location review (geography, offsets, sampling); products only from the user's product choice; actual-year years only from the user's text or a form; submission only after the user approves the plan review; each approval answers exactly one confirmation (one-shot); future weather stays suspended.
- Never claim `simulation_ready=true`; listed/supported means eligible to try retrieval.
- Keep EPW bytes out of logs and events (base64 goes only into the `epw_upload` call).
- Windows: run Python as `.venv/Scripts/python.exe` from the repo root.
- Known pre-existing failures (also on `main`): exactly 4 tests — 2 in `tests/unit/test_availability_adapters.py`, 2 in `tests/unit/test_availability_service.py` ("catalog-supported discovery called provider HTTP"); one pre-existing starlette/anyio `DeprecationWarning`. Report any other failure.

## Decisions this plan makes (owner may override; see handoff)

1. **Host substitution.** Plan requests are built by the host from approved facts (`gates.build_requests`), and a model-supplied request is checked and rewritten (`gates.check_plan_request`, used by P3). This replaces the deferred "review-key helper": the geography in a plan is always the canonical one returned by `weather_locations_review`, so keys match by construction.
2. **One-shot approvals.** `ApprovalBook.approve(plan_hash)` authorises exactly one `weather_submit` confirmation for that hash; it is consumed when the server asks.
3. **CLI.** A new `openepw chat` subcommand. The legacy `openepw-chat` console stays until P5.
4. **Scenarios as pytest.** P2's guided scenarios are pytest tests with explicit assertions; the reusable `openepw eval` runner (with live model runs) is built in P3.

## File structure

| File | Responsibility |
| --- | --- |
| `src/openepw/agent/__init__.py` | Package docstring only (no imports) |
| `src/openepw/agent/text.py` | Offline reading: written years, product words, the place part, future requests |
| `src/openepw/agent/interactions.py` | Forms (`Interaction`, `Option`), answers (`Answer`), conversation events (`Event`) |
| `src/openepw/agent/state.py` | `Facts` (approved and pending choices) and `SessionState` |
| `src/openepw/agent/store.py` | SQLite persistence: sessions, events, form snapshots for Back |
| `src/openepw/agent/gates.py` | `next_need`, `build_requests`, `check_plan_request`, `GateRequired` |
| `src/openepw/agent/mcp_port.py` | `InProcessMCP` client, `ToolResult`, `ToolFailure`, one-shot `ApprovalBook` |
| `src/openepw/agent/session.py` | `AgentSession`: inputs, forms, tool calls, Back, upload, job following |
| `src/openepw/agent/guided.py` | `GuidedPolicy`: rule-based reading and form order |
| `src/openepw/agent/cli.py` | Text rendering of events and forms; `main_chat` REPL |
| `src/openepw/cli/main.py` (modify) | `openepw chat` subcommand |
| `src/openepw/chat/coordinator.py` (modify) | Import `explicit_weather_years` from `openepw.agent.text` |
| `tests/agent/fakes.py` | Offline scenario service: fake geocoder, GeoNames files, ERA5-like provider |
| `tests/agent/harness.py` | Async test harness around `AgentSession` |
| `tests/agent/test_*.py` | Unit, scenario and CLI tests |

---

### Task 1: Offline text reading

**Files:**
- Create: `src/openepw/agent/__init__.py`, `src/openepw/agent/text.py`
- Modify: `src/openepw/chat/coordinator.py` (`explicit_weather_years` moves; coordinator imports it)
- Test: `tests/agent/test_text.py`

**Interfaces:**
- Produces: `FUTURE: re.Pattern`; `explicit_weather_years(text) -> set[int]`; `read_product(text) -> str | None` (one of `historical`, `tmy`, `tmyx`, `published`); `place_part(text) -> str`.

- [ ] **Step 1: Write the failing tests** — `tests/agent/test_text.py`

```python
from openepw.agent.text import FUTURE, explicit_weather_years, place_part, read_product


def test_years_are_read_only_as_written():
    assert explicit_weather_years("AMY 2018 for Ithaca") == {2018}
    assert explicit_weather_years("2016-2018") == {2016, 2017, 2018}
    assert explicit_weather_years("2012 buildings in Boston") == set()
    assert explicit_weather_years("the 2010s") == set(range(2010, 2020))


def test_product_words():
    assert read_product("TMYx for Ithaca") == "tmyx"
    assert read_product("a typical meteorological year") == "tmy"
    assert read_product("AMY 2018") == "historical"
    assert read_product("Ithaca") is None


def test_place_part_strips_years_products_and_question_words():
    assert place_part("AMY 2018 for Ithaca NY") == "Ithaca NY"
    assert place_part("Boston, Austin, Denver 2019") == "Boston, Austin, Denver"
    assert place_part("what's available in Phoenix?") == "Phoenix"
    assert place_part("42.44, -76.5 TMYx") == "42.44, -76.5"
    assert place_part("2019 instead") == ""


def test_future_requests_are_recognised():
    assert FUTURE.search("SSP585 2050 for Denver")
    assert FUTURE.search("future weather")
    assert not FUTURE.search("AMY 2018 for Denver")


def test_coordinator_uses_the_shared_year_reader():
    from openepw.agent import text
    from openepw.chat import coordinator

    assert coordinator.explicit_weather_years is text.explicit_weather_years
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_text.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent'`.

- [ ] **Step 3: Create the package and `text.py`**

`src/openepw/agent/__init__.py`:

```python
"""One agent core for the web and CLI chats: an MCP client with forms, gates and policies."""
```

`src/openepw/agent/text.py`:

```python
"""Offline reading of chat text: written years, product words, the place part, future requests."""

from __future__ import annotations

import re

FUTURE = re.compile(r"\b(?:future|ssp\d{3}|rcp\d{2}|climate scenarios?)\b", re.I)

_PRODUCTS = (
    ("tmyx", r"\btmyx\b"),
    ("tmy", r"\btmy\b|\btypical (?:meteorological )?year\b"),
    ("published", r"\bpublished\b"),
    ("historical", r"\b(?:historical|amy|actual[- ]year)\b"),
)

# Years, product words, question words and filler removed so the rest is the place text.
_PLACE_NOISE = re.compile(
    r"\b(?:(?:18|19|20|21)\d{2}(?:\s*(?:-|–|—|to|through)\s*(?:(?:18|19|20|21)\d{2}|\d{2}))?"
    r"|the\s+(?:18|19|20|21)\d0s|historical|amy|actual[- ]year|tmyx|tmy"
    r"|typical(?:\s+meteorological)?\s+year|published|epw|weather|data|files?|please"
    r"|get|give me|i need|i want|for|in|at|near|what(?:'s|\s+is|\s+are)?|which|available"
    r"|options?|sources?|products?|do you have|is there|show me|instead|only|just|use"
    r"|change(?:\s+it)?\s+to|switch to)\b", re.I)


def explicit_weather_years(text: str) -> set[int]:
    """A building count must not turn into a weather year, even if a model proposes it."""
    years = set()
    for match in re.finditer(r"\b(?:18|19|20|21)\d{2}\b", text):
        if not re.match(r"\s+buildings?\b", text[match.end():], re.I):
            years.add(int(match.group()))
    for match in re.finditer(r"\b((?:18|19|20|21)\d{2})\s*(?:-|–|—|to|through)\s*"
                             r"((?:18|19|20|21)\d{2}|\d{2})\b", text, re.I):
        start, tail = int(match.group(1)), match.group(2)
        end = int(tail)
        if len(tail) == 2:                 # "2012-18" and "1998-02" abbreviate the end year
            end += start // 100 * 100
            end += 100 if end < start else 0
        if 0 <= end - start <= 30:
            years.update(range(start, end + 1))
    for match in re.finditer(r"\b((?:18|19|20|21)\d)0s\b", text):     # "the 2010s"
        years.update(range(int(match.group(1)) * 10, int(match.group(1)) * 10 + 10))
    return years


def read_product(text: str) -> str | None:
    """The weather product a message names, if any; TMYx wins over TMY."""
    for product, pattern in _PRODUCTS:
        if re.search(pattern, text, re.I):
            return product
    return None


def place_part(text: str) -> str:
    """The place part of a message; newlines are kept because they separate list items."""
    stripped = re.sub(r"[ \t]+", " ", _PLACE_NOISE.sub(" ", text))
    return "\n".join(line.strip(" ,.;:!?") for line in stripped.splitlines()).strip()
```

- [ ] **Step 4: Point the coordinator at the shared reader**

In `src/openepw/chat/coordinator.py`, delete the whole `def explicit_weather_years(text: str) -> set[int]:` function (about 17 lines, it starts with the docstring "A building count must not turn into a weather year...") and add to the import block, after the `..places.parse` import:

```python
from ..agent.text import explicit_weather_years
```

(Let `ruff check --fix src/openepw/chat/coordinator.py` move it to its sorted position.)

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_text.py tests/unit/test_chat_navigation.py tests/unit/test_chat_sessions.py -q`
Expected: all PASS.

- [ ] **Step 6: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add src/openepw/agent tests/agent/test_text.py src/openepw/chat/coordinator.py
git commit -m "fix(agent): share offline reading of years, products and places"
```

---

### Task 2: Forms, facts and session persistence

**Files:**
- Create: `src/openepw/agent/interactions.py`, `src/openepw/agent/state.py`, `src/openepw/agent/store.py`
- Test: `tests/agent/test_store.py`

**Interfaces:**
- Produces:
  - `Option(id, label, detail=None)`; `Interaction(id, revision, kind, gate, prompt, summary, options, multi, data, allow_text)` with `kind` in `text|choice|location_review|product_choice|map_input|upload|plan_review`; `Answer(interaction_id, revision, choice_ids=[], approve=False, text=None, value=None)`; `Event(seq, type, text, data)` with `type` in `user|assistant|tool|form|job|view|notice|error`.
  - `Facts` fields: `stage, place_set, candidates, place_rows, geography, review, approved_key, product_type, provider, offers, offer_availability, chosen, years, plans, job_ids, finished_job_ids, artifact_ids`; methods `set_geography(value)`, `reset_place()`, `new_request()`.
  - `SessionState(id, revision, mode, facts, form)`.
  - `SessionStore(path)`: `create() -> SessionState`, `load(id) -> SessionState` (raises `KeyError`), `save(state)`, `append(session_id, type, text="", data=None) -> Event`, `events(session_id, after=0) -> list[Event]`, `push_snapshot(state)`, `snapshots(session_id, limit) -> list[SessionState]` (newest first), `drop_snapshot(session_id)`.

- [ ] **Step 1: Write the failing tests** — `tests/agent/test_store.py`

```python
import pytest

from openepw.agent.interactions import Answer, Interaction, Option
from openepw.agent.state import Facts
from openepw.agent.store import SessionStore


def test_sessions_round_trip_with_their_open_form(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite")
    state = store.create()
    state.facts.years = [2018]
    state.form = Interaction(kind="choice", gate="choose_location", prompt="Which?",
                             options=[Option(id="1", label="Springfield, Illinois")])
    store.save(state)
    loaded = store.load(state.id)
    assert loaded == state and loaded.form.options[0].label == "Springfield, Illinois"
    with pytest.raises(KeyError):
        store.load("missing")


def test_events_are_numbered_per_session_and_paged(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite")
    first, second = store.create(), store.create()
    store.append(first.id, "user", "AMY 2018 for Ithaca")
    store.append(second.id, "user", "other")
    event = store.append(first.id, "tool", "weather_geocode", {"tool": "weather_geocode"})
    assert event.seq == 2 and event.data["tool"] == "weather_geocode"
    assert [item.seq for item in store.events(first.id)] == [1, 2]
    assert [item.text for item in store.events(first.id, after=1)] == ["weather_geocode"]


def test_snapshots_are_a_stack_per_session(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite")
    state = store.create()
    for years in ([2018], [2019], [2020]):
        state.facts.years = years
        store.push_snapshot(state)
    assert [item.facts.years for item in store.snapshots(state.id, 2)] == [[2020], [2019]]
    store.drop_snapshot(state.id)
    assert [item.facts.years for item in store.snapshots(state.id, 5)] == [[2019], [2018]]


def test_new_geography_drops_the_review_and_everything_after_it():
    facts = Facts(review={"key": "k"}, approved_key="k", offers=[{"id": "x"}], chosen=[{"id": "x"}],
                  plans=[{"plan_hash": "h"}], years=[2018], product_type="historical")
    facts.set_geography({"lat": 1, "lon": 2})
    assert (facts.review, facts.approved_key, facts.offers, facts.chosen, facts.plans) == (None, None, [], [], [])
    assert facts.years == [2018] and facts.product_type == "historical"


def test_a_new_request_keeps_results_but_clears_the_request():
    facts = Facts(stage="results", geography={"lat": 1, "lon": 2}, job_ids=["j"], finished_job_ids=["j"],
                  artifact_ids=["a"], years=[2018])
    facts.new_request()
    assert facts.stage == "request" and facts.geography is None and facts.job_ids == [] and facts.years == []
    assert facts.finished_job_ids == ["j"] and facts.artifact_ids == ["a"]


def test_answers_and_forms_are_strict():
    with pytest.raises(ValueError):
        Interaction(kind="dialog", prompt="x")
    assert Answer(interaction_id="i", revision=1, approve=True).choice_ids == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent.interactions'`.

- [ ] **Step 3: Create `src/openepw/agent/interactions.py`**

```python
"""Renderer-neutral forms the agent shows, the answers people give, and conversation events."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from ..models import Model

FormKind = Literal["text", "choice", "location_review", "product_choice", "map_input", "upload",
                   "plan_review"]
EventType = Literal["user", "assistant", "tool", "form", "job", "view", "notice", "error"]


class Option(Model):
    id: str
    label: str
    detail: str | None = None


class Interaction(Model):
    """One open form. ``gate`` names the step it answers; ``summary`` is its plain-text body."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 0
    kind: FormKind
    gate: str | None = None
    prompt: str
    summary: str = ""
    options: list[Option] = Field(default_factory=list)
    multi: bool = False
    data: dict[str, Any] = Field(default_factory=dict)
    allow_text: bool = True


class Answer(Model):
    """An answer to the open form: chosen options, an approval, free text or a value."""

    interaction_id: str
    revision: int
    choice_ids: list[str] = Field(default_factory=list)
    approve: bool = False
    text: str | None = None
    value: Any = None


class Event(Model):
    seq: int
    type: EventType
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Create `src/openepw/agent/state.py`**

```python
"""What the conversation has established so far, and the session that holds it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..models import Model
from .interactions import Interaction


class Facts(Model):
    """Pending and approved choices. Only approved facts reach a plan (see gates.build_requests)."""

    stage: Literal["request", "results"] = "request"
    place_set: dict[str, Any] | None = None          # {"draft": ..., "questions": [...]}
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    place_rows: list[dict[str, Any]] = Field(default_factory=list)
    geography: Any = None                            # proposed point, point list or area
    review: dict[str, Any] | None = None             # weather_locations_review result for geography
    approved_key: str | None = None                  # review key the person approved
    product_type: str | None = None                  # historical | tmy | tmyx | published (from text)
    provider: str | None = None
    offers: list[dict[str, Any]] = Field(default_factory=list)
    offer_availability: dict[str, Any] | None = None
    chosen: list[dict[str, Any]] = Field(default_factory=list)   # chosen offers, each with "request"
    years: list[int] = Field(default_factory=list)   # only from the person's text or a form
    plans: list[dict[str, Any]] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    finished_job_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)

    def set_geography(self, value: Any) -> None:
        """A new geography needs a new review, approval, product choice and plan."""
        self.geography = value
        self.review = None
        self.approved_key = None
        self.offers = []
        self.offer_availability = None
        self.chosen = []
        self.plans = []

    def reset_place(self) -> None:
        self.place_set = None
        self.candidates = []
        self.place_rows = []

    def new_request(self) -> None:
        """Start over; finished jobs and EPW artifacts stay available."""
        self.stage = "request"
        self.reset_place()
        self.set_geography(None)
        self.product_type = None
        self.provider = None
        self.years = []
        self.job_ids = []


class SessionState(Model):
    id: str
    revision: int = 0
    mode: Literal["guided", "agent"] = "guided"
    facts: Facts = Field(default_factory=Facts)
    form: Interaction | None = None
```

- [ ] **Step 5: Create `src/openepw/agent/store.py`**

```python
"""SQLite persistence for agent sessions, their events and the form snapshots used by Back."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .interactions import Event
from .state import SessionState

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (session_id TEXT NOT NULL, seq INTEGER NOT NULL,
    event TEXT NOT NULL, PRIMARY KEY (session_id, seq));
CREATE TABLE IF NOT EXISTS snapshots (session_id TEXT NOT NULL, seq INTEGER NOT NULL,
    state TEXT NOT NULL, PRIMARY KEY (session_id, seq));
"""


class SessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        try:
            with db:                      # commits on success, rolls back on error
                yield db
        finally:
            db.close()

    def create(self) -> SessionState:
        state = SessionState(id=uuid.uuid4().hex)
        self.save(state)
        return state

    def load(self, session_id: str) -> SessionState:
        with self._connect() as db:
            row = db.execute("SELECT state FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return SessionState.model_validate_json(row[0])

    def save(self, state: SessionState) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)",
                       (state.id, state.model_dump_json()))

    def append(self, session_id: str, type: str, text: str = "",
               data: dict[str, Any] | None = None) -> Event:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id=?",
                             (session_id,)).fetchone()[0]
            event = Event(seq=seq, type=type, text=text, data=data or {})  # type: ignore[arg-type]
            db.execute("INSERT INTO events VALUES (?, ?, ?)",
                       (session_id, seq, event.model_dump_json()))
        return event

    def events(self, session_id: str, after: int = 0) -> list[Event]:
        with self._connect() as db:
            rows = db.execute("SELECT event FROM events WHERE session_id=? AND seq>? ORDER BY seq",
                              (session_id, after)).fetchall()
        return [Event.model_validate_json(row[0]) for row in rows]

    def push_snapshot(self, state: SessionState) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            seq = db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM snapshots WHERE session_id=?",
                             (state.id,)).fetchone()[0]
            db.execute("INSERT INTO snapshots VALUES (?, ?, ?)",
                       (state.id, seq, state.model_dump_json()))

    def snapshots(self, session_id: str, limit: int) -> list[SessionState]:
        """Newest first."""
        with self._connect() as db:
            rows = db.execute("SELECT state FROM snapshots WHERE session_id=? ORDER BY seq DESC LIMIT ?",
                              (session_id, limit)).fetchall()
        return [SessionState.model_validate(json.loads(row[0])) for row in rows]

    def drop_snapshot(self, session_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM snapshots WHERE session_id=? AND seq="
                       "(SELECT MAX(seq) FROM snapshots WHERE session_id=?)", (session_id, session_id))
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_store.py -q`
Expected: all PASS. If `Event(...)` with a `str` type needs no ignore under mypy, drop the `# type: ignore` comment.

- [ ] **Step 7: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add src/openepw/agent/interactions.py src/openepw/agent/state.py src/openepw/agent/store.py tests/agent/test_store.py
git commit -m "fix(agent): add forms, facts and session persistence"
```

---

### Task 3: Gates and host substitution

**Files:**
- Create: `src/openepw/agent/gates.py`
- Test: `tests/agent/test_gates.py`

**Interfaces:**
- Consumes: `Facts` (Task 2).
- Produces: `GateRequired(need, message)` exception with `.need`; `QUEUED_PROVIDERS`; `needs_years(facts) -> bool`; `next_need(facts) -> str` (one of `next_steps, place_set, choose_location, where, review_location, choose_products, years, plan, review_plan, jobs`); `build_requests(facts) -> list[dict]`; `check_plan_request(facts, request: dict) -> dict`.

- [ ] **Step 1: Write the failing tests** — `tests/agent/test_gates.py`

```python
import pytest

from openepw.agent.gates import GateRequired, build_requests, check_plan_request, next_need
from openepw.agent.state import Facts

POINT = {"lat": 42.44, "lon": -76.5, "standard_offset_minutes": -300, "name": "Ithaca"}
REVIEW = {"key": "k1", "geography": POINT, "sampling": None}
ERA5 = {"id": "era5-openmeteo", "label": "ERA5",
        "request": {"product": "historical",
                    "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}}
ERA5_CDS = {"id": "era5-cds", "label": "ERA5 CDS",
            "request": {"product": "historical",
                        "dataset_selections": [{"provider": "cds", "dataset": "reanalysis-era5-single-levels"}]}}
PVGIS = {"id": "pvgis-tmy", "label": "PVGIS TMY",
         "request": {"product": "tmy", "dataset_selections": [{"provider": "pvgis", "dataset": "PVGIS TMY"}]}}


def approved(**changes):
    facts = Facts(geography=POINT, review=REVIEW, approved_key="k1", chosen=[ERA5], years=[2018])
    for name, value in changes.items():
        setattr(facts, name, value)
    return facts


def test_the_gate_order():
    assert next_need(Facts()) == "where"
    assert next_need(Facts(candidates=[{"id": "1"}])) == "choose_location"
    assert next_need(Facts(place_set={"questions": [{}]})) == "place_set"
    assert next_need(Facts(geography=POINT)) == "review_location"
    assert next_need(Facts(geography=POINT, review=REVIEW)) == "review_location"
    assert next_need(Facts(geography=POINT, review=REVIEW, approved_key="k1")) == "choose_products"
    assert next_need(approved(years=[])) == "years"
    assert next_need(approved(chosen=[PVGIS], years=[])) == "plan"
    assert next_need(approved()) == "plan"
    assert next_need(approved(plans=[{"plan_hash": "h"}])) == "review_plan"
    assert next_need(approved(plans=[{"plan_hash": "h"}], job_ids=["j"])) == "jobs"
    assert next_need(Facts(stage="results")) == "next_steps"


def test_requests_use_the_approved_review_and_group_by_kind():
    requests = build_requests(approved(chosen=[ERA5, ERA5_CDS, PVGIS]))
    assert [(item["product"], [s["provider"] for s in item["dataset_selections"]]) for item in requests] == [
        ("historical", ["openmeteo"]), ("historical", ["cds"]), ("tmy", ["pvgis"])]
    assert all(item["locations"] == POINT and item["sampling"] == {} for item in requests)
    assert requests[0]["years"] == [2018] and requests[2]["years"] == []


def test_requests_refuse_unapproved_facts():
    with pytest.raises(GateRequired) as error:
        build_requests(approved(approved_key="other"))
    assert error.value.need == "review_location"
    with pytest.raises(GateRequired) as error:
        build_requests(approved(chosen=[]))
    assert error.value.need == "choose_products"
    with pytest.raises(GateRequired) as error:
        build_requests(approved(years=[]))
    assert error.value.need == "years"


def test_a_model_request_is_rewritten_to_the_approved_location():
    proposed = {"locations": {"lat": 0, "lon": 0}, "product": "historical", "years": [2018],
                "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}
    checked = check_plan_request(approved(), proposed)
    assert checked["locations"] == POINT and checked["years"] == [2018]


def test_a_model_request_cannot_add_products_or_years():
    with pytest.raises(GateRequired) as error:
        check_plan_request(approved(), {"product": "historical", "years": [2018],
                                        "dataset_selections": [{"provider": "nsrdb", "dataset": "x"}]})
    assert error.value.need == "choose_products"
    with pytest.raises(GateRequired) as error:
        check_plan_request(approved(), {"product": "historical", "years": [2017],
                                        "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]})
    assert error.value.need == "years"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_gates.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent.gates'`.

- [ ] **Step 3: Create `src/openepw/agent/gates.py`**

```python
"""Host guard-rails: the next required step, and plan requests built only from approved facts."""

from __future__ import annotations

from typing import Any

from ..models import DatasetSelection
from .state import Facts

# Copernicus CDS requests wait in Copernicus's queue, so they run as their own job.
QUEUED_PROVIDERS = frozenset({"cds"})


class GateRequired(Exception):
    """A step the person must complete first; ``need`` names it (see next_need)."""

    def __init__(self, need: str, message: str):
        super().__init__(message)
        self.need = need


def needs_years(facts: Facts) -> bool:
    return any(offer["request"]["product"] == "historical" for offer in facts.chosen)


def _reviewed(facts: Facts) -> bool:
    return facts.review is not None and facts.approved_key == facts.review["key"]


def next_need(facts: Facts) -> str:
    if facts.stage == "results":
        return "next_steps"
    if facts.place_set:
        return "place_set"
    if facts.candidates:
        return "choose_location"
    if facts.geography is None:
        return "where"
    if not _reviewed(facts):
        return "review_location"
    if not facts.chosen:
        return "choose_products"
    if needs_years(facts) and not facts.years:
        return "years"
    if not facts.plans:
        return "plan"
    if not facts.job_ids:
        return "review_plan"
    return "jobs"


def _selection(value: dict[str, Any]) -> dict[str, Any]:
    return DatasetSelection.model_validate(value).model_dump(mode="json")


def build_requests(facts: Facts) -> list[dict[str, Any]]:
    """One request per kind from the approved review, chosen offers and stated years."""
    if not _reviewed(facts):
        raise GateRequired("review_location", "The person has not approved these locations")
    if not facts.chosen:
        raise GateRequired("choose_products", "The person has not chosen a weather product")
    if needs_years(facts) and not facts.years:
        raise GateRequired("years", "Actual-year weather needs the person's years")
    assert facts.review is not None
    base = {"locations": facts.review["geography"], "sampling": facts.review.get("sampling") or {}}

    def selections(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [_selection(item) for offer in offers for item in offer["request"]["dataset_selections"]]

    actual = [offer for offer in facts.chosen if offer["request"]["product"] == "historical"]
    typical = [offer for offer in facts.chosen if offer["request"]["product"] != "historical"]
    queued = [offer for offer in actual if any(item["provider"] in QUEUED_PROVIDERS
                                               for item in offer["request"]["dataset_selections"])]
    direct = [offer for offer in actual if offer not in queued]
    requests = [{**base, "product": "historical", "years": list(facts.years),
                 "dataset_selections": selections(group)} for group in (direct, queued) if group]
    if typical:
        kinds = {offer["request"]["product"] for offer in typical}
        requests.append({**base, "product": kinds.pop() if len(kinds) == 1 else "tmy", "years": [],
                         "dataset_selections": selections(typical)})
    return requests


def check_plan_request(facts: Facts, request: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a proposed plan request to the approved facts, or say which step is missing.

    Locations and sampling always come from the approved review; datasets must be among the
    chosen offers; years must be among the person's stated years.
    """
    approved = build_requests(facts)
    product = request.get("product", "historical")
    proposed = [_selection(item) for item in request.get("dataset_selections") or []]
    match = next((item for item in approved if item["product"] == product
                  and all(selection in item["dataset_selections"] for selection in proposed)), None)
    if match is None:
        raise GateRequired("choose_products", "The plan's product or datasets differ from the person's choice")
    years = list(request.get("years") or [])
    if not set(years) <= set(facts.years):
        raise GateRequired("years", "The plan's years differ from the years the person stated")
    return {**match, "dataset_selections": proposed or match["dataset_selections"]}
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_gates.py -q`
Expected: all PASS.

- [ ] **Step 5: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`

```bash
git add src/openepw/agent/gates.py tests/agent/test_gates.py
git commit -m "fix(agent): enforce approval gates and build plans from approved facts"
```

---

### Task 4: In-process MCP client with one-shot approvals

**Files:**
- Create: `src/openepw/agent/mcp_port.py`
- Create: `tests/agent/fakes.py` (offline scenario service, reused by Tasks 6–8)
- Test: `tests/agent/test_mcp_port.py`

**Interfaces:**
- Consumes: P1 `openepw.mcp.server.create_server(service, runner=...)`, `openepw.mcp.approval.approval_callback(is_approved)`.
- Produces: `ToolResult(data: dict, text: str)` (frozen dataclass); `ToolFailure(code, message, retryable=False, details=None)`; `parse_failure(text) -> ToolFailure`; `ApprovalBook` with `approve(plan_hash)`, `consume(plan_hash) -> bool`, `pending` (frozenset); `MCPPort` protocol `async call(name, **arguments) -> ToolResult`; `InProcessMCP(server, approvals)` async context manager implementing `MCPPort`. Test fakes: `scenario_service(tmp_path) -> WeatherService`, `GEOCODER`, `FakeERA5`.

- [ ] **Step 1: Create the offline scenario service** — `tests/agent/fakes.py`

```python
"""Offline service for agent scenarios: fake geocoder, GeoNames files and an ERA5-like provider."""

import hashlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_places_geonames import FakeHttp  # noqa: E402

from openepw.config import RuntimeConfig  # noqa: E402
from openepw.dataset import WeatherDataset  # noqa: E402
from openepw.models import Candidate, SourceRef, VariableLineage  # noqa: E402
from openepw.providers.base import ProviderResult  # noqa: E402
from openepw.providers.openmeteo import interval_bounds  # noqa: E402
from openepw.service import WeatherService  # noqa: E402

GEOCODER = {
    "Ithaca, NY": [("Ithaca, New York, United States", 42.44, -76.50)],
    "Springfield": [("Springfield, Illinois, United States", 39.80, -89.64),
                    ("Springfield, Massachusetts, United States", 42.10, -72.59),
                    ("Springfield, Missouri, United States", 37.21, -93.29)],
    "Boston": [("Boston, Massachusetts, United States", 42.36, -71.06)],
    "Austin": [("Austin, Texas, United States", 30.27, -97.74)],
    "Denver": [("Denver, Colorado, United States", 39.74, -104.98)],
    "Phoenix": [("Phoenix, Arizona, United States", 33.45, -112.07)],
}
VALUES = {"dry_bulb": 10.0, "dew_point": 5.0, "relative_humidity": 70.0, "pressure": 101325.0,
          "wind_speed": 3.0, "wind_direction": 180.0, "ghi": 0.0, "dni": 0.0, "dhi": 0.0}


class ScenarioHttp(FakeHttp):
    """GeoNames files from the unit-test fake plus a small Open-Meteo geocoder table."""

    def __init__(self, config):
        super().__init__()
        self.config = config          # the service's cached-fetch replay reads http.config

    def get_json(self, url, params=None, **kwargs):
        self.calls.append("geocode:" + params["name"])
        return {"results": [{"id": index + 1, "name": name, "latitude": lat, "longitude": lon}
                            for index, (name, lat, lon) in enumerate(GEOCODER.get(params["name"], []))]}


class FakeERA5:
    """Answers openmeteo/era5 selections with constant hourly weather for the requested period."""

    name = "openmeteo"

    def __init__(self):
        self.calls = 0

    def discover(self, request, location, http):
        source = SourceRef(provider=self.name, dataset="era5",
                           identity=f"{location.lat:.2f},{location.lon:.2f}",
                           location=location, provisional=False)
        return [Candidate(id=self.name + location.key, location_id=location.key, source=source,
                          variables=list(VALUES))]

    def fetch(self, task, http):
        self.calls += 1
        start, end = interval_bounds(task.parameters)
        index = pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
        frame = pd.DataFrame({name: [value] * len(index) for name, value in VALUES.items()}, index=index)
        lineage = {variable: VariableLineage(variable=variable, source=task.source,
                                             raw_sha256=hashlib.sha256(b"fake-era5").hexdigest())
                   for variable in frame}
        return ProviderResult(WeatherDataset(data=frame, location=task.source.location, lineage=lineage),
                              task.source, b"fake-era5")


def scenario_service(tmp_path):
    config = RuntimeConfig(data_root=tmp_path)
    return WeatherService(config, http=ScenarioHttp(config), providers=[FakeERA5()])
```

- [ ] **Step 2: Write the failing tests** — `tests/agent/test_mcp_port.py`

```python
import asyncio

import pytest
from fakes import scenario_service

from openepw.agent.mcp_port import ApprovalBook, InProcessMCP, ToolFailure, parse_failure
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server

REQUEST = {"locations": {"lat": 42.44, "lon": -76.5, "standard_offset_minutes": -300},
           "product": "historical", "years": [2018],
           "dataset_selections": [{"provider": "openmeteo", "dataset": "era5"}]}


def test_failures_parse_bare_json_and_plain_text():
    failure = parse_failure('{"code": "INVALID_REQUEST", "message": "bad", "retryable": false, '
                            '"details": [{"loc": "offset", "msg": "x"}]}')
    assert (failure.code, failure.message, failure.details[0]["loc"]) == ("INVALID_REQUEST", "bad", "offset")
    assert parse_failure("Unknown tool: nope").code == "MCP_TOOL_ERROR"


def test_approvals_are_one_shot():
    book = ApprovalBook()
    book.approve("a" * 64)
    assert book.pending == frozenset({"a" * 64})
    assert book.consume("a" * 64) is True and book.consume("a" * 64) is False


def test_in_process_client_calls_tools_and_submits_only_once_per_approval(tmp_path):
    service = scenario_service(tmp_path)
    runner = JobRunner(service)
    approvals = ApprovalBook()

    async def scenario():
        async with InProcessMCP(create_server(service, runner=runner), approvals) as port:
            review = await port.call("weather_locations_review", locations={"lat": 42.44, "lon": -76.5})
            assert review.data["points"][0]["standard_offset_minutes"] == -300
            assert review.data["key"] in review.text
            plan = await port.call("weather_plan", request=REQUEST)
            plan_hash = plan.data["plan_hash"]
            with pytest.raises(ToolFailure) as refused:
                await port.call("weather_submit", plan_hash=plan_hash)
            assert refused.value.code == "APPROVAL_DECLINED"
            approvals.approve(plan_hash)
            job = await port.call("weather_submit", plan_hash=plan_hash)
            assert job.data["approved_via"] == "elicitation" and approvals.pending == frozenset()
            with pytest.raises(ToolFailure) as again:
                await port.call("weather_submit", plan_hash=plan_hash)
            assert again.value.code == "APPROVAL_DECLINED"

    try:
        asyncio.run(scenario())
    finally:
        runner.close()
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_mcp_port.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent.mcp_port'`.

- [ ] **Step 4: Create `src/openepw/agent/mcp_port.py`**

```python
"""The agent's MCP client: in-process transport, parsed failures and one-shot approvals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.shared.memory import create_connected_server_and_client_session

from ..mcp.approval import approval_callback


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, Any]          # structuredContent, for renderers and the host
    text: str                     # short summary, for model context and transcripts


class ToolFailure(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False,
                 details: list[dict[str, Any]] | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or []


def parse_failure(text: str) -> ToolFailure:
    """Tool errors are bare JSON (P1 contract); anything else becomes MCP_TOOL_ERROR."""
    try:
        payload = json.loads(text[text.index("{"):])
        return ToolFailure(str(payload["code"]), str(payload.get("message", "")),
                           retryable=bool(payload.get("retryable", False)),
                           details=list(payload.get("details") or []))
    except (ValueError, KeyError, TypeError):
        return ToolFailure("MCP_TOOL_ERROR", text[:200] or "MCP tool failed")


class ApprovalBook:
    """Each approved plan hash answers exactly one submission confirmation."""

    def __init__(self) -> None:
        self._pending: set[str] = set()

    def approve(self, plan_hash: str) -> None:
        self._pending.add(plan_hash)

    def consume(self, plan_hash: str) -> bool:
        if plan_hash in self._pending:
            self._pending.discard(plan_hash)
            return True
        return False

    @property
    def pending(self) -> frozenset[str]:
        return frozenset(self._pending)


class MCPPort(Protocol):
    async def call(self, name: str, **arguments: Any) -> ToolResult: ...


class InProcessMCP:
    """A real MCP client session over the SDK's in-memory transport.

    Enter and exit it in the same asyncio task. The server should be built with a runner the
    host owns (``create_server(service, runner=...)``).
    """

    def __init__(self, server: Any, approvals: ApprovalBook):
        self.server = server
        self.approvals = approvals
        self._context: Any = None
        self._session: Any = None

    async def __aenter__(self) -> InProcessMCP:
        self._context = create_connected_server_and_client_session(
            self.server, elicitation_callback=approval_callback(self.approvals.consume))
        self._session = await self._context.__aenter__()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        context, self._context, self._session = self._context, None, None
        if context is not None:
            await context.__aexit__(*exc_info)

    async def call(self, name: str, **arguments: Any) -> ToolResult:
        if self._session is None:
            raise ToolFailure("CLIENT_CLOSED", "The MCP session is closed")
        result = await self._session.call_tool(name, arguments)
        text = "".join(block.text for block in result.content if getattr(block, "type", "") == "text")
        if result.isError:
            raise parse_failure(text)
        return ToolResult(dict(result.structuredContent or {}), text)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_mcp_port.py -q`
Expected: all PASS. If `FakeERA5` or the plan fails because a fetch parameter name differs, fix the fake in `tests/agent/fakes.py` (never product code) and say so in your report.

- [ ] **Step 6: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`

```bash
git add src/openepw/agent/mcp_port.py tests/agent/fakes.py tests/agent/test_mcp_port.py
git commit -m "fix(agent): add an in-process MCP client with one-shot approvals"
```

---

### Task 5: Agent session

**Files:**
- Create: `src/openepw/agent/session.py`
- Test: `tests/agent/test_session.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `Policy` protocol: `async on_text(session, text)`, `async on_answer(session, form, answer)`, `async advance(session)`.
  - `AgentSession(store, port, approvals, state, policy, *, poll_seconds=0.5)`; class methods `start(store, port, approvals, policy, **kw)` and `resume(store, port, approvals, policy, session_id, **kw)`.
  - Properties `id`, `facts`, `form`; `events(after=0)`; `emit(type, text="", **data) -> Event`; `open_form(form) -> Interaction`; `close_form()`; `async tool(name, **arguments) -> ToolResult`.
  - Inputs: `async begin()`, `async send_text(text)`, `async answer(answer)`, `async back()`, `async new_request()`, `async upload_epw(content: bytes, filename=None)`, `async follow_jobs(*, timeout=600.0, on_update=None)`.
  - `TERMINAL` (job states), `answer_text(form, answer) -> str`.

- [ ] **Step 1: Write the failing tests** — `tests/agent/test_session.py`

A tiny scripted policy isolates the session from guided rules.

```python
import asyncio

from openepw.agent.interactions import Answer, Interaction, Option
from openepw.agent.mcp_port import ApprovalBook, ToolFailure, ToolResult
from openepw.agent.session import AgentSession
from openepw.agent.store import SessionStore


class Port:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def call(self, name, **arguments):
        self.calls.append(name)
        if self.fail:
            raise ToolFailure("PROVIDER_DOWN", "Provider unavailable", retryable=True)
        return ToolResult({"ok": True}, f"{name} done")


class StepPolicy:
    """Opens form A, then B on any text; records answers."""

    def __init__(self):
        self.answers = []

    async def advance(self, session):
        if session.form is None:
            session.open_form(Interaction(kind="choice", gate="a", prompt="A?",
                                          options=[Option(id="x", label="X")]))

    async def on_text(self, session, text):
        await session.tool("weather_geocode", query=text)
        session.open_form(Interaction(kind="text", gate="b", prompt="B?"))

    async def on_answer(self, session, form, answer):
        self.answers.append(answer.choice_ids)


def make(tmp_path, port=None):
    store = SessionStore(tmp_path / "sessions.sqlite")
    policy = StepPolicy()
    return AgentSession.start(store, port or Port(), ApprovalBook(), policy), store, policy


def test_forms_get_new_revisions_and_events_record_the_turn(tmp_path):
    session, store, _ = make(tmp_path)
    asyncio.run(session.begin())
    first = session.form
    asyncio.run(session.send_text("Ithaca"))
    assert session.form.gate == "b" and session.form.revision > first.revision
    types = [event.type for event in session.events()]
    assert types == ["form", "user", "tool", "tool", "form"]
    assert store.load(session.id).form == session.form


def test_stale_or_foreign_answers_are_refused(tmp_path):
    session, _, policy = make(tmp_path)
    asyncio.run(session.begin())
    form = session.form
    asyncio.run(session.answer(Answer(interaction_id=form.id, revision=form.revision - 1, choice_ids=["x"])))
    assert policy.answers == [] and session.events()[-1].data["code"] == "STALE_FORM"
    asyncio.run(session.answer(Answer(interaction_id=form.id, revision=form.revision, choice_ids=["x"])))
    assert policy.answers == [["x"]]


def test_tool_failures_become_error_events_and_keep_the_form(tmp_path):
    session, _, _ = make(tmp_path, Port(fail=True))
    asyncio.run(session.begin())
    form = session.form
    asyncio.run(session.send_text("Ithaca"))
    assert session.form == form
    assert session.events()[-1].type == "error" and session.events()[-1].data["code"] == "PROVIDER_DOWN"


def test_back_restores_the_previous_form_until_none_is_left(tmp_path):
    session, _, _ = make(tmp_path)
    asyncio.run(session.begin())
    first = session.form
    asyncio.run(session.send_text("Ithaca"))
    asyncio.run(session.back())
    assert session.form.id == first.id and session.form.revision > first.revision
    asyncio.run(session.back())
    assert session.events()[-1].data["code"] == "NOTHING_TO_UNDO"


def test_back_never_crosses_a_started_job(tmp_path):
    session, _, _ = make(tmp_path)
    asyncio.run(session.begin())
    asyncio.run(session.send_text("Ithaca"))
    session.facts.job_ids.append("job-1")
    asyncio.run(session.back())
    assert session.form.gate == "b" and session.events()[-1].data["code"] == "JOB_STARTED"


def test_a_session_resumes_with_its_open_form(tmp_path):
    session, store, policy = make(tmp_path)
    asyncio.run(session.begin())
    resumed = AgentSession.resume(store, Port(), ApprovalBook(), policy, session.id)
    assert resumed.form == session.form
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_session.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent.session'`.

- [ ] **Step 3: Create `src/openepw/agent/session.py`**

```python
"""One conversation: inputs, forms, tool calls, Back, uploads and job following."""

from __future__ import annotations

import asyncio
import base64
from typing import Any, Callable, Protocol

from .gates import GateRequired
from .interactions import Answer, Event, Interaction
from .mcp_port import ApprovalBook, MCPPort, ToolFailure, ToolResult
from .state import Facts, SessionState
from .store import SessionStore

TERMINAL = frozenset({"completed", "partially_completed", "failed", "cancelled"})
MAX_UPLOAD = 5_000_000


class Policy(Protocol):
    async def on_text(self, session: AgentSession, text: str) -> None: ...

    async def on_answer(self, session: AgentSession, form: Interaction, answer: Answer) -> None: ...

    async def advance(self, session: AgentSession) -> None: ...


def answer_text(form: Interaction, answer: Answer) -> str:
    """What the person said, for the transcript."""
    if answer.text:
        return answer.text
    if answer.approve:
        return "Run" if form.kind == "plan_review" else "Approved"
    if answer.choice_ids:
        labels = {option.id: option.label for option in form.options}
        return ", ".join(labels.get(choice, choice) for choice in answer.choice_ids)
    return "Selected on the map" if answer.value is not None else ""


class AgentSession:
    def __init__(self, store: SessionStore, port: MCPPort, approvals: ApprovalBook,
                 state: SessionState, policy: Policy, *, poll_seconds: float = 0.5):
        self.store = store
        self.port = port
        self.approvals = approvals
        self.state = state
        self.policy = policy
        self.poll_seconds = poll_seconds

    @classmethod
    def start(cls, store: SessionStore, port: MCPPort, approvals: ApprovalBook, policy: Policy,
              **options: Any) -> AgentSession:
        return cls(store, port, approvals, store.create(), policy, **options)

    @classmethod
    def resume(cls, store: SessionStore, port: MCPPort, approvals: ApprovalBook, policy: Policy,
               session_id: str, **options: Any) -> AgentSession:
        return cls(store, port, approvals, store.load(session_id), policy, **options)

    @property
    def id(self) -> str:
        return self.state.id

    @property
    def facts(self) -> Facts:
        return self.state.facts

    @property
    def form(self) -> Interaction | None:
        return self.state.form

    def events(self, after: int = 0) -> list[Event]:
        return self.store.events(self.id, after)

    def emit(self, type: str, text: str = "", **data: Any) -> Event:
        return self.store.append(self.id, type, text, data)

    def open_form(self, form: Interaction) -> Interaction:
        """Show a form; the snapshot taken here is what Back returns to."""
        self.state.revision += 1
        form = form.model_copy(update={"revision": self.state.revision})
        self.state.form = form
        self.store.save(self.state)
        self.store.push_snapshot(self.state)
        self.emit("form", form.prompt, form=form.model_dump(mode="json"))
        return form

    def close_form(self) -> None:
        self.state.form = None

    async def tool(self, name: str, **arguments: Any) -> ToolResult:
        self.emit("tool", name, tool=name, phase="call")
        result = await self.port.call(name, **arguments)
        self.emit("tool", result.text, tool=name, phase="result")
        return result

    async def _guard(self, work: Any) -> None:
        try:
            await work
        except ToolFailure as failure:
            self.emit("error", f"{failure.code}: {failure.message}", code=failure.code,
                      retryable=failure.retryable)
        except GateRequired as gate:
            self.emit("error", str(gate), code="GATE_REQUIRED", need=gate.need)
        finally:
            self.store.save(self.state)

    async def begin(self) -> None:
        if self.form is None:
            await self._guard(self.policy.advance(self))

    async def send_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if len(text) > 4000:
            self.emit("error", "Messages are limited to 4,000 characters.", code="MESSAGE_TOO_LONG")
            return
        self.emit("user", text)
        await self._guard(self.policy.on_text(self, text))

    async def answer(self, answer: Answer) -> None:
        form = self.form
        if form is None or answer.interaction_id != form.id or answer.revision != form.revision:
            self.emit("error", "That form is no longer current; answer the latest one.", code="STALE_FORM")
            return
        self.emit("user", answer_text(form, answer), answer=answer.model_dump(mode="json"))
        await self._guard(self.policy.on_answer(self, form, answer))

    async def back(self) -> None:
        current, *earlier = self.store.snapshots(self.id, 2)
        if not earlier:
            self.emit("error", "There is no earlier step to go back to.", code="NOTHING_TO_UNDO")
            return
        restored = earlier[0]
        if restored.facts.job_ids != self.facts.job_ids:
            self.emit("error", "A weather job already started after that step; start a new request instead.",
                      code="JOB_STARTED")
            return
        self.store.drop_snapshot(self.id)
        restored.revision = self.state.revision + 1
        if restored.form is not None:
            restored.form = restored.form.model_copy(update={"revision": restored.revision})
        self.state = restored
        self.store.save(self.state)
        self.emit("notice", "Went back to: " + (restored.form.prompt if restored.form else "the start"),
                  form=restored.form.model_dump(mode="json") if restored.form else None)

    async def new_request(self) -> None:
        self.facts.new_request()
        self.close_form()
        await self._guard(self.policy.advance(self))

    async def upload_epw(self, content: bytes, filename: str | None = None) -> None:
        await self._guard(self._upload(content, filename))

    async def _upload(self, content: bytes, filename: str | None) -> None:
        if not content or len(content) > MAX_UPLOAD:
            self.emit("error", "EPW uploads must be 1 byte to 5 MB.", code="RESOURCE_LIMIT")
            return
        result = await self.tool("epw_upload", content_base64=base64.b64encode(content).decode("ascii"),
                                 filename=filename)
        self.facts.artifact_ids.append(result.data["artifact_id"])
        self.emit("assistant", f"Registered your EPW ({result.data.get('rows')} rows) as artifact "
                               f"{result.data['artifact_id']}.", artifact_id=result.data["artifact_id"])
        if self.facts.geography is None and not self.facts.job_ids:
            self.facts.stage = "results"
            self.close_form()
            await self.policy.advance(self)

    async def follow_jobs(self, *, timeout: float = 600.0,
                          on_update: Callable[[], None] | None = None) -> None:
        """Follow submitted jobs until they finish (the host polls; a model never does)."""
        await self._guard(self._follow(timeout, on_update))

    async def _follow(self, timeout: float, on_update: Callable[[], None] | None) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        seen: dict[str, tuple] = {}
        pending = [job_id for job_id in self.facts.job_ids if job_id not in self.facts.finished_job_ids]
        while pending:
            for job_id in list(pending):
                job = (await self.port.call("job_inspect", job_id=job_id)).data
                snapshot = (job.get("state"), job.get("completed", 0), job.get("failed", 0))
                if seen.get(job_id) != snapshot:
                    seen[job_id] = snapshot
                    self.emit("job", f"Job {job_id[:8]} {job.get('state')}: {job.get('completed', 0)} of "
                                     f"{job.get('total', 0)} outputs done, {job.get('failed', 0)} failed",
                              job_id=job_id, state=job.get("state"), completed=job.get("completed", 0),
                              total=job.get("total", 0), failed=job.get("failed", 0))
                if job.get("state") in TERMINAL:
                    pending.remove(job_id)
                    await self._finished(job_id, job)
            if on_update is not None:
                on_update()
            if pending:
                if loop.time() > deadline:
                    self.emit("notice", "Jobs are still running; check again later.", job_ids=pending)
                    return
                await asyncio.sleep(self.poll_seconds)
        self.facts.stage = "results"
        self.close_form()
        await self.policy.advance(self)

    async def _finished(self, job_id: str, job: dict[str, Any]) -> None:
        weather = list((job.get("artifacts") or {}).get("weather", []))
        codes: set[str] = set()
        for artifact_id in weather[:20]:
            inspected = (await self.tool("artifact_inspect", artifact_id=artifact_id)).data
            codes.update(inspected.get("qc_issue_codes") or [])
        self.facts.finished_job_ids.append(job_id)
        self.facts.artifact_ids.extend(weather)
        message = (f"Job {job.get('state')}: {job.get('completed', 0)} of {job.get('total', 0)} outputs "
                   f"completed, {job.get('failed', 0)} failed; {len(weather)} EPW file(s).")
        message += " QC issue codes: " + ", ".join(sorted(codes)) + "." if codes else ""
        message += (" These EPWs are not certified simulation-ready (simulation_ready=false); "
                    "review QC before simulation." if weather else " No EPW was produced.")
        self.emit("assistant", message, job_id=job_id, artifact_ids=weather)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_session.py -q`
Expected: all PASS. Note the event order in the first test: `begin()` opens form A (`form`); `send_text` emits `user`, the tool `call` and `result`, then form B.

- [ ] **Step 5: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`

```bash
git add src/openepw/agent/session.py tests/agent/test_session.py
git commit -m "fix(agent): add the agent session with forms, back and job following"
```

---

### Task 6: Guided policy and the main scenarios

**Files:**
- Create: `src/openepw/agent/guided.py`
- Create: `tests/agent/harness.py`
- Test: `tests/agent/test_guided_scenarios.py` (S1–S4 and S10–S12 here; Task 7 adds the rest)

**Interfaces:**
- Consumes: Tasks 1–5; MCP tools `weather_places_interpret`, `weather_geocode`, `weather_places_preview`, `weather_place_set`, `weather_locations_review`, `weather_product_offers`, `weather_plan`, `weather_submit`, `weather_visualize`, `weather_export_compact`.
- Produces: `GuidedPolicy` (implements `Policy`; `name = "guided"`); module constants `SUSPENDED`, `UNREAD`. Gates opened: `where` (map_input), `choose_location` (choice), `place_set` (choice), `review_location` (location_review), `choose_products` (product_choice, multi), `years` (text), `review_plan` (plan_review), `next_steps` (choice with ids `view:monthly_series`, `view:histogram`, `export`, `new`). Test harness: `Harness(tmp_path)` async context manager with `session`, `port`, `approvals`, `form`, `say(text)`, `choose(*ids)`, `approve()`, `tools()`, `texts(type)`, `close()`.

- [ ] **Step 1: Create the test harness** — `tests/agent/harness.py`

```python
"""Drive an AgentSession in guided mode against the real MCP server with offline fakes."""

from fakes import scenario_service

from openepw.agent.guided import GuidedPolicy
from openepw.agent.interactions import Answer
from openepw.agent.mcp_port import ApprovalBook, InProcessMCP
from openepw.agent.session import AgentSession
from openepw.agent.store import SessionStore
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server


class Harness:
    def __init__(self, tmp_path, session_id=None):
        self.tmp_path = tmp_path
        self.session_id = session_id
        self.service = scenario_service(tmp_path)
        self.runner = JobRunner(self.service)
        self.server = create_server(self.service, runner=self.runner)
        self.approvals = ApprovalBook()
        self.store = SessionStore(tmp_path / "agent" / "sessions.sqlite")

    async def __aenter__(self):
        self.port = await InProcessMCP(self.server, self.approvals).__aenter__()
        if self.session_id:
            self.session = AgentSession.resume(self.store, self.port, self.approvals, GuidedPolicy(),
                                               self.session_id, poll_seconds=0.05)
        else:
            self.session = AgentSession.start(self.store, self.port, self.approvals, GuidedPolicy(),
                                              poll_seconds=0.05)
        await self.session.begin()
        return self

    async def __aexit__(self, *exc_info):
        await self.port.__aexit__(*exc_info)
        self.runner.close()

    @property
    def form(self):
        return self.session.form

    async def say(self, text):
        await self.session.send_text(text)

    async def choose(self, *ids):
        form = self.form
        await self.session.answer(Answer(interaction_id=form.id, revision=form.revision, choice_ids=list(ids)))

    async def approve(self):
        form = self.form
        await self.session.answer(Answer(interaction_id=form.id, revision=form.revision, approve=True))

    def tools(self):
        return [event.data["tool"] for event in self.session.events()
                if event.type == "tool" and event.data.get("phase") == "call"]

    def texts(self, type):
        return [event.text for event in self.session.events() if event.type == type]


def in_order(sequence, wanted):
    """True when ``wanted`` appears in ``sequence`` in this order (gaps allowed)."""
    remaining = iter(sequence)
    return all(item in remaining for item in wanted)
```

- [ ] **Step 2: Write the failing scenario tests** — `tests/agent/test_guided_scenarios.py`

```python
"""Guided-mode scenarios from the design spec (§6), offline against the real MCP server."""

import asyncio

from harness import Harness, in_order


def run(tmp_path, scenario):
    async def main():
        async with Harness(tmp_path) as h:
            await scenario(h)
    asyncio.run(main())


def test_s1_actual_year_for_one_place_runs_after_reviews(tmp_path):
    async def scenario(h):
        assert h.form.gate == "where" and h.form.kind == "map_input"
        await h.say("AMY 2018 for Ithaca NY")
        assert h.form.gate == "review_location"
        assert h.form.data["points"][0]["standard_offset_minutes"] == -300
        await h.approve()
        assert h.form.gate == "choose_products" and h.form.multi
        assert "era5-openmeteo" in [option.id for option in h.form.options]
        await h.choose("era5-openmeteo")
        assert h.form.gate == "review_plan" and h.form.kind == "plan_review"
        await h.approve()
        assert h.form is None and h.session.facts.job_ids
        await h.session.follow_jobs(timeout=120)
        assert h.session.facts.artifact_ids, h.texts("assistant")
        assert "simulation_ready=false" in h.texts("assistant")[-1]
        assert h.form.gate == "next_steps"
        # job_inspect polling is host work and is not logged as tool events.
        assert in_order(h.tools(), ["weather_geocode", "weather_locations_review", "weather_product_offers",
                                    "weather_plan", "weather_submit", "artifact_inspect"])
        assert "job_inspect" not in h.tools()

    run(tmp_path, scenario)


def test_s2_an_ambiguous_name_asks_which_place(tmp_path):
    async def scenario(h):
        await h.say("Springfield 2018")
        assert h.form.gate == "choose_location" and len(h.form.options) == 3
        await h.choose(h.form.options[1].id)
        assert h.form.gate == "review_location"
        assert "Massachusetts" in h.form.data["points"][0]["name"]

    run(tmp_path, scenario)


def test_s3_coordinates_show_an_estimated_offset(tmp_path):
    async def scenario(h):
        await h.say("42.44, -76.5 TMYx")
        assert h.form.gate == "review_location" and h.form.data["offset_estimated"] is True
        assert "estimated" in h.form.summary
        await h.approve()
        assert h.form.gate == "choose_products" and h.session.facts.product_type == "tmyx"

    run(tmp_path, scenario)


def test_s4_a_place_list_is_reviewed_and_edited(tmp_path):
    async def scenario(h):
        await h.say("Boston, Austin, Denver 2019")
        assert h.form.gate == "review_location" and h.form.data["point_count"] == 3
        await h.say("remove 2")
        assert h.form.gate == "review_location" and h.form.data["point_count"] == 2
        assert [point["name"].split(",")[0] for point in h.form.data["points"]] == ["Boston", "Denver"]
        assert h.tools().count("weather_places_preview") == 2

    run(tmp_path, scenario)


def test_s10_a_year_with_a_reference_product_is_explained(tmp_path):
    async def scenario(h):
        await h.say("TMY 2015 for Denver")
        assert any("reference product" in text for text in h.texts("assistant"))
        assert h.session.facts.years == [] and h.session.facts.product_type == "tmy"
        assert h.form.gate == "review_location"

    run(tmp_path, scenario)


def test_s11_future_weather_is_suspended_without_tools(tmp_path):
    async def scenario(h):
        await h.say("SSP585 2050 for Denver")
        assert any("temporarily unavailable" in text for text in h.texts("assistant"))
        assert h.tools() == [] and h.form.gate == "where"

    run(tmp_path, scenario)


def test_s12_asking_what_is_available_offers_products_without_planning(tmp_path):
    async def scenario(h):
        await h.say("what's available in Phoenix?")
        assert h.form.gate == "review_location"
        await h.approve()
        assert h.form.gate == "choose_products" and h.form.options
        assert "weather_plan" not in h.tools()

    run(tmp_path, scenario)


def test_unread_text_keeps_the_form_and_says_why(tmp_path):
    async def scenario(h):
        await h.say("AMY 2018 for Ithaca NY")
        await h.approve()
        form = h.form                      # the product choice: text here is not read as a place
        await h.say("hmm")
        assert h.form == form and h.texts("assistant")[-1].startswith("Guided mode reads")

    run(tmp_path, scenario)
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_guided_scenarios.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent.guided'`.

- [ ] **Step 4: Create `src/openepw/agent/guided.py`**

```python
"""Guided mode: rule-based forms in the gate order, reading text offline."""

from __future__ import annotations

import re
from typing import Any

from ..models import OpenEPWError
from ..places.parse import apply_edit, describe_place_set
from .gates import build_requests, needs_years, next_need
from .interactions import Answer, Interaction, Option
from .session import AgentSession
from .text import FUTURE, explicit_weather_years, place_part, read_product

SUSPENDED = ("Future-weather planning is temporarily unavailable; ask for actual-year (historical) "
             "or typical-year weather instead.")
UNREAD = "Guided mode reads places, coordinates, years and product names. Use the form."
APPROVE = re.compile(r"a|approve|approved|yes|y|ok|okay|correct|looks good", re.I)
RUN = re.compile(r"run|r|yes|go|start|approve", re.I)
PLACE_GATES = {None, "where", "choose_location", "review_location", "place_set", "next_steps"}
REFERENCE_LABELS = {"tmy": "TMY", "tmyx": "TMYx", "published": "A published EPW"}
VIEWS = (("view:monthly_series", "Monthly dry-bulb temperature chart"),
         ("view:histogram", "Dry-bulb temperature distribution"))


def _offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _point(candidate: dict[str, Any]) -> dict[str, Any]:
    """A geocoder candidate as a request point; its default offset (0) must not be kept."""
    return {key: candidate[key] for key in ("lat", "lon", "name", "id", "elevation")
            if candidate.get(key) is not None}


class GuidedPolicy:
    name = "guided"

    # Text -----------------------------------------------------------------------------
    async def on_text(self, s: AgentSession, text: str) -> None:
        gate = s.form.gate if s.form else None
        if FUTURE.search(text):
            s.emit("assistant", SUSPENDED)
            return
        if gate == "review_location" and APPROVE.fullmatch(text):
            await self._approve_location(s)
            return
        if gate == "review_plan" and RUN.fullmatch(text):
            await self._run(s)
            return
        if gate == "next_steps":
            s.facts.new_request()
            gate = "where"
        changed = self._read_time_and_product(s, text)
        place = place_part(text) if gate in PLACE_GATES else ""
        if gate == "place_set" and place and s.facts.place_set:
            await self._continue_place_set(s, place)
        elif gate == "review_location" and s.facts.place_rows and await self._edit_list(s, text):
            pass
        elif place:
            await self._read_place(s, text, place)
        elif not changed:
            s.emit("assistant", UNREAD)
            return
        await self.advance(s)

    def _read_time_and_product(self, s: AgentSession, text: str) -> bool:
        facts = s.facts
        changed = False
        product = read_product(text)
        if product and product != facts.product_type:
            facts.product_type = product
            facts.offers, facts.offer_availability, facts.chosen, facts.plans = [], None, [], []
            changed = True
        years = sorted(explicit_weather_years(text))
        if not years:
            return changed
        reference = product in REFERENCE_LABELS or (product is None and facts.chosen and not needs_years(facts))
        if reference:
            label = REFERENCE_LABELS.get(product or "", "The chosen product")
            written = ", ".join(map(str, years))
            s.emit("assistant", f"{label} is a reference product, not actual-year weather for {written}. "
                                f"Ask for actual-year weather for {written}, or for it without a year.")
            return True
        if years != facts.years:
            facts.years = years
            facts.plans = []
            changed = True
        if facts.product_type is None:
            facts.product_type = "historical"
        return changed

    async def _read_place(self, s: AgentSession, text: str, place: str) -> None:
        if describe_place_set(text):
            result = (await s.tool("weather_places_interpret", text=text)).data
            await self._place_set_result(s, result)
            return
        result = (await s.tool("weather_places_interpret", text=place)).data
        kind = result.get("kind")
        if kind == "invalid":
            s.emit("assistant", (result.get("issue") or {}).get("message", "That place text is not valid."))
        elif kind == "descriptive":
            await self._place_set_result(s, result)
        elif kind == "coordinates" and len(result.get("points", [])) == 1:
            lat, lon = result["points"][0]
            s.facts.reset_place()
            s.facts.set_geography({"lat": lat, "lon": lon})
        elif kind == "single":
            await self._geocode(s, result["items"][0])
        else:
            items = (result.get("items") if kind == "list"
                     else [f"{lat}, {lon}" for lat, lon in result.get("points", [])])
            await self._preview(s, items or [])

    async def _geocode(self, s: AgentSession, name: str) -> None:
        candidates = (await s.tool("weather_geocode", query=name)).data.get("candidates", [])
        match = re.fullmatch(r"\s*(.+?)[\s,]+([A-Za-z]{2})\s*", name)
        if not candidates and match:
            normalized = f"{match.group(1).rstrip(', ')}, {match.group(2).upper()}"
            if normalized != name:
                candidates = (await s.tool("weather_geocode", query=normalized)).data.get("candidates", [])
        s.facts.reset_place()
        if not candidates:
            s.emit("assistant", f"No location matched '{name}'. Give coordinates or a more specific place.")
        elif len(candidates) == 1:
            s.facts.set_geography(_point(candidates[0]))
        else:
            s.facts.set_geography(None)
            s.facts.candidates = candidates[:10]

    async def _preview(self, s: AgentSession, items: list[Any]) -> None:
        self._apply_rows(s, (await s.tool("weather_places_preview", places=items)).data)

    def _apply_rows(self, s: AgentSession, data: dict[str, Any]) -> None:
        rows = data.get("rows", [])
        s.facts.reset_place()
        s.facts.place_rows = rows
        points = [{"lat": row["lat"], "lon": row["lon"], "name": row.get("name")}
                  for row in rows if row.get("status") == "resolved"]
        s.facts.set_geography(points or None)
        lines = [f"Previewed {data.get('resolved', len(points))} of {len(rows)} places. Fix anything by text, "
                 "for example 'remove 3' or 'add Reno'."]
        for row in rows[:25]:
            if row.get("status") != "resolved":
                lines.append(f"{row['index']}. '{row['input']}' not found; replace or remove it")
            else:
                note = f"; top of {row['candidate_count']} matches, check it" if row.get("ambiguous") else ""
                lines.append(f"{row['index']}. {row.get('name')} ({row['lat']:.4f}, {row['lon']:.4f}){note}")
        if len(rows) > 25:
            lines.append(f"... and {len(rows) - 25} more")
        s.emit("assistant", "\n".join(lines + list(data.get("attribution") or [])))
        if not points:
            s.emit("assistant", "None of those places resolved; give places or coordinates.")

    async def _edit_list(self, s: AgentSession, text: str) -> bool:
        rows = s.facts.place_rows
        labels = [row.get("name") or row["input"] for row in rows]
        try:
            edited = apply_edit(labels, text)
        except OpenEPWError as error:
            s.emit("assistant", error.issue.message)
            return True
        if edited is None:
            return False
        if not edited:
            s.facts.reset_place()
            s.facts.set_geography(None)
            s.emit("assistant", "The place list is now empty; give places or coordinates.")
            return True
        by_label = dict(zip(labels, rows))
        await self._preview(s, [by_label.get(label, label) for label in edited])
        return True

    async def _place_set_result(self, s: AgentSession, result: dict[str, Any]) -> None:
        if result.get("questions"):
            s.facts.candidates = []
            s.facts.place_set = {"draft": result["draft"], "questions": result["questions"]}
            return
        if result.get("query"):
            s.facts.place_set = None
            self._apply_rows(s, (await s.tool("weather_place_set", query=result["query"])).data)

    async def _continue_place_set(self, s: AgentSession, reply: str) -> None:
        assert s.facts.place_set is not None
        result = (await s.tool("weather_places_interpret", text=reply, draft=s.facts.place_set["draft"])).data
        await self._place_set_result(s, result)

    # Answers ----------------------------------------------------------------------------
    async def on_answer(self, s: AgentSession, form: Interaction, answer: Answer) -> None:
        gate = form.gate
        if answer.text:
            await self.on_text(s, answer.text)
            return
        if gate == "review_location" and answer.approve:
            await self._approve_location(s)
            return
        if gate == "review_plan" and answer.approve:
            await self._run(s)
            return
        if gate == "where" and answer.value is not None:
            s.facts.reset_place()
            s.facts.set_geography(answer.value)
            await self.advance(s)
            return
        known = {option.id for option in form.options}
        if (not answer.choice_ids or not set(answer.choice_ids) <= known
                or (not form.multi and len(answer.choice_ids) != 1)):
            s.emit("error", "Choose one of the listed options.", code="UNKNOWN_CHOICE")
            return
        choice = answer.choice_ids[0]
        if gate == "choose_location":
            candidate = next(item for index, item in enumerate(s.facts.candidates)
                             if str(item.get("id", index)) == choice)
            s.facts.candidates = []
            s.facts.set_geography(_point(candidate))
        elif gate == "place_set":
            await self._continue_place_set(s, form.data["answers"][choice])
        elif gate == "choose_products":
            s.facts.chosen = [offer for offer in s.facts.offers if offer["id"] in answer.choice_ids]
            s.facts.plans = []
            if not needs_years(s.facts):
                s.facts.years = []
        elif gate == "next_steps":
            await self._next_step(s, choice)
            return
        await self.advance(s)

    async def _approve_location(self, s: AgentSession) -> None:
        if s.facts.review is None:
            s.emit("error", "There is no location review to approve.", code="GATE_REQUIRED")
            return
        s.facts.approved_key = s.facts.review["key"]
        s.emit("assistant", "Location approved.")
        await self.advance(s)

    async def _run(self, s: AgentSession) -> None:
        plans = [plan for plan in s.facts.plans if plan["output_count"]]
        if not plans:
            s.emit("error", "There is no reviewed plan to run.", code="GATE_REQUIRED")
            return
        for plan in plans:
            s.approvals.approve(plan["plan_hash"])
            job = (await s.tool("weather_submit", plan_hash=plan["plan_hash"],
                                idempotency_key=f"agent:{s.id}:{plan['plan_hash'][:16]}")).data
            s.facts.job_ids.append(job["id"])
            s.emit("job", f"Weather job {job['id'][:8]} started", job_id=job["id"], state=job.get("state"))
        s.close_form()

    async def _next_step(self, s: AgentSession, choice: str) -> None:
        if choice == "new":
            s.facts.new_request()
        elif choice.startswith("view:"):
            family = choice.split(":", 1)[1]
            result = await s.tool("weather_visualize", request={
                "artifact_ids": s.facts.artifact_ids[-100:], "family": family, "variable": "dry_bulb"})
            s.emit("view", result.text, view_id=result.data["view_id"], family=family, variable="dry_bulb")
        elif choice == "export":
            for job_id in s.facts.finished_job_ids:
                data = (await s.tool("weather_export_compact", job_id=job_id)).data
                s.emit("assistant", f"Compact ZIP ready: artifact {data['artifact_id']} ({data['bytes']} bytes).",
                       artifact_id=data["artifact_id"])
        await self.advance(s)

    # Forms ------------------------------------------------------------------------------
    async def advance(self, s: AgentSession) -> None:
        facts = s.facts
        need = next_need(facts)
        if need == "place_set":
            s.open_form(self._place_set_form(facts.place_set or {}))
        elif need == "choose_location":
            s.open_form(Interaction(
                kind="choice", gate="choose_location", prompt="Which location do you mean?",
                options=[Option(id=str(item.get("id", index)), label=item.get("name") or "unnamed",
                                detail=f"{item['lat']:.4f}, {item['lon']:.4f}")
                         for index, item in enumerate(facts.candidates)]))
        elif need == "where":
            s.open_form(Interaction(
                kind="map_input", gate="where", prompt="Where do you need weather?",
                summary="Give a place name, a list of places, or coordinates such as 42.44, -76.50.",
                data={"hint": "e.g. Ithaca, NY · Boston; Denver · 42.44, -76.50"}))
        elif need == "review_location":
            if facts.review is None:
                facts.review = (await s.tool("weather_locations_review", locations=facts.geography)).data
            s.open_form(self._review_form(facts))
        elif need == "choose_products":
            assert facts.review is not None               # next_need guarantees an approved review
            if not facts.offers:
                data = (await s.tool("weather_product_offers", locations=facts.review["geography"],
                                     product=facts.product_type, provider=facts.provider,
                                     years=facts.years or None)).data
                facts.offers = data.get("options", [])
                facts.offer_availability = data.get("availability")
            s.open_form(Interaction(
                kind="product_choice", gate="choose_products", multi=True, prompt="Which weather products?",
                summary="Listed means eligible to try retrieval, not quality assured.",
                options=[Option(id=offer["id"], label=offer["label"], detail=offer.get("detail"))
                         for offer in facts.offers],
                data={"availability": facts.offer_availability}))
        elif need == "years":
            s.open_form(Interaction(kind="text", gate="years", prompt="Which actual year or years?",
                                    summary="Actual-year products need calendar years.",
                                    data={"hint": "e.g. 2018 or 2016-2018"}))
        elif need == "plan":
            await self._plan(s)
        elif need == "review_plan":
            if not (s.form and s.form.gate == "review_plan"):
                s.open_form(self._plan_form(facts))
        elif need == "next_steps":
            s.open_form(self._next_steps_form(facts))
        else:                                              # "jobs": retrieval is running
            s.close_form()

    async def _plan(self, s: AgentSession) -> None:
        facts = s.facts
        for request in build_requests(facts):
            result = await s.tool("weather_plan", request=request)
            facts.plans.append({"plan_hash": result.data["plan_hash"], "product": request["product"],
                                "output_count": result.data.get("output_count", 0), "summary": result.text,
                                "warnings": result.data.get("warnings", [])})
        if not any(plan["output_count"] for plan in facts.plans):
            s.emit("assistant", "The plan has no executable output for these choices; choose other products.")
            facts.chosen, facts.plans = [], []
        await self.advance(s)

    @staticmethod
    def _place_set_form(place_set: dict[str, Any]) -> Interaction:
        question = place_set["questions"][0]
        numbered = bool((place_set.get("draft") or {}).get("region_options"))
        options, answers = [], {}
        for index, option in enumerate(question.get("options", []), start=1):
            if question["field"] == "region":
                label = option["label"]
                answer = str(index) if numbered else label
            elif question["field"] == "definition":
                label, answer = f"{option['min_population']:,}", str(option["min_population"])
            else:
                label = "All (1,000)" if option["limit"] >= 1000 else str(option["limit"])
                answer = "all" if option["limit"] >= 1000 else f"top {option['limit']}"
            options.append(Option(id=f"place:{index}", label=label))
            answers[f"place:{index}"] = answer
        return Interaction(kind="choice", gate="place_set", prompt=question["prompt"], options=options,
                           data={"answers": answers, "field": question["field"]})

    @staticmethod
    def _review_form(facts: Any) -> Interaction:
        review = facts.review
        count = review["point_count"]
        lines = [f"{index}. {point.get('name') or 'point'} ({point['lat']:.4f}, {point['lon']:.4f}) "
                 f"{_offset(point['standard_offset_minutes'])}"
                 for index, point in enumerate(review["points"][:25], start=1)]
        if count > 25:
            lines.append(f"... and {count - 25} more")
        lines.append(review["standard_time"])
        return Interaction(
            kind="location_review", gate="review_location",
            prompt="Are these the right locations?" if count > 1 else "Is this the right location?",
            summary="\n".join(lines), data={**review, "several": count > 1, "rows": facts.place_rows})

    @staticmethod
    def _plan_form(facts: Any) -> Interaction:
        lines = []
        for plan in facts.plans:
            heading = "Actual year" if plan["product"] == "historical" else "Typical year"
            lines.append(f"{heading}: {plan['summary']}")
            lines.extend(f"Warning: {warning}" for warning in plan.get("warnings", [])[:5])
        if any(plan["product"] == "historical" for plan in facts.plans) and facts.review:
            lines.append(facts.review["standard_time"])
        lines.append("Listed sources are eligible to try; retrieved weather is checked by QC afterwards.")
        return Interaction(kind="plan_review", gate="review_plan",
                           prompt="Review the plan, then run it to start retrieval.",
                           summary="\n".join(lines), data={"plans": facts.plans})

    @staticmethod
    def _next_steps_form(facts: Any) -> Interaction:
        options = [Option(id=choice, label=label) for choice, label in VIEWS] if facts.artifact_ids else []
        if facts.finished_job_ids:
            options.append(Option(id="export", label="Compact ZIP of the outputs"))
        options.append(Option(id="new", label="Start a new weather request"))
        return Interaction(kind="choice", gate="next_steps", prompt="What next?", options=options)
```

- [ ] **Step 5: Run the scenarios**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_guided_scenarios.py -q`
Expected: all PASS. If S1's job does not complete because `FakeERA5` output is rejected (e.g. a variable name), fix the fake, not product code, and record it. If `era5-openmeteo` is not among the offers, check what `weather_product_offers` returns for an uncatalogued data root and adjust the fake to serve that openmeteo dataset; report the finding.

- [ ] **Step 6: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`

```bash
git add src/openepw/agent/guided.py tests/agent/harness.py tests/agent/test_guided_scenarios.py
git commit -m "fix(agent): add guided mode over MCP with the main scenarios"
```

---

### Task 7: Remaining guided scenarios

**Files:**
- Test: `tests/agent/test_guided_scenarios_more.py`
- Modify (only if a scenario exposes a defect): `src/openepw/agent/guided.py`, `src/openepw/agent/session.py`

**Interfaces:**
- Consumes: `Harness`, `in_order` (Task 6); `tests/unit/test_epw.synthetic`, `openepw.epw.writer.epw_bytes`.

- [ ] **Step 1: Write the scenario tests** — `tests/agent/test_guided_scenarios_more.py`

```python
"""S5, S9, S15, S17, S18, S21 and one-shot approvals."""

import asyncio
import sys
from pathlib import Path

import pytest
from harness import Harness

from openepw.agent.interactions import Answer
from openepw.agent.mcp_port import ToolFailure
from openepw.epw.writer import epw_bytes

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_epw import synthetic  # noqa: E402


async def to_plan_review(h):
    await h.say("AMY 2018 for Ithaca NY")
    await h.approve()
    await h.choose("era5-openmeteo")
    assert h.form.gate == "review_plan"


def test_s5_a_descriptive_set_asks_before_listing(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("all cities in Texas")
            assert h.form.gate == "place_set"
            for _ in range(4):
                if h.form.gate != "place_set":
                    break
                await h.choose(h.form.options[0].id)
            assert h.form.gate == "review_location" and h.form.data["point_count"] >= 1
            assert h.tools().index("weather_places_interpret") < h.tools().index("weather_place_set")
    asyncio.run(main())


def test_s9_changing_the_year_after_review_needs_a_new_plan(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            first = h.session.facts.plans[0]["plan_hash"]
            await h.say("2019 instead")
            assert h.form.gate == "review_plan" and h.session.facts.years == [2019]
            assert h.session.facts.plans[0]["plan_hash"] != first
            assert h.approvals.pending == frozenset()
    asyncio.run(main())


def test_s15_an_uploaded_epw_can_be_charted(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.session.upload_epw(epw_bytes(synthetic(2023, 8760)), "site.epw")
            assert h.form.gate == "next_steps" and h.session.facts.artifact_ids
            await h.choose("view:monthly_series")
            views = [event for event in h.session.events() if event.type == "view"]
            assert views and views[-1].data["view_id"]
            assert h.form.gate == "next_steps"
    asyncio.run(main())


def test_s17_a_stale_answer_is_refused(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("Springfield 2018")
            form = h.form
            await h.session.answer(Answer(interaction_id=form.id, revision=form.revision - 1,
                                          choice_ids=[form.options[0].id]))
            assert h.form == form and h.session.events()[-1].data["code"] == "STALE_FORM"
    asyncio.run(main())


def test_s18_a_restarted_session_keeps_its_open_form(tmp_path):
    async def first():
        async with Harness(tmp_path) as h:
            await h.say("AMY 2018 for Ithaca NY")
            await h.approve()
            return h.session.id, h.form

    async def second(session_id):
        async with Harness(tmp_path, session_id=session_id) as h:
            return h.form

    session_id, form = asyncio.run(first())
    assert asyncio.run(second(session_id)) == form


def test_s21_back_returns_to_the_location_review(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("AMY 2018 for Ithaca NY")
            await h.approve()
            assert h.form.gate == "choose_products"
            await h.session.back()
            assert h.form.gate == "review_location" and h.session.facts.approved_key is None
            await h.session.back()
            assert h.form.gate == "where"
            await h.session.back()
            assert h.session.events()[-1].data["code"] == "NOTHING_TO_UNDO"
    asyncio.run(main())


def test_an_approval_answers_exactly_one_submission(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await to_plan_review(h)
            plan_hash = h.session.facts.plans[0]["plan_hash"]
            await h.approve()
            assert h.session.facts.job_ids
            with pytest.raises(ToolFailure) as refused:
                await h.port.call("weather_submit", plan_hash=plan_hash)
            assert refused.value.code == "APPROVAL_DECLINED"
    asyncio.run(main())


def test_an_unknown_choice_is_refused(tmp_path):
    async def main():
        async with Harness(tmp_path) as h:
            await h.say("Springfield 2018")
            form = h.form
            await h.choose("nope")
            assert h.form == form and h.session.events()[-1].data["code"] == "UNKNOWN_CHOICE"
    asyncio.run(main())
```

- [ ] **Step 2: Run them**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_guided_scenarios_more.py -q`
Expected: PASS. If one fails because of a defect in `guided.py` or `session.py`, write down the failing assertion, fix the product code minimally, re-run both scenario files, and describe the defect in the commit message body.

- [ ] **Step 3: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`

```bash
git add tests/agent/test_guided_scenarios_more.py src/openepw/agent
git commit -m "fix(agent): cover place sets, replans, uploads, restarts and back in guided mode"
```

---

### Task 8: CLI renderer and `openepw chat`

**Files:**
- Create: `src/openepw/agent/cli.py`
- Modify: `src/openepw/cli/main.py` (add the `chat` subcommand)
- Test: `tests/agent/test_cli.py`

**Interfaces:**
- Consumes: Tasks 2–7.
- Produces: `render_form(form) -> str`; `render_event(event) -> str | None` (None = not shown); `parse_reply(form, line) -> Answer | None`; `async main_chat(service, *, session_id=None, read=input, write=print, poll_seconds=0.5) -> int`; CLI `openepw [--data-root R] chat [--session ID]`.

- [ ] **Step 1: Write the failing tests** — `tests/agent/test_cli.py`

```python
import asyncio

from fakes import scenario_service

from openepw.agent.cli import main_chat, parse_reply, render_event, render_form
from openepw.agent.interactions import Event, Interaction, Option


def test_every_form_kind_renders_as_text():
    choice = Interaction(kind="choice", gate="choose_location", prompt="Which location do you mean?",
                         options=[Option(id="1", label="Springfield, Illinois", detail="39.8000, -89.6400")])
    assert "1. Springfield, Illinois" in render_form(choice)
    products = Interaction(kind="product_choice", prompt="Which weather products?", multi=True,
                           options=[Option(id="era5-openmeteo", label="ERA5")])
    assert "comma" in render_form(products)
    review = Interaction(kind="location_review", prompt="Is this the right location?", summary="1. Ithaca")
    assert "1. Ithaca" in render_form(review) and "'a' to approve" in render_form(review)
    plan = Interaction(kind="plan_review", prompt="Review the plan", summary="Actual year: plan_hash x")
    assert "'run'" in render_form(plan)
    where = Interaction(kind="map_input", prompt="Where do you need weather?", data={"hint": "e.g. Ithaca"})
    assert "e.g. Ithaca" in render_form(where)
    years = Interaction(kind="text", prompt="Which actual year or years?", data={"hint": "e.g. 2018"})
    assert "e.g. 2018" in render_form(years)
    upload = Interaction(kind="upload", prompt="Attach an EPW")
    assert "/upload" in render_form(upload)


def test_replies_map_to_answers():
    choice = Interaction(kind="product_choice", prompt="?", multi=True,
                         options=[Option(id="a", label="A"), Option(id="b", label="B")])
    assert parse_reply(choice, "1, 2").choice_ids == ["a", "b"]
    assert parse_reply(choice, "7") is None and parse_reply(choice, "ERA5 please") is None
    single = Interaction(kind="choice", prompt="?", options=[Option(id="a", label="A"), Option(id="b", label="B")])
    assert parse_reply(single, "1, 2") is None
    review = Interaction(kind="location_review", prompt="?")
    assert parse_reply(review, "a").approve and parse_reply(review, "remove 2") is None
    plan = Interaction(kind="plan_review", prompt="?")
    assert parse_reply(plan, "run").approve


def test_events_render_without_echoing_the_person_or_tool_calls():
    assert render_event(Event(seq=1, type="user", text="hi")) is None
    assert render_event(Event(seq=2, type="tool", text="weather_geocode", data={"phase": "call"})) is None
    assert render_event(Event(seq=3, type="tool", text="1 candidate", data={"phase": "result"})) == "  · 1 candidate"
    assert render_event(Event(seq=4, type="error", text="STALE_FORM: x")).startswith("✗")


def test_a_cli_conversation_runs_a_plan_and_reports_qc(tmp_path):
    lines = iter(["AMY 2018 for Ithaca NY", "a", "1", "run", "/quit"])
    output = []
    code = asyncio.run(main_chat(scenario_service(tmp_path), read=lambda prompt: next(lines),
                                 write=output.append, poll_seconds=0.05))
    text = "\n".join(output)
    assert code == 0
    assert "Is this the right location?" in text and "Which weather products?" in text
    assert "simulation_ready=false" in text and "What next?" in text
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.agent.cli'`.

- [ ] **Step 3: Create `src/openepw/agent/cli.py`**

```python
"""Text rendering of agent events and forms, and the `openepw chat` loop."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable

from ..jobs.worker import JobRunner
from ..models import OpenEPWError
from .guided import GuidedPolicy
from .interactions import Answer, Event, Interaction
from .mcp_port import ApprovalBook, InProcessMCP
from .session import AgentSession
from .store import SessionStore

HELP = ("Type a weather request, or answer the current form.\n"
        "/back  /new  /upload <path to .epw>  /status  /mode  /help  /quit\n"
        "EPW bytes stay out of the conversation; review QC before simulation.")
_NUMBERS = re.compile(r"\d+(?:\s*,\s*\d+)*")


def render_form(form: Interaction) -> str:
    lines = ["? " + form.prompt]
    if form.summary:
        lines.append(form.summary)
    if form.kind in ("choice", "product_choice"):
        lines.extend(f"  {index}. {option.label}" + (f" — {option.detail}" if option.detail else "")
                     for index, option in enumerate(form.options, start=1))
        lines.append("Reply with numbers separated by commas." if form.multi else "Reply with a number.")
    elif form.kind == "location_review":
        lines.append("Type 'a' to approve, or describe a change (e.g. 'remove 2' or another place).")
    elif form.kind == "plan_review":
        lines.append("Type 'run' to start retrieval, or describe a change.")
    elif form.kind == "upload":
        lines.append("Use /upload <path to .epw>.")
    elif form.data.get("hint"):
        lines.append(str(form.data["hint"]))
    return "\n".join(lines)


def render_event(event: Event) -> str | None:
    if event.type in ("user", "form"):
        return None
    if event.type == "tool":
        return None if event.data.get("phase") == "call" else "  · " + event.text.splitlines()[0]
    prefix = {"assistant": "", "job": "[job] ", "view": "[view] ", "notice": "! ", "error": "✗ "}[event.type]
    return prefix + event.text


def parse_reply(form: Interaction, line: str) -> Answer | None:
    """A reply that answers the form directly; None means read it as text."""
    reply = line.strip()
    base = {"interaction_id": form.id, "revision": form.revision}
    if form.kind in ("choice", "product_choice") and _NUMBERS.fullmatch(reply):
        indices = [int(item) for item in reply.split(",")]
        if not form.multi and len(indices) != 1:
            return None
        if not all(1 <= index <= len(form.options) for index in indices):
            return None
        return Answer(**base, choice_ids=[form.options[index - 1].id for index in indices])
    if form.kind == "location_review" and reply.casefold() in ("a", "approve", "yes", "y", "ok"):
        return Answer(**base, approve=True)
    if form.kind == "plan_review" and reply.casefold() in ("run", "r", "yes", "go"):
        return Answer(**base, approve=True)
    return None


async def main_chat(service: Any, *, session_id: str | None = None,
                    read: Callable[[str], str] = input, write: Callable[[str], Any] = print,
                    poll_seconds: float = 0.5) -> int:
    from ..mcp.server import create_server

    runner = JobRunner(service)
    try:
        runner.recover()
    except OpenEPWError as error:
        write(f"✗ {error.issue.code}: {error.issue.message}")
        runner.close()
        return 2
    approvals = ApprovalBook()
    store = SessionStore(Path(service.config.data_root) / "agent" / "sessions.sqlite")
    seen = 0
    try:
        async with InProcessMCP(create_server(service, runner=runner), approvals) as port:
            policy = GuidedPolicy()
            session = (AgentSession.resume(store, port, approvals, policy, session_id, poll_seconds=poll_seconds)
                       if session_id else
                       AgentSession.start(store, port, approvals, policy, poll_seconds=poll_seconds))
            write(f"OpenEPW chat (guided mode) · session {session.id}. Type /help for commands.")
            await session.begin()

            def flush() -> None:
                nonlocal seen
                for event in session.events(seen):
                    seen = event.seq
                    shown = render_event(event)
                    if shown:
                        write(shown)

            flush()
            if session.form:
                write(render_form(session.form))
            while True:
                pending = [job for job in session.facts.job_ids if job not in session.facts.finished_job_ids]
                if pending:
                    await session.follow_jobs(on_update=flush)
                    flush()
                    if session.form:
                        write(render_form(session.form))
                try:
                    line = await asyncio.to_thread(read, "> ")
                except (EOFError, KeyboardInterrupt):
                    break
                command, _, argument = line.strip().partition(" ")
                before = session.form
                if command in ("/quit", "/exit"):
                    break
                if command == "/help":
                    write(HELP)
                    continue
                if command == "/mode":
                    write("Guided mode: rule-based forms. Agent mode arrives with the model loop.")
                    continue
                if command == "/status":
                    write(f"Jobs: {', '.join(session.facts.job_ids) or 'none'}")
                    continue
                if command == "/back":
                    await session.back()
                elif command == "/new":
                    await session.new_request()
                elif command == "/upload":
                    path = Path(argument.strip().strip('"')).expanduser()
                    if not path.is_file():
                        write("✗ No such file.")
                        continue
                    await session.upload_epw(path.read_bytes(), path.name)
                else:
                    answer = parse_reply(session.form, line) if session.form else None
                    if answer is not None:
                        await session.answer(answer)
                    else:
                        await session.send_text(line)
                flush()
                if session.form and session.form != before:
                    write(render_form(session.form))
    finally:
        runner.close()
    write(f"Session {session.id} saved. Resume with: openepw chat --session {session.id}")
    return 0
```

- [ ] **Step 4: Add the subcommand**

In `src/openepw/cli/main.py`: add `import asyncio` at the top; after the `mcp` parser definition add

```python
    chat = sub.add_parser("chat", help="Guided weather chat over the local MCP server")
    chat.add_argument("--session", help="Resume a saved chat session by ID")
```

and in the command dispatch, next to the `mcp` branch, add

```python
        if args.command == "chat":
            from ..agent.cli import main_chat

            return asyncio.run(main_chat(service, session_id=args.session))
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/agent/test_cli.py -q`
Expected: all PASS. If `session` is unbound in the final `write` when `InProcessMCP` fails to open, move that `write` inside the `async with` block after the loop and report it.

- [ ] **Step 6: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`

```bash
git add src/openepw/agent/cli.py src/openepw/cli/main.py tests/agent/test_cli.py
git commit -m "fix(agent): add the openepw chat command with text forms"
```

---

### Task 9: Documentation and full verification

**Files:**
- Create: `docs/agent/README.md`
- Modify: `ARCHITECTURE.md` (after the 2026-10 MCP paragraph), `FEATURES.md` (new row), `docs/decisions/0005-mcp-agent-chat.md` (status), this plan (append "Execution notes")

- [ ] **Step 1: Write `docs/agent/README.md`**

```markdown
# Agent chat core (guided mode)

`openepw.agent` is one conversation core for the CLI and (from P4) the web chat. It is a real
MCP client of the local openepw server over the SDK's in-memory transport and never calls the
weather service directly.

## Run it

```powershell
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat --session <id>
```

One process runs jobs for a data root: stop `openepw serve` or use another data root
(`DATA_ROOT_BUSY` otherwise). Commands: `/back`, `/new`, `/upload <path>`, `/status`, `/mode`,
`/help`, `/quit`.

## Forms and gates

Every step is a typed form (`text`, `choice`, `location_review`, `product_choice`, `map_input`,
`upload`, `plan_review`). Guided mode asks them in the gate order: place → location review
(with fixed standard-time offsets) → products → years (actual-year only) → plan review → run →
job progress → next steps (charts, compact ZIP, new request). Plans are built by the host from
the approved review, chosen offers and the years the person wrote; a model-supplied plan request
(P3) is rewritten the same way. Each plan approval answers exactly one submission confirmation.
Future weather stays suspended. Retrieved EPWs are not certified simulation-ready.

## Modes

P2 ships guided mode only (rule-based forms, offline text reading). Agent mode with a
tool-calling model arrives in P3 with the same forms and gates.
```

- [ ] **Step 2: Update ARCHITECTURE, FEATURES, ADR and the plan**

In `ARCHITECTURE.md`, after the paragraph starting "Since 2026-10 (ADR 0005, P1)", add:

```markdown
P2 adds `openepw.agent`: an `AgentSession` (SQLite events, typed facts, form snapshots for Back)
that talks to the MCP server through the in-memory transport, host gates that build plan
requests only from approved facts, a rule-based guided policy, and the `openepw chat` CLI that
renders every form as text. The agent package is optional and never imported by the core.
```

In `FEATURES.md`, add a row after `Local MCP contract`:
`| Agent chat core (guided) | P2 implemented, offline tested | One MCP-client session for CLI (and later web): typed forms, approval gates, host-built plans, one-shot approvals, guided mode, \`openepw chat\` |`

In `docs/decisions/0005-mcp-agent-chat.md`, change "P2–P5 pending" to "P2 (agent core, guided mode, CLI) implemented; P3–P5 pending" (keep ~80-column wrapping).

Append to this plan:

```markdown
## Execution notes

(Record deviations, fake adjustments and owner decisions made during execution here.)
```

- [ ] **Step 3: Full verification**

Run each and record the actual result lines:

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m build
```

Expected: pytest passes except exactly the 4 known pre-existing failures (Global Constraints); ruff, mypy and build succeed. Then try the CLI by hand once on a scratch data root (it needs network for real geocoding and providers; if offline, say so):

```powershell
.venv/Scripts/openepw.exe --data-root .local/agent-try chat
```

- [ ] **Step 4: Commit**

```bash
git add docs/agent/README.md ARCHITECTURE.md FEATURES.md docs/decisions/0005-mcp-agent-chat.md docs/superpowers/plans/2026-10-05-mcp-agent-chat-p2-agent-core.md
git commit -m "fix(docs): document the guided agent core and openepw chat"
```

---

## Later phases

| Phase | Scope |
| --- | --- |
| P3 | `ModelPort` (OpenAI adapter with ledger/budget stop; `ScriptedModel`), model policy: tool-calling loop over `MODEL_TOOLS` plus ask-tools that open these same forms, `check_plan_request` before `weather_plan`, limits (8 steps, 2 retries, 60 s), one repair attempt then guided fallback, mode switching (`/mode`), scenarios S6–S8, S13, S14, S16, S19, S20, and the reusable `openepw eval` runner with opt-in live runs. |
| P4 | `/v2/agent` REST + SSE over `app.state.mcp_server` (one long-lived in-memory client per session task), React rendering of the same forms, mode toggle, parity tests (CLI text vs API), vitest fixtures from Python events, CI `web` job, optional `/mcp` streamable HTTP behind bearer auth, lock hardening. |
| P5 | Retire `ChatCoordinator`, `chat/products.py`, `ReferenceAgent`, `ChatSession`, `GraphChatSession`, `/v1/chat/*`; docs and validation record. |

## Execution notes (2026-10-05)

Executed on branch `feature/mcp-agent-core` from `feature/chat-ui` at `639aa12` (the handoff
commit; it contains `d32a449`). The handoff's default branch was used; the owner named none.
The code blocks above are left as written and are superseded where they differ.

- Environment: this machine's venv had no `harness` or `cds` extras, so `tests/harness` failed to
  collect (`langsmith` missing). The CI extras (`.[dev,api,mcp,harness,cds]`) were installed into
  the local venv; nothing in the repository changed for this. Only Python 3.14 is installed
  locally, so 3.11 compatibility was checked by review, not by running.
- Process: tasks were implemented test-first in plan order by one agent; reviews (spec and
  quality) ran as separate read-only reviewer agents over tasks 1-2, 3-5 and 6-8, then a
  whole-branch review and a focused re-review of the final run guard. Findings were fixed in
  follow-up commits rather than by rewriting task commits.
- Task 2: the `# type: ignore[arg-type]` in `SessionStore.append` was unused under mypy and was
  dropped, as the plan allowed.
- Tasks 1-8 matched the plan's code; no test fake needed changing. Review fixes, each with tests:
  - Text reading: scenario names such as SSP5-8.5, SSP2-4.5, RCP 4.5, rcp85 and CMIP6 are future
    requests (previously "SSP5-8.5 2050" would have been read as actual year 2050). Upper-case IN
    and AT stay in place text as state or country codes; "2010s" without "the", from/between
    ranges and TMY3 are no longer place text.
  - Session: `OpenEPWError` becomes an error event with its own code and any other exception
    becomes `INTERNAL_ERROR` with a correlation id logged locally (no exception text in events),
    so the CLI no longer crashes. Following jobs with none pending changes nothing. Back keeps
    uploaded and retrieved artifacts.
  - Gates: `check_plan_request` treats TMY, TMYx and published as one typical group (the chosen
    selections decide) and keeps a model's own subset of the stated years. `next_need` keeps the
    plan review open while a runnable plan has not started.
  - Approvals: a submission that fails before the server asks for confirmation drops its one-shot
    approval. `parse_failure` keeps `details` only as a list of objects.
  - Guided plan review (blocker found in review): after a replan such as "2019 instead" the open
    review still showed the old plan while "run" submitted the new one. The review now reopens
    whenever its plans differ from the plans that run submits, and S9 asserts it. A partly failed
    run reopens the review marking plans that already started; running again submits only the
    rest. A place typed at the plan review starts a new location review; years typed before a
    product choice refresh the offers. Export continues past a job without a bundle.
  - Final branch review (second blocker in the same place): a replan that failed partway kept a
    half-built plan set under the old review, so "run" could submit an unseen plan. Plans are
    now replaced all at once, and run refuses with `GATE_REQUIRED` (and reopens the review)
    unless the open review shows exactly the plans it would submit. Population thresholds and
    place-set limits ("over 2000 people", "top 1900") are not weather years. Started plan
    hashes are kept for the session so Back after `/new` cannot restore a started plan.
  - Focused re-review of that guard: no way found to submit a plan the open review did not show
    (replan then Back, product or place change, failed replan then resume, partly failed run
    then resume, no false-refusal loops). Follow-ups: years typed at a place-set question are
    read again (a bare number is the answer), "the 2000 largest cities" is not a year, and the
    review keeps its own copy of the plans it shows.
  - CLI: `openepw chat` quiets per-request MCP SDK and httpx INFO logs and replaces characters a
    redirected Windows console cannot encode; an unknown `--session` is `SESSION_NOT_FOUND`
    (exit 2); input is read on the main thread so Ctrl-C ends the chat cleanly (exit 130 if it
    interrupts elsewhere); jobs are followed only while no form is open, for up to two minutes at
    a time before the prompt returns; `/upload` checks the size before reading the file. The final
    "session saved" line is written inside the client block so the session is always bound.
- Verification at `4c9c575` (Python 3.14.7, Windows): `pytest -q` 725 passed, 18 skipped and
  exactly the 4 known pre-existing failures (2 in `test_availability_adapters.py`, 2 in
  `test_availability_service.py`) with the one known starlette/anyio `DeprecationWarning`;
  `tests/agent` 69 passed; `ruff check .` clean; `mypy` clean (104 files); `build` produced
  the sdist and wheel.
- Manual run (2026-10-05, real network, scratch data root `.local/agent-try`): "AMY 2018 for
  Ithaca NY" geocoded to two candidates (the city and its airport), so a choice form appeared;
  the location review showed UTC-05:00 estimated from longitude; four ERA5/ERA5-Land offers were
  listed from the catalog; resuming with `--session` worked; ERA5 via Open-Meteo planned with two
  warnings, ran after "run", and completed with one EPW, no QC issue codes and the
  `simulation_ready=false` notice. That run found the log noise and encoding problem fixed above.
- Deferred, with reasons:
  - `/quit` while a job runs waits for it, because `JobRunner.close()` shuts its pool down with
    `wait=True` (P1 behaviour). A long Copernicus job therefore holds the chat open; cancelling or
    detaching jobs belongs with P4's lock and runner hardening.
  - Resuming a session prints its whole earlier transcript (tool lines included) before the open
    form; a compact resume view can come with the P4 renderer work.
  - Offers still carry no availability evidence dates (P1 deferral); the product form shows
    catalog listing status only.
  - Place-set caps and the offers location cap (P1 deferrals) are unchanged.
  - The export choice is offered whenever a job finished, even if it produced nothing; a failed
    export is reported per job.
