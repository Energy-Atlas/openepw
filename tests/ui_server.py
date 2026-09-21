"""Offline provider fixture server. NEVER imported by production code."""

import hashlib
import os
from pathlib import Path

import pandas as pd

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.dataset import WeatherDataset
from openepw.models import Candidate, Location, OpenEPWError, SourceRef, VariableLineage
from openepw.providers.base import ProviderResult
from openepw.service import WeatherService


class FixtureProvider:
    def __init__(self, name="openmeteo", dataset="era5", *, sparse=False):
        self.name = name
        self.dataset = dataset
        self.sparse = sparse

    def discover(self, request, location, http):
        variables = [
            "dry_bulb",
            "dew_point",
            "relative_humidity",
            "pressure",
            "ghi",
            "dhi",
            "wind_speed",
            "wind_direction",
        ]
        if not self.sparse:
            variables.extend(["dni", "liquid_precipitation"])
        source = SourceRef(
            provider=self.name,
            dataset=self.dataset,
            identity=f"fixture-{self.name}",
            location=location,
            provisional=False,
        )
        return [
            Candidate(
                id=f"fixture-{self.name}-" + location.key,
                location_id=location.key,
                source=source,
                variables=variables,
                missing_fields=["dni", "liquid_precipitation"] if self.sparse else [],
                selection_reasons=["complete local test source"] if not self.sparse else [],
            )
        ]

    def fetch(self, task, http):
        location = Location.model_validate(task.parameters["location"])
        if self.sparse and location.lon > -76.48:
            raise OpenEPWError(
                "SOURCE_UNAVAILABLE",
                "Synthetic alternate source is unavailable at this sampled point",
            )
        start = task.parameters["start"]
        end = task.parameters["end"]
        index = pd.date_range(
            pd.Timestamp(start, tz="UTC") + pd.Timedelta(hours=1),
            pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1),
            freq="h",
        )
        values = {
            "dry_bulb": 20.0,
            "dew_point": 10.0,
            "relative_humidity": 50.0,
            "pressure": 101325.0,
            "ghi": 0.0,
            "dhi": 0.0,
            "wind_speed": 2.0,
            "wind_direction": 180.0,
        }
        if not self.sparse:
            values.update({"dni": 0.0, "liquid_precipitation": 0.1})
        frame = pd.DataFrame(values, index=index)
        raw = b"synthetic browser fixture"
        data = WeatherDataset(
            frame,
            location,
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
    WeatherService(
        RuntimeConfig(data_root=root),
        providers=[
            FixtureProvider(),
            FixtureProvider("cds", "reanalysis-era5-single-levels", sparse=True),
        ],
    ),
    ui_dir=Path(__file__).resolve().parents[1] / "ui/dist"
    if (Path(__file__).resolve().parents[1] / "ui/dist/index.html").exists()
    else None,
)
