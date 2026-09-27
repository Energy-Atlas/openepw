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


def export_compact_chain(runner, job_ids: list[str]) -> ArtifactRef:
    """Export the verified union of an original weather job and its retries."""
    if not 2 <= len(job_ids) <= 10 or len(set(job_ids)) != len(job_ids):
        raise OpenEPWError("EXPORT_UNAVAILABLE", "A bounded retry chain is required")
    return _export_union(runner, [job_ids], "openepw-compact-chain-v1:" + ":".join(job_ids))


def export_compact_groups(runner, groups: list[list[str]]) -> ArtifactRef:
    """Export the verified union of independent weather jobs, each with its own retry chain.

    A chat request that mixes actual-year and typical-year products runs one job per kind.
    """
    flat = [job_id for group in groups for job_id in group]
    if (not 2 <= len(groups) <= 4 or any(not 1 <= len(group) <= 10 for group in groups)
            or len(set(flat)) != len(flat)):
        raise OpenEPWError("EXPORT_UNAVAILABLE", "Bounded independent weather jobs are required")
    return _export_union(runner, groups, "openepw-compact-groups-v1:" + "|".join(
        ":".join(group) for group in groups))


def _export_union(runner, groups: list[list[str]], identity: str) -> ArtifactRef:
    job_ids = [job_id for group in groups for job_id in group]
    artifacts = runner.service.artifacts
    rows_by_key: dict[str, dict] = {}
    refs = {}
    sources = []
    chained = [(group, index, job_id) for group in groups for index, job_id in enumerate(group)]
    for group, index, job_id in chained:
        job = runner.store.get(job_id)
        if job.kind != "weather" or job.state not in (
            "completed", "partially_completed", "failed", "cancelled"
        ) or job.bundle is None:
            raise OpenEPWError("EXPORT_UNAVAILABLE", "Finished weather jobs are required")
        if index and job.retry_of != group[index - 1]:
            raise OpenEPWError("EXPORT_UNAVAILABLE", "Jobs are not one retry chain")
        _, manifest_path = artifacts.resolve(job.bundle.manifest.id)
        _, qc_path = artifacts.resolve(job.bundle.qc.id)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = manifest.get("batch_rows")
        if not isinstance(rows, list):
            raise OpenEPWError("EXPORT_UNAVAILABLE", "Batch mapping is unavailable")
        refs.update({ref.id: ref for ref in job.bundle.weather})
        sources.append((job_id, manifest_path, qc_path))
        for row in rows:
            key = row.get("output_id") or json.dumps([
                row.get("occurrence_index"), row.get("dataset_selection"),
                row.get("period_start"), row.get("period_end"),
            ], sort_keys=True)
            previous = rows_by_key.get(key)
            if previous is None or row.get("status") == "succeeded" or (
                previous.get("status") != "succeeded"
            ):
                rows_by_key[key] = row

    export_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    record = artifacts.root / "artifacts" / f"{export_id}.json"
    if record.exists():
        ref, _ = artifacts.resolve(export_id)
        return ref
    members: dict[str, Path] = {}
    mapping = []
    for row in rows_by_key.values():
        artifact_id = row.get("artifact_id") or ""
        member = ""
        if artifact_id:
            if artifact_id not in refs:
                raise OpenEPWError("INVALID_ARTIFACT", "Retry artifact mapping is incomplete")
            _, path = artifacts.resolve(artifact_id)
            output_id = row.get("output_id")
            if not isinstance(output_id, str) or len(output_id) != 64:
                raise OpenEPWError("INVALID_ARTIFACT", "Batch output identity is invalid")
            member = f"weather/{output_id}.epw"
            members[member] = path
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
    temporary = artifacts.root / "jobs" / job_ids[-1] / f".tmp-{uuid.uuid4().hex}.zip"
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=MAPPING_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(mapping)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as archive:
            archive.writestr("mapping.csv", stream.getvalue())
            archive.writestr("manifest.json", json.dumps({
                "job_ids": job_ids, "batch_rows": list(rows_by_key.values()),
                **({"job_groups": groups} if len(groups) > 1 else {}),
            }, sort_keys=True))
            for job_id, manifest_path, qc_path in sources:
                archive.write(manifest_path, f"manifests/{job_id}.json")
                archive.write(qc_path, f"qc/{job_id}.json")
            for member, path in members.items():
                archive.write(path, member)
        return artifacts.register_file(job_ids[-1], "compact.zip", temporary,
                                       "compact_export", "application/zip", export_id)
    finally:
        temporary.unlink(missing_ok=True)
