"""Local evidence check cadences, not upstream completeness guarantees."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import EvidenceRef


def cadence(source_id: str) -> timedelta:
    if source_id.startswith("cds-"):
        return timedelta(days=1)
    if source_id == "openmeteo-doc":
        return timedelta(days=30)
    return timedelta(days=7)


def aged(evidence: EvidenceRef, now: datetime | None = None) -> bool:
    checked = evidence.checked_at or evidence.retrieved_at
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - checked > cadence(evidence.id)
