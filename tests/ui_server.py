"""Offline provider fixture server. NEVER imported by production code."""

import hashlib
import os
from pathlib import Path

import pandas as pd

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.dataset import WeatherDataset
from openepw.models import Candidate, Location, SourceRef, VariableLineage
from openepw.providers.base import ProviderResult
from openepw.service import WeatherService


class FixtureProvider:
    name = "openmeteo"

    def discover(self, request, location, http):
        source = SourceRef(
            provider=self.name,
            dataset="synthetic browser test",
            identity="fixture",
            location=location,
            provisional=False,
        )
        return [
            Candidate(
                id="fixture-" + location.key,
                location_id=location.key,
                source=source,
                variables=[
                    "dry_bulb",
                    "dew_point",
                    "relative_humidity",
                    "pressure",
                    "ghi",
                    "dni",
                    "dhi",
                    "wind_speed",
                    "wind_direction",
                ],
            )
        ]

    def fetch(self, task, http):
        start = task.parameters["start"]
        end = task.parameters["end"]
        index = pd.date_range(
            pd.Timestamp(start, tz="UTC") + pd.Timedelta(hours=1),
            pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1),
            freq="h",
        )
        frame = pd.DataFrame(
            {
                "dry_bulb": 20.0,
                "dew_point": 10.0,
                "relative_humidity": 50.0,
                "pressure": 101325.0,
                "ghi": 0.0,
                "dni": 0.0,
                "dhi": 0.0,
                "wind_speed": 2.0,
                "wind_direction": 180.0,
            },
            index=index,
        )
        raw = b"synthetic browser fixture"
        data = WeatherDataset(
            frame,
            Location.model_validate(task.parameters["location"]),
            lineage={
                v: VariableLineage(
                    variable=v, source=task.source, raw_sha256=hashlib.sha256(raw).hexdigest()
                )
                for v in frame
            },
        )
        return ProviderResult(data, task.source, raw)


root = Path(os.environ.get("OPENEPW_UI_TEST_ROOT", ".local/ui-browser-tests"))
app = create_app(
    WeatherService(RuntimeConfig(data_root=root), providers=[FixtureProvider()]),
    ui_dir=Path(__file__).resolve().parents[1] / "ui/dist"
    if (Path(__file__).resolve().parents[1] / "ui/dist/index.html").exists()
    else None,
)
