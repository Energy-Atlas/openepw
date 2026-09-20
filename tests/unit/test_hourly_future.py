import io
import zipfile

import httpx
import pytest
from test_epw import synthetic

from openepw.config import RuntimeConfig
from openepw.generation.climate_profile import select_profile
from openepw.generation.hourly_archive import RemoteZip
from openepw.models import OpenEPWError
from openepw.providers.http import HttpClient


def test_remote_zip_range_crc_and_budget(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("test.epw", b"synthetic-weather" * 100)
    raw = buffer.getvalue()

    def handler(request):
        span = request.headers["Range"].removeprefix("bytes=")
        if span.startswith("-"):
            start = max(0, len(raw) + int(span))
            end = len(raw) - 1
        else:
            start, end = map(int, span.split("-"))
        return httpx.Response(
            206,
            content=raw[start : end + 1],
            headers={"ETag": "fixed", "Content-Range": f"bytes {start}-{end}/{len(raw)}"},
        )

    h = HttpClient(RuntimeConfig(data_root=tmp_path), transport=httpx.MockTransport(handler))
    with zipfile.ZipFile(RemoteZip("https://data.openei.org/test.zip", h)) as archive:
        assert archive.read("test.epw") == b"synthetic-weather" * 100
    bad = HttpClient(
        RuntimeConfig(data_root=tmp_path),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=raw)),
    )
    with pytest.raises(OpenEPWError):
        RemoteZip("https://data.openei.org/test.zip", bad)


def test_typical_medoid_and_coherent_hot_shock():
    years = {y: synthetic(y, 8760) for y in (2045, 2046, 2047)}
    for y, t in [(2045, 10), (2046, 20), (2047, 30)]:
        years[y].data["dry_bulb"] = t
    assert select_profile(years, {}, "typical", {}) == [2046]
    assert select_profile(years, {}, "extreme", {"type": "hot", "mode": "shock"}) == [2047]
    assert select_profile(years, {}, "extreme", {"type": "cold", "mode": "shock"}) == [2045]
    assert select_profile(years, {}, "ensemble", {}) == [2045, 2046, 2047]
