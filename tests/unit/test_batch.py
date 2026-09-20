import hashlib

import pandas as pd

from openepw.config import RuntimeConfig
from openepw.dataset import WeatherDataset
from openepw.models import (
    Candidate,
    HybridPolicy,
    Location,
    SourceRef,
    VariableLineage,
    WeatherRequest,
)
from openepw.providers.base import ProviderResult
from openepw.service import WeatherService


class StationProvider:
    name = "station"

    def __init__(self):
        self.calls = 0

    def discover(self, request, location, http):
        source = SourceRef(
            provider=self.name,
            dataset="synthetic",
            identity=str(int(location.lat) % 11),
            location=Location(lat=int(location.lat) % 11, lon=0),
            provisional=False,
        )
        return [
            Candidate(
                id=self.name + location.key,
                location_id=location.key,
                source=source,
                variables=["dry_bulb", "ghi"],
            )
        ]

    def fetch(self, task, http):
        self.calls += 1
        frame = pd.DataFrame(
            {"dry_bulb": [20.0] * 24, "ghi": [0.0] * 24},
            index=pd.date_range("2024-01-01T01:00Z", periods=24, freq="h"),
        )
        lineage = {
            v: VariableLineage(
                variable=v, source=task.source, raw_sha256=hashlib.sha256(b"synthetic").hexdigest()
            )
            for v in frame
        }
        return ProviderResult(
            WeatherDataset(data=frame, location=task.source.location, lineage=lineage),
            task.source,
            b"synthetic",
        )


def test_73_requests_reuse_11_verified_sources(tmp_path):
    p = StationProvider()
    s = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[p])
    r = WeatherRequest(
        locations=[Location(lat=i, lon=0) for i in range(73)], start="2024-01-01", end="2024-01-01"
    )
    plan = s.plan(r)
    assert len(plan.tasks) == 11
    b = s.execute(plan)
    assert p.calls == 11
    assert len(b.weather) == 11
    assert len(plan.outputs) == 73


def test_explicit_hybrid_uses_assigned_source(tmp_path):
    import pytest

    from openepw.models import OpenEPWError
    from openepw.planning.hybrid import combine

    first = StationProvider()
    second = StationProvider()
    second.name = "solar"
    s = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[first, second])
    request = WeatherRequest(
        locations=Location(lat=1, lon=0),
        start="2024-01-01",
        end="2024-01-01",
        hybrid_policy=HybridPolicy(
            enabled=True, assignments={"dry_bulb": "station", "ghi": "solar"}
        ),
    )
    plan = s.plan(request)
    assert len(plan.tasks) == 2
    b = s.execute(plan)
    assert len(b.weather) == 1
    import json

    manifest = json.loads((tmp_path / b.manifest.path).read_text())
    assert manifest["outputs"][0]["lineage"]["ghi"]["source"]["provider"] == "solar"
    a = first.fetch(plan.tasks[0], s.http).dataset
    z = second.fetch(plan.tasks[1], s.http).dataset
    z.data.index = z.data.index + pd.Timedelta(hours=1)
    with pytest.raises(OpenEPWError):
        combine({"station": a, "solar": z}, request.hybrid_policy.assignments)


def test_subhourly_missing_state_is_not_silently_filled():
    import numpy as np

    from openepw.planning.hybrid import hourly

    frame = pd.DataFrame(
        {"dry_bulb": [20, np.nan], "wind_direction": [180, np.nan], "ghi": [100, 100]},
        index=pd.date_range("2024-01-01T00:30Z", periods=2, freq="30min"),
    )
    result = hourly(
        WeatherDataset(data=frame, location=Location(lat=0, lon=0), interval_minutes=30)
    )
    assert np.isnan(result.data.dry_bulb.iloc[0])
    assert np.isnan(result.data.wind_direction.iloc[0])
    assert result.data.ghi.iloc[0] == 200
