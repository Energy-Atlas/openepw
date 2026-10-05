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
            event = Event(seq=seq, type=type, text=text, data=data or {})
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
