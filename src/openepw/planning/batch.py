"""Pure rules for weather batch evidence and native fetch identity."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from ..availability.models import AvailabilityResult
from ..models import Candidate, DatasetSelection, SourceRef, digest


def fetch_task_key(source: SourceRef, parameters: dict[str, Any]) -> str:
    """Preserve the v0.1 task digest for the exact source request."""
    return digest({"source": source.model_dump(mode="json"),
                   "parameters": parameters, "version": "0.1"})


def exact_published_url(candidate: Candidate) -> bool:
    """Only a reviewed OneBuilding HTTPS product path can omit query location."""
    return exact_published_source(candidate.source, candidate.product_id)


def exact_published_source(source: SourceRef, product_id: str | None) -> bool:
    """Validate a location-free fetch without trusting an arbitrary plan URL."""
    parsed = urlparse(source.citation or "")
    return (source.provider == "onebuilding" and
            parsed.scheme == "https" and parsed.netloc == "climate.onebuilding.org" and
            bool(source.identity) and parsed.path == source.identity and
            product_id == parsed.path.lstrip("/") and
            parsed.path.endswith(".zip") and ".." not in parsed.path.split("/") and
            not parsed.query and not parsed.fragment)


def missing_selection_status(
    availability: AvailabilityResult | None, occurrence: int,
    selection: DatasetSelection | None,
) -> Literal["unsupported", "unresolved"]:
    """A current explicit exclusion is different from absent or stale evidence."""
    if availability is None:
        return "unresolved"
    options = [option for option in availability.options
               if option.occurrence_index == occurrence and
               (selection is None or (option.product.provider == selection.provider and
                                      option.product.dataset == selection.dataset))]
    if options and all(option.eligibility.status == "excluded" and
                       not option.eligibility.stale for option in options):
        return "unsupported"
    return "unresolved"
