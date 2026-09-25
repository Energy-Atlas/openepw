"""Explicit compact export of verified normalized weather artifacts."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path

from ..models import ArtifactRef, OpenEPWError

MAPPING_FIELDS = (
    "occurrence_index", "requested_location_id", "dataset", "product_id",
    "period_start", "period_end", "status", "output_id", "task_ids",
    "artifact_id", "compact_member", "issue_codes",
)


def export_compact(runner, job_id: str) -> ArtifactRef:
    job = runner.store.get(job_id)
    if job.kind != "weather" or job.state not in (
        "completed", "partially_completed", "failed", "cancelled"
    ) or job.bundle is None:
        raise OpenEPWError("EXPORT_UNAVAILABLE", "Finished weather job required")
    service = runner.service
    artifacts = service.artifacts
    plan = runner.store.plan(job_id)
    _, manifest_path = artifacts.resolve(job.bundle.manifest.id)
    _, qc_path = artifacts.resolve(job.bundle.qc.id)
    manifest = json.loads(manifest_path.read_text())
    rows = manifest.get("batch_rows")
    if not isinstance(rows, list):
        raise OpenEPWError("EXPORT_UNAVAILABLE", "Batch mapping is unavailable")
    outputs = {entry.get("artifact_id"): entry for entry in manifest["outputs"]}
    weather = {ref.id: ref for ref in job.bundle.weather}
    resolved: dict[str, Path] = {}
    for artifact_id in weather:
        _, resolved[artifact_id] = artifacts.resolve(artifact_id)
    members: dict[str, Path] = {}
    equivalents: dict[str, str] = {}
    mapping = []
    for row in rows:
        artifact_id = row.get("artifact_id", "")
        member = ""
        if artifact_id:
            ref = weather.get(artifact_id)
            entry = outputs.get(artifact_id)
            if ref is None or entry is None:
                raise OpenEPWError("INVALID_ARTIFACT", "Batch artifact mapping is incomplete")
            identity = json.dumps({
                "tasks": row["task_ids"],
                "missing_policy": plan.request.missing_policy,
                "leap_policy": manifest["leap_policy"],
                "skip_feb_29": plan.request.skip_feb_29,
                "hybrid_assignments": plan.request.hybrid_policy.assignments,
                "source": entry.get("source"),
                "lineage": entry.get("lineage"),
                "sha256": ref.sha256,
            }, sort_keys=True, separators=(",", ":"))
            key = hashlib.sha256(identity.encode()).hexdigest()
            member = equivalents.get(key, "")
            if not member:
                output_id = row.get("output_id")
                if not isinstance(output_id, str) or len(output_id) != 64:
                    raise OpenEPWError("INVALID_ARTIFACT", "Batch output identity is invalid")
                member = f"weather/{output_id}.epw"
                equivalents[key] = member
                members[member] = resolved[artifact_id]
        selection = row["dataset_selection"]
        mapping.append({
            "occurrence_index": row["occurrence_index"],
            "requested_location_id": row["requested_location_id"],
            "dataset": selection["dataset"],
            "product_id": selection.get("product_id") or "",
            "period_start": row.get("period_start") or "",
            "period_end": row.get("period_end") or "",
            "status": row["status"],
            "output_id": row.get("output_id") or "",
            "task_ids": ";".join(row.get("task_ids", [])),
            "artifact_id": artifact_id,
            "compact_member": member,
            "issue_codes": ";".join(row.get("issue_codes", [])),
        })
    export_id = hashlib.sha256(f"openepw-compact-v1:{job_id}".encode()).hexdigest()[:32]
    record = artifacts.root / "artifacts" / f"{export_id}.json"
    if record.exists():
        ref, _ = artifacts.resolve(export_id)
        return ref
    temporary = artifacts.root / "jobs" / job_id / f".tmp-{uuid.uuid4().hex}.zip"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=MAPPING_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(mapping)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as archive:
            archive.writestr("mapping.csv", stream.getvalue())
            archive.write(manifest_path, "manifest.json")
            archive.write(qc_path, "qc.json")
            for member, path in members.items():
                archive.write(path, member)
        return artifacts.register_file(job_id, "compact.zip", temporary,
                                       "compact_export", "application/zip", export_id)
    finally:
        temporary.unlink(missing_ok=True)
