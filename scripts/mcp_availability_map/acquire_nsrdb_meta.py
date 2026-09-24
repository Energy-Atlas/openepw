"""Opt-in, bounded coordinate-only acquisition from NLR's public NSRDB objects."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Protocol

import h5py
import numpy as np

from .nsrdb_coverage import (
    REVIEWED_MODEL_VERSION,
    REVIEWED_OBJECT_KEY,
    TMY_ID,
    load_coverage_manifest,
)

BUCKET = "https://nrel-pds-nsrdb.s3.us-west-2.amazonaws.com/"
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_REQUESTS = 12


@dataclass(frozen=True)
class SourceSpec:
    product_id: str
    selector_kind: str
    selector: str
    object_key: str

    @property
    def url(self) -> str:
        return BUCKET + self.object_key


def source_spec(product_id: str, selector: str) -> SourceSpec:
    """Resolve only the reviewed API/selector/object correspondence."""
    if product_id == TMY_ID and selector == "tdy-2023":
        return SourceSpec(product_id, "published_name", selector, REVIEWED_OBJECT_KEY)
    raise ValueError("unsupported NSRDB product selector")


class Transport(Protocol):
    def head(self, url: str, if_none_match: str | None = None) -> dict[str, object] | None: ...
    def open_range(self, url: str, start: int, end: int, etag: str) -> BinaryIO: ...


class HttpTransport:
    """Anonymous S3 requests; credentials never enter URLs or local records."""

    def head(self, url: str, if_none_match: str | None = None) -> dict[str, object] | None:
        headers = {"If-None-Match": if_none_match} if if_none_match else {}
        request = urllib.request.Request(url, method="HEAD", headers=headers)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            if error.code == 304:
                return None
            raise
        with response:
            if response.status != 200:
                raise ValueError("unexpected source HEAD status")
            return {
                "size": int(response.headers["Content-Length"]),
                "etag": response.headers["ETag"],
                "modified": response.headers["Last-Modified"],
            }

    def open_range(self, url: str, start: int, end: int, etag: str) -> BinaryIO:
        request = urllib.request.Request(
            url, headers={"Range": f"bytes={start}-{end}", "If-Match": etag}
        )
        return urllib.request.urlopen(request, timeout=60)


@dataclass
class _Budget:
    max_bytes: int
    max_requests: int
    bytes_used: int = 0
    requests_used: int = 1  # HEAD

    def claim(self, size: int) -> None:
        if size < 0 or self.bytes_used + size > self.max_bytes:
            raise ValueError("metadata byte cap exceeded")
        if self.requests_used + 1 > self.max_requests:
            raise ValueError("metadata request cap exceeded")
        self.bytes_used += size
        self.requests_used += 1


def _read_range(
    transport: Transport, spec: SourceSpec, start: int, end: int, etag: str,
    budget: _Budget, destination: BinaryIO,
) -> str:
    length = end - start + 1
    budget.claim(length)
    digest = hashlib.sha256()
    observed = 0
    with transport.open_range(spec.url, start, end, etag) as response:
        if getattr(response, "status", None) != 206:
            raise ValueError("source ignored byte range")
        while True:
            chunk = response.read(min(1024 * 1024, length - observed))
            if not chunk:
                break
            observed += len(chunk)
            if observed > length:
                raise ValueError("oversized range response")
            digest.update(chunk)
            destination.write(chunk)
            if observed == length:
                break
    if observed != length:
        raise ValueError("incomplete range transfer")
    return digest.hexdigest()


class _RangeReader(io.RawIOBase):
    def __init__(
        self, transport: Transport, spec: SourceSpec, size: int, etag: str,
        budget: _Budget, block_bytes: int,
    ) -> None:
        self.transport = transport
        self.spec = spec
        self.size = size
        self.etag = etag
        self.budget = budget
        self.block_bytes = block_bytes
        self.position = 0
        self.cache: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        self.position = (offset if whence == 0 else self.position + offset
                         if whence == 1 else self.size + offset)
        if not 0 <= self.position <= self.size:
            raise ValueError("HDF5 seek outside object")
        return self.position

    def readinto(self, buffer: bytearray) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = self.size - self.position
        output = bytearray()
        while size and self.position < self.size:
            start = self.position // self.block_bytes * self.block_bytes
            if start not in self.cache:
                end = min(self.size, start + self.block_bytes) - 1
                block = io.BytesIO()
                _read_range(self.transport, self.spec, start, end, self.etag,
                            self.budget, block)
                self.cache[start] = block.getvalue()
            current = self.cache[start]
            offset = self.position - start
            length = min(size, len(current) - offset)
            output.extend(current[offset:offset + length])
            self.position += length
            size -= length
        return bytes(output)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(payload)
        temp_path = Path(temporary.name)
    os.replace(temp_path, path)


def _stale_existing(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    for entry in document["entries"]:
        entry["stale"] = True
    _atomic_bytes(path, json.dumps(document, sort_keys=True).encode())


def _cells_and_nearest(
    meta_path: Path, dtype: np.dtype, count: int, step: float,
    probes: tuple[tuple[float, float], ...],
) -> frozenset[tuple[int, int]]:
    # A memmap keeps the file open through exception tracebacks on Windows,
    # preventing cleanup of a rejected acquisition.
    rows = np.fromfile(meta_path, dtype=dtype, count=count)
    lat = np.asarray(rows["latitude"])
    lon = np.asarray(rows["longitude"])
    if not (np.isfinite(lat).all() and np.isfinite(lon).all()
            and (np.abs(lat) <= 90).all() and (np.abs(lon) <= 180).all()):
        raise ValueError("invalid source coordinate")
    pairs = np.empty(count, dtype=[("latitude", lat.dtype), ("longitude", lon.dtype)])
    pairs["latitude"] = lat
    pairs["longitude"] = lon
    if len(np.unique(pairs)) != count:
        raise ValueError("duplicate source coordinates")
    for probe_lat, probe_lon in probes:
        lon_gap = np.abs(lon - probe_lon)
        lon_gap = np.minimum(lon_gap, 360 - lon_gap)
        distance_km = np.hypot((lat - probe_lat) * 111.2,
                               lon_gap * 111.2 * math.cos(math.radians(probe_lat)))
        if float(np.min(distance_km)) > 8:
            raise ValueError("source grid disagrees with point probe")
    columns = int(360 / step)
    row_ids = np.minimum(np.floor((lat + 90) / step).astype(np.int32), int(180 / step) - 1)
    wrapped_lon = np.where(lon == 180, -180, lon)
    column_ids = np.floor((wrapped_lon + 180) / step).astype(np.int32)
    packed = np.unique(row_ids.astype(np.int64) * columns + column_ids)
    return frozenset((int(value // columns), int(value % columns)) for value in packed)


def acquire_meta(
    spec: SourceSpec, output_root: Path, transport: Transport,
    *, probes: tuple[tuple[float, float], ...],
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    block_bytes: int = 1024 * 1024,
    step_degrees: float = 0.25,
) -> Path:
    """Acquire one exact selector's `meta` table; publish a mask only after validation."""
    if source_spec(spec.product_id, spec.selector) != spec:
        raise ValueError("unreviewed source object path")
    if not math.isfinite(step_degrees) or step_degrees <= 0 or 180 / step_degrees % 1:
        raise ValueError("invalid display resolution")
    destination = output_root / spec.product_id / spec.selector
    manifest_path = destination / "manifest.json"
    previous = None
    if manifest_path.exists():
        previous = load_coverage_manifest(manifest_path).entries[0]
    headers = transport.head(spec.url, previous.object_etag if previous else None)
    if headers is None:
        if previous is None or previous.stale:
            raise ValueError("unexpected unchanged response")
        return manifest_path
    size = int(headers["size"])
    etag = str(headers["etag"])
    if size <= 0 or not etag:
        raise ValueError("invalid source identity")
    if previous and etag == previous.object_etag and not previous.stale:
        return manifest_path
    if previous:
        _stale_existing(manifest_path)
    budget = _Budget(max_bytes=max_bytes, max_requests=max_requests)
    reader = _RangeReader(transport, spec, size, etag, budget, block_bytes)
    with h5py.File(reader, "r") as source:
        model_version = str(source.attrs["version"])
        if model_version != REVIEWED_MODEL_VERSION:
            raise ValueError("source model version disagrees with reviewed object")
        meta = source["meta"]
        if meta.ndim != 1 or meta.chunks is not None or meta.id.get_offset() is None:
            raise ValueError("unsupported source meta layout")
        if not {"latitude", "longitude"} <= set(meta.dtype.names or ()):
            raise ValueError("source meta lacks coordinates")
        offset = int(meta.id.get_offset())
        length = int(meta.id.get_storage_size())
        count = int(meta.shape[0])
        dtype = meta.dtype
        if length != count * dtype.itemsize or offset < 0 or offset + length > size:
            raise ValueError("inconsistent source meta layout")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination, delete=False) as temporary:
        temp_path = Path(temporary.name)
        try:
            meta_sha = _read_range(transport, spec, offset, offset + length - 1,
                                   etag, budget, temporary)
        except BaseException:
            temporary.close()
            temp_path.unlink(missing_ok=True)
            raise
    try:
        cells = _cells_and_nearest(temp_path, dtype, count, step_degrees, probes)
        mask = {"step_degrees": step_degrees, "cells": [list(cell) for cell in sorted(cells)]}
        mask_raw = json.dumps(mask, separators=(",", ":"), sort_keys=True).encode()
        mask_sha = hashlib.sha256(mask_raw).hexdigest()
        os.replace(temp_path, destination / "meta.bin")
        _atomic_bytes(destination / "mask.json", mask_raw)
        manifest = {
            "schema_version": 1,
            "entries": [{
                "product_id": spec.product_id,
                "source_file_id": spec.object_key,
                "source_version": model_version,
                "selector_kind": spec.selector_kind,
                "selector": spec.selector,
                "basis": "source_grid_sites",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "source_modified_at": str(headers["modified"]),
                "object_etag": etag,
                "object_size": size,
                "meta_sha256": meta_sha,
                "mask_sha256": mask_sha,
                "mask_path": "mask.json",
                "coordinate_count": count,
                "native_crs": "EPSG:4326",
                "native_longitude_convention": "-180_to_180",
                "request_count": budget.requests_used,
                "transferred_bytes": budget.bytes_used,
                "stale": False,
            }],
        }
        _atomic_bytes(manifest_path, json.dumps(manifest, indent=2, sort_keys=True).encode())
        load_coverage_manifest(manifest_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_id", choices=[TMY_ID])
    parser.add_argument("selector", help="Reviewed native selector (currently tdy-2023)")
    parser.add_argument("--output-root", type=Path, default=Path(".local/mcp-availability/nsrdb-footprints"))
    args = parser.parse_args()
    if not args.output_root.resolve().is_relative_to((Path.cwd() / ".local").resolve()):
        raise ValueError("metadata output must stay under the ignored .local tree")
    path = acquire_meta(source_spec(args.product_id, args.selector), args.output_root,
                        HttpTransport(), probes=((42.44, -76.5), (33.45, -112.07)))
    entry = load_coverage_manifest(path).entries[0]
    print(json.dumps({"manifest": str(path), "product": entry.product_id,
                      "selector": entry.selector, "sites": entry.coordinate_count,
                      "display_cells": len(entry.cells), "meta_sha256": entry.meta_sha256}))


if __name__ == "__main__":
    main()
