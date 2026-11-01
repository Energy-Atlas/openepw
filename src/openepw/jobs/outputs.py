"""The outputs of one weather job, read from its verified manifest (or its plan while it runs).

Each row says which place, product and year an output is, its status and, when it succeeded,
its artifact. Conversations use these rows to find "the 2016 file" instead of guessing from
artifact order or file names.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from ..models import OpenEPWError

MAX_ROWS = 1000


def _year(start: str | None, end: str | None) -> int | None:
    """The calendar year a period covers exactly, else None."""
    if not start or not end:
        return None
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.year == last.year and (first.month, first.day, last.month, last.day) == (1, 1, 12, 31):
        return first.year
    return None


def job_outputs(runner: Any, job_id: str) -> dict[str, Any]:
    """One row per planned occurrence of a weather job, with its status and artifact.

    Rows come from the job's checksum-verified manifest once it finished, else from its plan
    (status ``pending``). Status is ``succeeded``, ``failed``, ``cancelled``, ``unsupported``,
    ``unresolved`` or ``pending``; only succeeded rows name an artifact.
    """
    job = runner.store.get(job_id)
    if job.kind != "weather":
        raise OpenEPWError("INVALID_REQUEST", "Outputs are listed for weather jobs only")
    plan = runner.store.plan(job_id)
    places = {point.key: point for point in runner.service.locations(plan.request)}
    names = {output.id: output.name for output in plan.outputs if output.id}
    refs = {ref.id: ref for ref in (job.bundle.weather if job.bundle else [])}
    if job.bundle is not None:
        _, path = runner.service.artifacts.resolve(job.bundle.manifest.id)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        rows = manifest.get("batch_rows")
        if not isinstance(rows, list):        # plans made before batch rows: one row per output
            produced = {entry.get("output_id"): entry.get("artifact_id") for entry in manifest.get("outputs", [])}
            rows = [{"occurrence_index": output.occurrence_index or 0,
                     "requested_location_id": output.requested_location_id,
                     "dataset_selection": (output.dataset_selection.model_dump(mode="json")
                                           if output.dataset_selection else {}),
                     "output_id": output.id,
                     "status": "succeeded" if produced.get(output.id) else "failed",
                     "artifact_id": produced.get(output.id), "issue_codes": []}
                    for output in plan.outputs]
    else:
        rows = [{**row.model_dump(mode="json"), "status": "pending" if row.status == "planned" else row.status}
                for row in plan.batch_rows]
    outputs = []
    for row in rows[:MAX_ROWS]:
        place = places.get(row.get("requested_location_id", ""))
        selection = row.get("dataset_selection") or {}
        artifact_id = row.get("artifact_id") if row.get("status") == "succeeded" else None
        ref = refs.get(artifact_id) if artifact_id else None
        start, end = row.get("period_start"), row.get("period_end")
        outputs.append({
            "output_id": row.get("output_id"),
            "occurrence_index": row.get("occurrence_index"),
            "place": {"name": place.name if place else None,
                      "lat": place.lat if place else None, "lon": place.lon if place else None},
            "product": plan.request.product,
            "provider": selection.get("provider"), "dataset": selection.get("dataset"),
            "product_id": selection.get("product_id"),
            "year": _year(start, end), "period_start": start, "period_end": end,
            "status": row.get("status"),
            "artifact_id": artifact_id if ref is not None else None,
            "filename": names.get(row.get("output_id") or "") if ref is not None else None,
            "bytes": ref.bytes if ref is not None else None,
            "sha256": ref.sha256 if ref is not None else None,
            "issue_codes": list(row.get("issue_codes") or []),
        })
    counts: dict[str, int] = {}
    for output in outputs:
        counts[output["status"]] = counts.get(output["status"], 0) + 1
    return {"job_id": job.id, "state": job.state, "retry_of": job.retry_of, "plan_hash": job.plan_hash,
            "outputs": outputs, "total": len(rows), "counts": counts}
