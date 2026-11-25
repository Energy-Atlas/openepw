"""Short gaps inside a station's records (planning/short_gaps.py, owner decision 3b): gaps of up to
3 hours are interpolated where the person chose it, never solar, never at the edges, and every
interpolated hour is recorded."""

import json

import numpy as np
import pandas as pd
import pytest
from test_data_gaps import ROWS, _plan, _service

from openepw.dataset import WeatherDataset
from openepw.models import Location, SourceRef, VariableFill, VariableLineage
from openepw.planning import gaps
from openepw.planning.short_gaps import gap_runs, interpolate_short_gaps

INTERPOLATE = VariableFill(group="short_gaps", method="interpolate")
NAN = np.nan


def _dataset(**columns):
    index = pd.date_range("2024-01-01T01:00Z", periods=len(next(iter(columns.values()))), freq="h")
    source = SourceRef(provider="noaa", dataset="ISD global-hourly")
    lineage = {name: VariableLineage(variable=name, source=source, raw_sha256="0" * 64,
                                     derived=name == "relative_humidity") for name in columns}
    return WeatherDataset(data=pd.DataFrame(columns, index=index), location=Location(lat=1, lon=1),
                          lineage=lineage)


def test_only_bounded_runs_of_at_most_three_hours_count():
    values = pd.Series([NAN, 1, NAN, 3, NAN, NAN, NAN, NAN, 8, NAN, NAN, 11, NAN],
                       index=pd.date_range("2024-01-01", periods=13, freq="h", tz="UTC"))
    assert gap_runs(values) == [(2, 1), (9, 2)]        # not the start, the 4-hour run or the end
    holed = values.drop(values.index[10])               # the index itself skips an hour
    assert gap_runs(holed) == [(2, 1)]


def test_straight_lines_and_untouched_long_gaps():
    result = interpolate_short_gaps(_dataset(dry_bulb=[10.0, NAN, NAN, 16.0, NAN, NAN, NAN, NAN, 0.0]),
                                    ["dry_bulb"])
    assert result.data.dry_bulb.iloc[:4].tolist() == pytest.approx([10, 12, 14, 16])
    assert result.data.dry_bulb.iloc[4:8].isna().all()
    assert result.metadata["interpolated"]["dry_bulb"] == {"hours": 2, "gaps": [["2024-01-01T02:00:00+00:00", 2]]}
    assert "short gaps interpolated: 2 h in 1 gap(s) of up to 3 h" in result.lineage["dry_bulb"].transforms[-1]
    assert [issue.code for issue in result.issues] == ["GAPS_INTERPOLATED"]


def test_solar_and_unrequested_variables_are_never_filled():
    source = _dataset(ghi=[100.0, NAN, 300.0], dew_point=[1.0, NAN, 3.0])
    result = interpolate_short_gaps(source, ["ghi", "dry_bulb"])
    assert np.isnan(result.data.ghi.iloc[1]) and np.isnan(result.data.dew_point.iloc[1])
    assert "interpolated" not in result.metadata and not result.issues
    assert np.isnan(source.data.ghi.iloc[1])           # the input is not changed


def test_relative_humidity_follows_the_interpolated_dry_bulb_and_dew_point():
    result = interpolate_short_gaps(_dataset(dry_bulb=[20.0, NAN, 24.0], dew_point=[10.0, NAN, 14.0],
                                             relative_humidity=[52.6, NAN, 53.2]),
                                    ["dry_bulb", "dew_point", "relative_humidity"])
    dry, dew = 22.0, 12.0
    expected = 100 * np.exp(17.625 * dew / (243.04 + dew) - 17.625 * dry / (243.04 + dry))
    assert result.data.relative_humidity.iloc[1] == pytest.approx(expected)
    assert "Magnus RH" in result.lineage["relative_humidity"].transforms[-1]


def test_wind_direction_takes_the_shorter_arc_and_skips_calm_hours():
    result = interpolate_short_gaps(_dataset(wind_speed=[2.0, NAN, 4.0, 3.0, 0.0, 3.0],
                                             wind_direction=[350.0, NAN, 10.0, 90.0, NAN, 270.0]),
                                    ["wind_speed", "wind_direction"])
    assert result.data.wind_speed.iloc[1] == pytest.approx(3.0)
    assert result.data.wind_direction.iloc[1] == pytest.approx(0.0)    # through north, not south
    assert np.isnan(result.data.wind_direction.iloc[4])                 # calm: no direction


def test_short_gaps_are_offered_for_station_records_and_decided_like_other_gaps(tmp_path):
    plan = _plan(_service(tmp_path, ROWS))
    gap = next(gap for gap in plan.gaps if gap.group == "short_gaps")
    assert gap.status == "unresolved" and "relative_humidity" in gap.variables and "ghi" not in gap.variables
    assert [(option.fill.method, option.recommended) for option in gap.options] == [
        ("interpolate", True), ("leave_missing", False)]
    row = next(row for row in gaps.gap_rows(plan.gaps) if row["group"] == "short_gaps")
    assert row["label"] == "Hours missing inside the station's records"
    chosen = _plan(_service(tmp_path / "chosen", ROWS), [INTERPOLATE])
    assert next(gap for gap in chosen.gaps if gap.group == "short_gaps").status == "interpolated"
    assert [fill.method for fill in chosen.outputs[0].fills] == ["interpolate"]
    assert chosen.tasks[0].cache_key == plan.tasks[0].cache_key          # the same retrieval
    assert chosen.outputs[0].id != plan.outputs[0].id                    # a different file


def test_a_planned_run_interpolates_and_records_the_hours(tmp_path):
    rows = [dict(row) for row in ROWS]
    for row in rows[4:6]:                       # 05:00 and 06:00 UTC: a two-hour gap
        row["TMP"] = "+9999,9"
    for row in rows[10:14]:                     # 11:00-14:00 UTC: four hours, left missing
        row["DEW"] = "+9999,9"
    service = _service(tmp_path, rows)
    bundle = service.execute(_plan(service, [INTERPOLATE]))
    manifest = json.loads((tmp_path / bundle.manifest.path).read_text())
    output = manifest["outputs"][0]
    assert output["interpolated_hours"] == {"dry_bulb": 2, "relative_humidity": 2}
    assert output["missing_hours"]["dry_bulb"] == 0 and output["missing_hours"]["dew_point"] == 4
    assert output["missing_hours"]["ghi"] == 24                          # never solar
    assert "GAPS_INTERPOLATED" in manifest["batch_rows"][0]["issue_codes"]
    assert manifest["batch_rows"][0]["status"] == "succeeded"
    assert manifest["simulation_ready"] is False
    left = _service(tmp_path / "left", rows)
    kept = json.loads((tmp_path / "left" / left.execute(_plan(left)).manifest.path).read_text())
    assert kept["outputs"][0]["missing_hours"]["dry_bulb"] == 2 and "interpolated_hours" not in kept["outputs"][0]
