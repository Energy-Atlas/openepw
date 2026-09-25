"""NOAA report gaps remain visible through EPW artifacts and QC."""

import json

import httpx
import pandas as pd

from openepw.config import RuntimeConfig
from openepw.epw import read_epw
from openepw.models import Candidate, DiscoveryResult, Location, SourceRef, WeatherRequest
from openepw.providers.http import HttpClient
from openepw.providers.noaa_isd import NOAAProvider
from openepw.service import WeatherService


def _execute(tmp_path, policy):
    row = {"DATE": "2024-01-01T01:00:00", "TMP": "+0200,1",
           "DEW": "+0100,1", "WND": "180,1,N,0020,1"}
    config = RuntimeConfig(data_root=tmp_path)
    http = HttpClient(config, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[row])))
    service = WeatherService(config, http=http, providers=[NOAAProvider()])
    location = Location(lat=42, lon=-76)
    request = WeatherRequest(locations=location, start="2024-01-01", end="2024-01-01",
                             providers=["noaa"], required_variables=["dry_bulb"],
                             missing_policy=policy)
    source = SourceRef(provider="noaa", dataset="ISD global-hourly", identity="A00002",
                       location=location, provisional=False)
    candidate = Candidate(id="noaa:A00002", location_id=location.key, product_id="A00002",
                          source=source, weather_types=["historical", "amy"],
                          variables=["dry_bulb"])
    discovery = DiscoveryResult(locations=[location], candidates=[candidate],
                                selected_candidate_ids=[candidate.id])
    plan = service.plan(request, discovery=discovery)
    return service.execute(plan)


def test_noaa_gap_warn_emits_sentinel_qc_and_not_simulation_ready(tmp_path):
    bundle = _execute(tmp_path, "warn")
    assert len(bundle.weather) == 1
    epw = (tmp_path / bundle.weather[0].path).read_text()
    rows = [line.split(",") for line in epw.splitlines()[8:]]
    assert len(rows) == 24
    assert rows[0][6] == "20"
    assert rows[1][6] == "99.9"
    assert all(value.lower() not in ("none", "nan") for row in rows for value in row[6:])
    parsed = read_epw(tmp_path / bundle.weather[0].path)
    assert pd.isna(parsed.data.dry_bulb.iloc[1])
    qc = json.loads((tmp_path / bundle.qc.path).read_text())
    assert any(issue["code"] == "MISSING_CRITICAL_VARIABLE" and
               issue["field"] == "dry_bulb" for issue in qc[0]["issues"])
    manifest = json.loads((tmp_path / bundle.manifest.path).read_text())
    assert manifest["simulation_ready"] is False


def test_noaa_gap_error_policy_does_not_emit_epw(tmp_path):
    bundle = _execute(tmp_path, "error")
    assert bundle.weather == []
    assert any(issue.code == "MISSING_CRITICAL_VARIABLE" and
               issue.severity == "error" for issue in bundle.issues)
    manifest = json.loads((tmp_path / bundle.manifest.path).read_text())
    assert manifest["simulation_ready"] is False
