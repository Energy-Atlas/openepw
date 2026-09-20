import csv
import io
from pathlib import Path

import pandas as pd

from ..dataset import WeatherDataset, local_interval_starts
from ..models import OpenEPWError
from .schema import FIELDS


def epw_bytes(dataset: WeatherDataset) -> bytes:
    if dataset.interval_minutes != 60 or dataset.data.empty:
        raise OpenEPWError("EPW_CONVERSION_FAILED", "EPW output requires nonempty hourly intervals")
    local = local_interval_starts(dataset)
    loc = dataset.location
    headers = (
        [list(h) for h in dataset.headers]
        if dataset.headers
        else [
            [
                "LOCATION",
                loc.name or "OpenEPW",
                "",
                "",
                "OpenEPW",
                "",
                str(loc.lat),
                str(loc.lon),
                str(loc.standard_offset_minutes / 60),
                str(loc.elevation if loc.elevation is not None else 0),
            ],
            ["DESIGN CONDITIONS", "0"],
            ["TYPICAL/EXTREME PERIODS", "0"],
            ["GROUND TEMPERATURES", "0"],
            [
                "HOLIDAYS/DAYLIGHT SAVINGS",
                "Yes" if (local.is_leap_year).any() else "No",
                "0",
                "0",
                "0",
            ],
            ["COMMENTS 1", "OpenEPW; see accompanying provenance manifest and QC"],
            ["COMMENTS 2", "Missing fields use EPW sentinels; no silent repair"],
            [
                "DATA PERIODS",
                "1",
                "1",
                "Data",
                local[0].day_name(),
                f"{local[0].month}/{local[0].day}",
                f"{local[-1].month}/{local[-1].day}",
            ],
        ]
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(headers)
    for pos, (_, row) in enumerate(dataset.data.iterrows()):
        stamp = local[pos]
        year = dataset.source_years[pos] if dataset.source_years else stamp.year
        fields = [year, stamp.month, stamp.day, stamp.hour + 1, 60, row.get("flags", "?9" * 29)]
        for name, sentinel in FIELDS:
            value = row.get(name)
            fields.append(
                str(sentinel) if value is None or pd.isna(value) else format(float(value), ".8g")
            )
        writer.writerow(fields)
    return output.getvalue().encode("utf-8")


def write_epw(dataset: WeatherDataset, path: str | Path) -> None:
    Path(path).write_bytes(epw_bytes(dataset))
