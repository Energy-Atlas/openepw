"""Pure rules for weather batch evidence and native fetch identity."""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse

from ..availability.models import AvailabilityResult
from ..models import Candidate, DatasetSelection, Issue, SourceRef, WeatherPlan, digest


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


def finalize_batch_rows(
    plan: WeatherPlan, manifest_outputs: list[dict[str, Any]],
    issues: list[Issue], cancelled: bool,
) -> list[dict[str, Any]]:
    """Account for every planned occurrence without inventing a weather artifact."""
    produced = {entry.get("output_id"): entry for entry in manifest_outputs}
    finalized = []
    for row in plan.batch_rows:
        entry = produced.get(row.output_id) if row.output_id else None
        related = [issue for issue in issues if (
            issue.task_id is not None and
            (issue.task_id == row.output_id or issue.task_id in row.task_ids)
        ) or (
            issue.task_id is None and issue.occurrence_index == row.occurrence_index and
            (issue.location_id is None or issue.location_id == row.requested_location_id) and
            (issue.dataset_selection is None or
             issue.dataset_selection == row.dataset_selection.model_dump(mode="json"))
        )]
        result = row.model_dump(mode="json")
        result["issue_codes"] = list(dict.fromkeys(
            [*row.issue_codes, *(issue.code for issue in related)]))
        if row.status == "planned":
            result["status"] = "succeeded" if entry else (
                "cancelled" if cancelled and not related else "failed")
            if entry:
                for key in ("artifact_id", "source", "lineage", "metadata", "raw_sha256"):
                    if key in entry:
                        result[key] = entry[key]
        finalized.append(result)
    return finalized
