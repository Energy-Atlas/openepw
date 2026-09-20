"""Bounded Stage 1 range-read of one EPW in the OEDI 5974 ZIP64 archive."""
import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from probe_providers import summarize


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        self.url = url
        self.pos = 0
        self.transferred = 0
        self.requests = []
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=-65536"}), timeout=35) as response:
            if response.status != 206:
                raise ValueError("Server did not honor Range")
            self.size = int(response.headers["Content-Range"].split("/")[-1])
            self.etag = response.headers["ETag"]
            body = response.read(65537)
            if len(body) != 65536:
                raise ValueError("Unexpected initial range size")
            self.transferred += len(body)
            self.requests.append({"range": "bytes=-65536", "status": response.status, "bytes": len(body)})

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self.pos = offset + (self.pos if whence == 1 else self.size if whence == 2 else 0)
        return self.pos

    def tell(self):
        return self.pos

    def read(self, size=-1):
        size = self.size - self.pos if size < 0 else size
        size = min(size, self.size - self.pos)
        if size <= 0:
            return b""
        if self.transferred + size > 15_000_000:
            raise ValueError("15 MB probe budget exceeded")
        span = f"bytes={self.pos}-{self.pos+size-1}"
        request = urllib.request.Request(self.url, headers={"Range": span, "If-Match": self.etag})
        with urllib.request.urlopen(request, timeout=35) as response:
            if response.status != 206:
                raise ValueError("Range ignored; refusing whole archive")
            data = response.read(size + 1)
            if len(data) != size:
                raise ValueError("Unexpected range size")
            self.requests.append({"range": span, "status": response.status, "bytes": len(data)})
        self.pos += len(data)
        self.transferred += len(data)
        return data


if __name__ == "__main__":
    endpoint = "https://data.openei.org/files/5974/RCP8.5_v1.1.zip"
    stream = RemoteZip(endpoint)
    with zipfile.ZipFile(stream) as archive:
        members = archive.infolist()
        epws = [m for m in members if m.filename.lower().endswith(".epw")]
        print("Members:", len(members), "EPWs:", len(epws))
        print("First names:", [m.filename for m in members[:8]])
        if not epws:
            raise ValueError("No direct EPW member")
        chosen = epws[0]
        if chosen.file_size > 3_000_000:
            raise ValueError("Uncompressed member exceeds probe budget")
        body = archive.read(chosen)
    Path(".local/probes/oedi_sample.epw").write_bytes(body)
    result = {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "url": endpoint, "etag": stream.etag, "archive_bytes": stream.size, "range_requests": stream.requests, "bytes_transferred": stream.transferred, "member_count": len(members), "epw_count": len(epws), "sample_member": chosen.filename, "sample_compressed_bytes": chosen.compress_size, "sample_sha256": hashlib.sha256(body).hexdigest(), "observations": summarize(body, "text/plain")}
    Path("docs/validation/2026-09-20-future-archive.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
