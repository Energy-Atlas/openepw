"""Bounded, opt-in source metadata refresh."""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from openepw.models import Issue

from .models import AvailabilityQuery, CatalogBundle, EvidenceRef
from .store import CatalogStore

_locks_guard = threading.Lock()
_source_locks: dict[tuple[str, str], threading.Lock] = {}


def _source_lock(store: CatalogStore, source_id: str) -> threading.Lock:
    key = (str(store.root.resolve()), source_id)
    with _locks_guard:
        return _source_locks.setdefault(key, threading.Lock())


def _replace_source(current: CatalogBundle, source_id: str, updated: CatalogBundle) -> CatalogBundle:
    old_products = {p.id for p in current.products if source_id in p.evidence_ids}
    return CatalogBundle(
        evidence=[e for e in current.evidence if e.id != source_id] + updated.evidence,
        products=[p for p in current.products if p.id not in old_products] + updated.products,
        sites=[s for s in current.sites if s.product_id not in old_products] + updated.sites,
        entries=[e for e in current.entries if e.product_id not in old_products] + updated.entries,
        reviews=[r for r in current.reviews if r.product_id not in old_products] + updated.reviews,
    )


def _save_raw(root: Path, body: bytes, checksum: str):
    raw_root = root / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    target = raw_root / f"{checksum}.body"
    if target.exists():
        return
    with tempfile.NamedTemporaryFile(dir=raw_root, delete=False) as temporary:
        temporary.write(body)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, target)


def refresh_if_relevant(
    query: AvailabilityQuery,
    store: CatalogStore,
    http,
    source_ids: set[str],
    normalizer: Callable[[str, bytes, EvidenceRef], CatalogBundle],
) -> list[Issue]:
    if query.refresh == "never":
        return []
    # The caller supplies only sources whose refreshed facts could affect this decision.
    issues: list[Issue] = []
    for source_id in sorted(source_ids):
        with _source_lock(store, source_id):
            view = store.active()
            if view is None:
                issues.append(Issue(code="CATALOG_UNAVAILABLE", message="No active catalog generation"))
                continue
            source = next((item for item in view.bundle.evidence if item.id == source_id), None)
            if source is None or not source.source_url:
                issues.append(Issue(code="SOURCE_UNAVAILABLE", message=f"No refresh URL for {source_id}"))
                continue
            cadence = timedelta(days=1 if source_id.startswith("cds-") else 7)
            if datetime.now(timezone.utc) - (source.checked_at or source.retrieved_at) < cadence:
                continue
            try:
                body, headers, status = http.request(
                    "GET", source.source_url,
                    headers={"If-None-Match": source.etag} if source.etag else None,
                    limit=50_000_000, max_retries=0, allow_not_modified=True,
                )
                if status == 304:
                    unchanged = view.bundle.model_copy(deep=True)
                    next(item for item in unchanged.evidence if item.id == source_id).checked_at = (
                        datetime.now(timezone.utc)
                    )
                    staged = store.stage(unchanged)
                    store.activate(staged.generation_id)
                    continue
                bundle = normalizer(source_id, body, source)
                checksum = hashlib.sha256(body).hexdigest()
                refreshed = next((e for e in bundle.evidence if e.id == source_id), None)
                if refreshed is None:
                    raise ValueError("Normalizer omitted source evidence")
                refreshed.sha256 = checksum
                refreshed.retrieved_at = datetime.now(timezone.utc)
                refreshed.checked_at = refreshed.retrieved_at
                refreshed.etag = headers.get("etag", refreshed.etag)
                refreshed.source_url = refreshed.source_url or source.source_url
                merged = _replace_source(view.bundle, source_id, bundle)
                snapshot = store.stage(merged)
                _save_raw(store.root, body, checksum)
                store.activate(snapshot.generation_id)
            except Exception:
                issues.append(Issue(code="REFRESH_FAILED", message=f"Refresh failed for {source_id}; using last good snapshot"))
    return issues
