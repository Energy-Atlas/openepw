import hashlib
import json
import os
import uuid
from pathlib import Path

from ..models import ArtifactRef, OpenEPWError


def atomic_write(path: Path, body: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("wb") as file:
            file.write(body)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class ArtifactStore:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def write(self, bundle_id, name, body, role, media_type="application/json"):
        if not bundle_id.isalnum() or "/" in name or "\\" in name or name in (".", ".."):
            raise OpenEPWError("INVALID_ARTIFACT", "Unsafe artifact name")
        relative = Path("jobs") / bundle_id / name
        path = self.root / relative
        atomic_write(path, body)
        ref = ArtifactRef(
            id=uuid.uuid4().hex,
            path=relative.as_posix(),
            media_type=media_type,
            bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            role=role,
        )
        atomic_write(self.root / "artifacts" / f"{ref.id}.json", ref.model_dump_json().encode())
        return ref

    def json(self, bundle_id, name, value, role):
        return self.write(
            bundle_id, name, json.dumps(value, indent=2, allow_nan=False).encode(), role
        )

    def resolve(self, artifact_id):
        if not artifact_id.isalnum() or len(artifact_id) != 32:
            raise OpenEPWError("INVALID_ARTIFACT", "Invalid artifact identifier")
        try:
            ref = ArtifactRef.model_validate_json(
                (self.root / "artifacts" / f"{artifact_id}.json").read_bytes()
            )
            path = (self.root / ref.path).resolve()
            if not path.is_relative_to(self.root):
                raise ValueError("outside root")
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != ref.sha256:
                raise ValueError("checksum changed")
            return ref, path
        except (OSError, ValueError):
            raise OpenEPWError("INVALID_ARTIFACT", "Artifact missing or checksum invalid") from None
