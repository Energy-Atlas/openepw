"""Immutable SQLite catalog generations with atomic activation."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .models import (
    AvailabilityEntry,
    CatalogBundle,
    CatalogSnapshotRef,
    EvidenceRef,
    ProductRecord,
    ReviewAnnotation,
    SiteRecord,
)


class CatalogImportError(ValueError):
    """A source bundle failed validation; the active generation remains intact."""


@dataclass(frozen=True)
class CatalogView:
    snapshot: CatalogSnapshotRef
    bundle: CatalogBundle


_TABLES = (
    ("evidence", EvidenceRef),
    ("products", ProductRecord),
    ("sites", SiteRecord),
    ("entries", AvailabilityEntry),
    ("reviews", ReviewAnnotation),
)


class CatalogStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "catalog.sqlite3"
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS generations (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS active (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), generation_id TEXT NOT NULL REFERENCES generations(id))")
            db.execute("CREATE TABLE IF NOT EXISTS stale_sources (source_id TEXT PRIMARY KEY)")
            for name, _ in _TABLES:
                db.execute(f"CREATE TABLE IF NOT EXISTS {name} (generation_id TEXT NOT NULL REFERENCES generations(id), id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (generation_id, id))")

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    @staticmethod
    def _validate(bundle: CatalogBundle):
        ids = {}
        for name, _ in _TABLES:
            records = getattr(bundle, name)
            keys = [r.catalog_url if name == "reviews" else r.id for r in records]
            if len(keys) != len(set(keys)):
                raise CatalogImportError(f"Duplicate {name} identity")
            ids[name] = set(keys)
        for e in bundle.evidence:
            if e.source_url and urlsplit(e.source_url).scheme not in ("http", "https"):
                raise CatalogImportError("Evidence URL must be HTTP(S)")
        for p in bundle.products:
            if not set(p.evidence_ids) <= ids["evidence"]:
                raise CatalogImportError("Product has dangling evidence")
        for s in bundle.sites:
            if s.product_id not in ids["products"] or not set(s.evidence_ids) <= ids["evidence"]:
                raise CatalogImportError("Site has dangling product/evidence")
        for e in bundle.entries:
            if e.product_id not in ids["products"] or (e.site_id and e.site_id not in ids["sites"]):
                raise CatalogImportError("Entry has dangling product/site")
            if not set(e.evidence_ids) <= ids["evidence"]:
                raise CatalogImportError("Entry has dangling evidence")
        for r in bundle.reviews:
            if r.product_id not in ids["products"]:
                raise CatalogImportError("Review has dangling product")

    def stage(self, bundle: CatalogBundle) -> CatalogSnapshotRef:
        self._validate(bundle)
        generation_id = uuid.uuid4().hex
        snapshot = CatalogSnapshotRef(
            generation_id=generation_id,
            source_checksums={e.id: e.sha256 for e in bundle.evidence},
            created_at=datetime.now(timezone.utc),
        )
        try:
            with self._connect() as db:
                db.execute("INSERT INTO generations (id, snapshot) VALUES (?, ?)",
                           (generation_id, snapshot.model_dump_json()))
                for name, _ in _TABLES:
                    for record in getattr(bundle, name):
                        key = record.catalog_url if name == "reviews" else record.id
                        db.execute(f"INSERT INTO {name} (generation_id, id, body) VALUES (?, ?, ?)",
                                   (generation_id, key, record.model_dump_json()))
        except sqlite3.Error as exc:
            raise CatalogImportError("Catalog staging failed") from exc
        return snapshot

    def activate(self, generation_id: str) -> CatalogSnapshotRef:
        with self._connect() as db:
            row = db.execute("SELECT snapshot FROM generations WHERE id = ?", (generation_id,)).fetchone()
            if row is None:
                raise CatalogImportError("Unknown catalog generation")
            snapshot = CatalogSnapshotRef.model_validate_json(row[0])
            snapshot.activated_at = datetime.now(timezone.utc)
            db.execute("UPDATE generations SET snapshot = ? WHERE id = ?",
                       (snapshot.model_dump_json(), generation_id))
            db.execute("INSERT INTO active (singleton, generation_id) VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET generation_id = excluded.generation_id",
                       (generation_id,))
        return snapshot

    def active(self) -> CatalogView | None:
        with self._connect() as db:
            row = db.execute("SELECT g.id, g.snapshot FROM active a JOIN generations g ON g.id = a.generation_id WHERE a.singleton = 1").fetchone()
            if row is None:
                return None
            generation_id, raw_snapshot = row
            contents = {}
            for name, kind in _TABLES:
                records = db.execute(f"SELECT body FROM {name} WHERE generation_id = ? ORDER BY id",
                                     (generation_id,)).fetchall()
                contents[name] = [kind.model_validate(json.loads(r[0])) for r in records]
            stale = [row[0] for row in db.execute("SELECT source_id FROM stale_sources ORDER BY source_id")]
        snapshot = CatalogSnapshotRef.model_validate_json(raw_snapshot)
        snapshot.stale_sources = sorted(set(snapshot.stale_sources) | set(stale))
        return CatalogView(snapshot,
                           CatalogBundle(**contents))

    def mark_stale(self, source_id: str):
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO stale_sources (source_id) VALUES (?)", (source_id,))

    def clear_stale(self, source_id: str):
        with self._connect() as db:
            db.execute("DELETE FROM stale_sources WHERE source_id = ?", (source_id,))
