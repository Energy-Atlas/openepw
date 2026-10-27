"""Availability-gaps plan, items 3 and 4 (owner decisions D4 and D5, 2026-10-13): NSRDB year
lists applied throughout a mask when every probe agrees, and the ERA5-Land mask of points with
values. Synthetic data only."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from openepw.availability import (
    CatalogSnapshotRef,
    EvidenceRef,
    WeatherAvailabilityQuery,
)
from openepw.availability.coverage import GridCoverage
from openepw.availability.evaluate import evaluate
from openepw.availability.importers import normalize_analysis
from openepw.availability.store import CatalogView
from openepw.models import Location, WeatherRequest
from scripts.mcp_availability_map.era5land_present import decode_grib1

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from mcp_research.analysis import nsrdb_documented_names  # noqa: E402

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
PAGE = b"""<html><code>/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download.csv</code>
<tr><td>names</td><td>Yes</td><td>Type: comma delimited string array<br>Default: None<br>
Options: tmy, tmy-2023, tdy-2023 .</td><td>The year(s) for which data should be extracted.</td></tr>"""


def test_the_documented_names_are_read_from_an_nlr_page():
    page = nsrdb_documented_names(PAGE)
    assert page["dataset"] == "nsrdb-GOES-tmy-v4-0-0" and page["names"] == ["tmy", "tmy-2023", "tdy-2023"]
    years = nsrdb_documented_names(PAGE.replace(b"tmy, tmy-2023, tdy-2023", b"1998, 1999"))
    assert years["names"] == [1998, 1999]
    with pytest.raises(ValueError):
        nsrdb_documented_names(b"<html>no endpoint</html>")


def _bundle(second_years=(2017, 2018, 2019), names=(2017, 2018, 2019)):
    probes = {"nsrdb-a": (20.0, 80.0, (2017, 2018, 2019)), "nsrdb-b": (25.0, 85.0, second_years)}
    inventories = {key: {"location": {"lat": lat, "lon": lon},
                         "products": [{"name": "msg-iodc", "available_years_or_products": list(years)}]}
                   for key, (lat, lon, years) in probes.items()}
    inventories["nsrdb-doc-meteosat"] = {"dataset": "msg-iodc", "names": list(names)}
    evidence = [EvidenceRef(id=key, sha256="a" * 64, retrieved_at=NOW,
                            basis="documentation" if "doc" in key else "targeted_probe") for key in inventories]
    return normalize_analysis(inventories, evidence)


def test_a_documented_list_applies_only_when_every_probe_agrees():
    entries = [e for e in _bundle().entries if ":documented:" in e.id]
    assert [(e.id, e.scope.years, e.probe_location) for e in entries] == [
        ("nsrdb:msg-iodc:documented:actual", [2017, 2018, 2019], None)]
    assert entries[0].evidence_ids == ["nsrdb-doc-meteosat", "nsrdb-a", "nsrdb-b"]
    assert not [e for e in _bundle(second_years=(2017, 2018)).entries if ":documented:" in e.id]
    assert not [e for e in _bundle(names=(2016, 2017)).entries if ":documented:" in e.id]   # page lists more
    lagging = [e for e in _bundle(names=(2017, 2018)).entries if ":documented:" in e.id]     # page lags
    assert lagging[0].scope.years == [2017, 2018, 2019]


def _decision(bundle, lat, lon, years, coverage):
    request = WeatherRequest(locations=Location(lat=lat, lon=lon), years=years, product="historical")
    view = CatalogView(CatalogSnapshotRef(generation_id="synthetic", created_at=NOW), bundle)
    [option] = [o for o in evaluate(WeatherAvailabilityQuery(request=request), view, coverage).options
                if o.product.id == "nsrdb:msg-iodc"]
    return option.eligibility


def test_inside_the_mask_the_documented_list_applies():
    mask = GridCoverage.from_cells(1.0, [(row, column) for row in range(105, 120) for column in range(255, 270)])
    coverage = {"nsrdb:msg-iodc": mask}
    inside = _decision(_bundle(), 22.5, 82.5, [2018], coverage)
    assert inside.status == "supported" and inside.evidence_bases == ["documentation"]
    assert _decision(_bundle(), 22.5, 82.5, [2020], coverage).status == "unknown"
    at_probe = _decision(_bundle(), 20.0, 80.0, [2018], coverage)
    assert at_probe.status == "supported" and at_probe.evidence_bases == ["targeted_probe"]
    assert _decision(_bundle(), 40.0, 10.0, [2018], coverage).status == "excluded"


def _ibm(value: float) -> bytes:
    """IBM single-precision float for small positive test values."""
    if value == 0:
        return bytes(4)
    exponent = 64
    while value >= 1:
        value /= 16
        exponent += 1
    while value < 1 / 16:
        value *= 16
        exponent -= 1
    return bytes([exponent]) + int(value * 2 ** 24).to_bytes(3, "big")


def _grib1(present: np.ndarray, values: np.ndarray, step: float = 60.0) -> bytes:
    """A GRIB 1 message on a regular grid from 90 N and 0 E, with a bit map and 16-bit packing."""
    nj, ni = present.shape
    pds = bytearray(28)
    pds[0:3] = (28).to_bytes(3, "big")
    pds[7] = 0xC0
    gds = bytearray(32)
    gds[0:3] = (32).to_bytes(3, "big")
    gds[5] = 0
    gds[6:8], gds[8:10] = ni.to_bytes(2, "big"), nj.to_bytes(2, "big")
    gds[10:13] = (90000).to_bytes(3, "big")
    gds[17:20] = (90000 | 0x800000).to_bytes(3, "big")
    gds[20:23] = int((360 - step) * 1000).to_bytes(3, "big")
    gds[23:25] = gds[25:27] = int(step * 1000).to_bytes(2, "big")
    bits = np.packbits(present.ravel())
    bms = (6 + len(bits)).to_bytes(3, "big") + bytes([0]) + (0).to_bytes(2, "big") + bits.tobytes()
    reference = 200.0
    packed = np.round(values[present] - reference).astype(">u2").tobytes()
    bds = (11 + len(packed)).to_bytes(3, "big") + bytes([0]) + (0).to_bytes(2, "big") + _ibm(reference) \
        + bytes([16]) + packed
    body = bytes(pds) + bytes(gds) + bms + bds + b"7777"
    return b"GRIB" + (8 + len(body)).to_bytes(3, "big") + bytes([1]) + body


def test_grib1_bit_map_and_values_decode():
    present = np.zeros((4, 6), dtype=bool)                  # 90, 30, -30, -90 N by 0-300 E
    present[1, [0, 1, 4]] = True
    values = np.zeros((4, 6))
    values[1, [0, 1, 4]] = [280, 290, 300]
    found, decoded, grid = decode_grib1(_grib1(present, values))
    assert (grid["ni"], grid["nj"], grid["la1"], grid["di"]) == (6, 4, 90.0, 60.0)
    assert (found == present).all()
    assert np.allclose(decoded[present], [280, 290, 300]) and np.isnan(decoded[~present]).all()
    with pytest.raises(ValueError):
        decode_grib1(b"GRIB" + bytes(3) + bytes([2]) + bytes(20))
