"""Immutable, checksum-verified prepared views under the private data root."""

import json
import re
from pathlib import Path

from ..artifacts.store import atomic_write
from ..models import OpenEPWError, digest


class VisualizationStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve() / "views"

    def _path(self, view_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", view_id):
            raise OpenEPWError("INVALID_VIEW", "Invalid visualization ID")
        return self.root / f"{view_id}.json"

    def _read(self, view_id: str) -> dict:
        try:
            envelope = json.loads(self._path(view_id).read_bytes())
            payload = envelope["payload"]
            if digest(payload) != envelope["sha256"] or payload["view_id"] != view_id:
                raise ValueError("checksum mismatch")
            return payload
        except (OSError, ValueError, KeyError, TypeError):
            raise OpenEPWError("INVALID_VIEW", "View missing or checksum invalid") from None

    def save(self, result: dict, *, limit: int = 100) -> dict:
        sources = [
            {"artifact_id": item["artifact_id"], "sha256": item["sha256"]}
            for item in result["specs"][0]["sources"]
        ]
        view_id = digest({"schema_version": result["schema_version"],
                          "request": result["request"], "sources": sources})
        payload = json.loads(json.dumps(result, allow_nan=False))
        payload["view_id"] = view_id
        for spec in payload["specs"]:
            spec["data_ref"]["view_id"] = view_id
        path = self._path(view_id)
        if path.exists():
            if self._read(view_id) != payload:
                raise OpenEPWError("INVALID_VIEW", "Existing view differs from this calculation")
        else:
            envelope = {"sha256": digest(payload), "payload": payload}
            body = json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode()
            if len(body) > 25_000_000:
                raise OpenEPWError("RESOURCE_LIMIT", "Prepared view exceeds 25 MB")
            atomic_write(path, body)
        return self.page(view_id, 0, limit)

    def page(self, view_id: str, offset: int = 0, limit: int = 100) -> dict:
        if offset < 0 or not 1 <= limit <= 200:
            raise OpenEPWError("RESOURCE_LIMIT", "Page requires offset >= 0 and limit 1..200")
        payload = self._read(view_id)
        total = len(payload["rows"])
        end = min(offset + limit, total)
        page = {"schema_version": payload["schema_version"], "view_id": view_id,
                "rows": payload["rows"][offset:end], "total_rows": total,
                "next_offset": end if end < total else None}
        if offset == 0:
            page.update({key: payload[key] for key in ("request", "specs", "warnings")})
        return page
