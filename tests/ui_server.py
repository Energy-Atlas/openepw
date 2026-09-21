"""Offline provider fixture server. NEVER imported by production code."""

import hashlib
import os
import time
from pathlib import Path

import numpy as np
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
        # Opt-in delay for manual progress checks; automated tests leave it at zero.
        time.sleep(float(os.environ.get("OPENEPW_UI_FIXTURE_DELAY", "0")))
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
        # Deterministic seasonal and diurnal cycles so charts show real gradients.
        day = index.dayofyear.to_numpy()
        hour = index.hour.to_numpy()
        season = np.cos(2 * np.pi * (day - 200) / 365.0)
        sun = np.clip(np.sin(np.pi * (hour - 6) / 12.0), 0, None) * (0.65 + 0.35 * season)
        dry_bulb = 9.0 + 13.0 * season + 5.0 * np.sin(np.pi * (hour - 9) / 12.0)
        values = {
            "dry_bulb": dry_bulb,
            "dew_point": dry_bulb - 6.0,
            "relative_humidity": 60.0 - 15.0 * sun,
            "pressure": 101325.0 + 400.0 * np.sin(2 * np.pi * day / 9.0),
            "ghi": 850.0 * sun,
            "dhi": 180.0 * sun,
            "wind_speed": 3.0 + 1.5 * np.sin(2 * np.pi * day / 5.0),
            "wind_direction": (180.0 + 90.0 * np.sin(2 * np.pi * day / 11.0)) % 360.0,
        }
        if not self.sparse:
            values.update(
                {
                    "dni": 700.0 * sun,
                    "liquid_precipitation": np.where((day % 4 == 0) & (hour < 6), 1.2, 0.0),
                }
            )
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
