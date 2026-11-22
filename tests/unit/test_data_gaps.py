"""Data gaps and fills (planning/gaps.py): what a chosen source lacks, station pressure from a
station's own reports, whole-variable fills from a second source, and what the manifest records."""

import json

import httpx
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from openepw import pressure
from openepw.agent.evals.stubs import StubERA5
from openepw.config import RuntimeConfig
from openepw.models import (
    Candidate,
    DiscoveryResult,
    Location,
    OpenEPWError,
    SourceRef,
    VariableFill,
    WeatherRequest,
)
from openepw.planning import gaps
from openepw.providers.http import HttpClient
from openepw.providers.noaa_isd import NOAAProvider, normalize_isd
from openepw.service import WeatherService

STATION_VARIABLES = ["dry_bulb", "dew_point", "relative_humidity", "wind_speed", "wind_direction"]
SOLAR = VariableFill(group="solar", method="source", provider="openmeteo", dataset="era5")
STATION_PRESSURE = VariableFill(group="pressure", method="station_reports")


def test_altimeter_setting_inverts_the_standard_atmosphere_definition():
    # Paya Lebar, 2023-06-01 00:00 UTC: altimeter 1010.0 hPa at a 19.81 m station.
    station = float(pressure.from_altimeter(1010.0, 19.81))
    assert station == pytest.approx(1007.63, abs=0.02)
    n, k = pressure.ALTIMETER_EXPONENT, pressure.ALTIMETER_K
    assert (station ** n + k * 19.81) ** (1 / n) == pytest.approx(1010.0)      # the definition, back
    assert float(pressure.from_altimeter(1013.25, 0)) == pytest.approx(1013.25)


def test_sea_level_pressure_is_reduced_only_for_low_stations():
    assert float(pressure.from_sea_level(1011.0, 27.6, 0)) == pytest.approx(1011.0)
    assert float(pressure.from_sea_level(1011.0, 27.6, 6.7)) == pytest.approx(1010.23, abs=0.02)
    assert np.isnan(pressure.from_sea_level(1011.0, 10.0, 501.0))


def test_station_reports_prefer_measured_then_altimeter_then_sea_level():
    rows = [
        {"DATE": "2023-06-01T01:00:00", "TMP": "+0276,1", "MA1": "99999,9,10094,1", "SLP": "10110,1"},   # measured
        {"DATE": "2023-06-01T02:00:00", "TMP": "+0280,1", "MA1": "10100,1,99999,9", "SLP": "99999,9"},   # altimeter
        {"DATE": "2023-06-01T03:00:00", "TMP": "+0280,1", "MA1": "99999,9,99999,9", "SLP": "10110,1"},   # sea level
        {"DATE": "2023-06-01T04:00:00", "TMP": "+0280,1", "MA1": "10100,3,99999,9", "SLP": "99999,9"},   # rejected flag
    ]
    target = pd.date_range("2023-06-01T01:00Z", periods=4, freq="h")
    frame = normalize_isd(rows, target, pressure_elevation=6.7, derive_pressure=True)
    assert frame.pressure.iloc[0] == pytest.approx(100940.0)
    assert frame.pressure.iloc[1] == pytest.approx(pressure.from_altimeter(1010.0, 6.7) * 100)
    assert frame.pressure.iloc[2] == pytest.approx(pressure.from_sea_level(1011.0, 28.0, 6.7) * 100)
    assert np.isnan(frame.pressure.iloc[3])
    assert list(frame["_pressure_method"].iloc[:3]) == ["reported", "altimeter", "sea_level"]
    unknown = normalize_isd(rows, target, pressure_elevation=None, derive_pressure=True)
    assert unknown.pressure.notna().tolist() == [True, False, False, False]      # only the measured hour
    assert "pressure" not in normalize_isd(rows, target)


def test_fill_rules_are_validated():
    with pytest.raises(ValidationError):
        VariableFill(group="solar", method="source")                       # which source?
    with pytest.raises(ValidationError):
        VariableFill(group="solar", method="station_reports")              # stations report pressure only
    with pytest.raises(ValidationError):
        VariableFill(group="pressure", method="leave_missing", provider="openmeteo", dataset="era5")
    with pytest.raises(ValidationError):
        WeatherRequest(locations=Location(lat=1, lon=1), product="tmy", fills=[SOLAR])
    assert "fills" not in WeatherRequest(locations=Location(lat=1, lon=1), years=[2020]).model_dump()


def test_missing_groups_and_options():
    required = WeatherRequest(locations=Location(lat=1, lon=1), years=[2020]).required_variables
    assert gaps.missing_groups(STATION_VARIABLES, required) == [("solar", ["ghi", "dni", "dhi"]),
                                                                ("pressure", ["pressure"])]
    cds = [*STATION_VARIABLES, "pressure", "ghi"]
    assert gaps.missing_groups(cds, required) == [("solar", ["dni", "dhi"])]     # all three still come from one source
    assert gaps.missing_groups(STATION_VARIABLES, ["dry_bulb"]) == []


def _service(tmp_path, rows, *, fail_filler=False):
    config = RuntimeConfig(data_root=tmp_path)
    http = HttpClient(config, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=rows)))
    filler = StubERA5(fail_near=[(1.38, 103.9)] if fail_filler else [])
    return WeatherService(config, http=http, providers=[NOAAProvider(), filler])


def _discovery(elevation=19.8):
    location = Location(lat=1.36, lon=103.9)
    station = Location(lat=1.38, lon=103.9, elevation=elevation, name="PAYA LEBAR")
    source = SourceRef(provider="noaa", dataset="ISD global-hourly", identity="48694099999",
                       location=station, provisional=False)
    candidate = Candidate(id="noaa:48694099999", location_id=location.key, product_id="48694099999",
                          source=source, weather_types=["historical", "amy"], variables=STATION_VARIABLES)
    return location, DiscoveryResult(locations=[location], candidates=[candidate],
                                     selected_candidate_ids=[candidate.id])


ROWS = [{"DATE": f"2024-01-01T{hour:02d}:00:00", "TMP": "+0250,1", "DEW": "+0200,1", "WND": "180,1,N,0020,1",
         "MA1": "10100,1,99999,9", "SLP": "99999,9"} for hour in range(1, 24)] + [
    {"DATE": "2024-01-02T00:00:00", "TMP": "+0250,1", "DEW": "+0200,1", "WND": "180,1,N,0020,1",
     "MA1": "10100,1,99999,9", "SLP": "99999,9"}]


def _plan(service, fills=(), elevation=19.8):
    location, discovery = _discovery(elevation)
    request = WeatherRequest(locations=location, start="2024-01-01", end="2024-01-01", providers=["noaa"],
                             fills=list(fills))
    return service.plan(request, discovery=discovery)


def _manifest(tmp_path, bundle):
    return json.loads((tmp_path / bundle.manifest.path).read_text())


def test_unresolved_gaps_warn_and_keep_the_output_unchanged(tmp_path):
    service = _service(tmp_path, ROWS)
    plan = _plan(service)
    assert [(gap.group, gap.status) for gap in plan.gaps] == [("solar", "unresolved"), ("pressure", "unresolved")]
    assert [issue.code for issue in plan.issues] == ["DATA_GAP", "DATA_GAP"]
    assert len(plan.tasks) == 1 and "derived" not in plan.tasks[0].parameters
    assert not plan.outputs[0].fills
    pressure_options = next(gap for gap in plan.gaps if gap.group == "pressure").options
    assert [option.fill.method for option in pressure_options] == ["station_reports", "source", "leave_missing"]
    assert pressure_options[0].recommended
    manifest = _manifest(tmp_path, service.execute(plan))
    output = manifest["outputs"][0]
    assert output["missing_hours"]["ghi"] == 24 and output["missing_hours"]["pressure"] == 24
    assert {gap["status"] for gap in output["gaps"]} == {"unresolved"}
    assert "DATA_GAP" in manifest["batch_rows"][0]["issue_codes"]


def test_fills_take_solar_from_a_second_source_and_pressure_from_the_station(tmp_path):
    service = _service(tmp_path, ROWS)
    plan = _plan(service, [SOLAR, STATION_PRESSURE])
    assert {gap.group: gap.status for gap in plan.gaps} == {"solar": "filled", "pressure": "station_reports"}
    assert not plan.issues
    station_task, fill_task = plan.tasks
    assert station_task.parameters["derived"] == ["pressure"]
    assert fill_task.source.provider == "openmeteo"
    assert fill_task.parameters["location"]["lat"] == 1.38                # the station's point
    assert fill_task.parameters["location"]["elevation"] == 19.8
    assert plan.outputs[0].task_ids == [station_task.id, fill_task.id]
    unfilled = _plan(_service(tmp_path / "other", ROWS))
    assert plan.outputs[0].id != unfilled.outputs[0].id                   # a fill is part of the identity

    bundle = service.execute(plan)
    manifest = _manifest(tmp_path, bundle)
    output = manifest["outputs"][0]
    assert output["missing_hours"] == {**output["missing_hours"], "ghi": 0, "dni": 0, "dhi": 0, "pressure": 0}
    assert output["lineage"]["ghi"]["filled"] is True
    assert "whole-variable fill for solar from Open-Meteo ERA5" in output["lineage"]["dni"]["transforms"][-1]
    assert output["lineage"]["pressure"]["derived"] is True
    assert "24 h from the altimeter setting" in output["lineage"]["pressure"]["transforms"][-1]
    assert output["metadata"]["fills"][0]["provider"] == "openmeteo"
    assert "VARIABLE_FILLED" in manifest["batch_rows"][0]["issue_codes"]
    assert manifest["simulation_ready"] is False


def test_a_failed_filling_source_leaves_its_group_missing(tmp_path):
    service = _service(tmp_path, ROWS, fail_filler=True)
    bundle = service.execute(_plan(service, [SOLAR]))
    manifest = _manifest(tmp_path, bundle)
    assert manifest["batch_rows"][0]["status"] == "succeeded"
    assert {"FILL_FAILED", "PROVIDER_ERROR"} <= set(manifest["batch_rows"][0]["issue_codes"])
    assert manifest["outputs"][0]["missing_hours"]["ghi"] == 24


def test_station_reports_need_a_known_elevation_and_later_rules_apply(tmp_path):
    service = _service(tmp_path, ROWS)
    fallback = VariableFill(group="pressure", method="source", provider="openmeteo", dataset="era5")
    plan = _plan(service, [STATION_PRESSURE, fallback], elevation=None)
    gap = next(gap for gap in plan.gaps if gap.group == "pressure")
    assert gap.status == "filled" and gap.fill == fallback
    assert "station_reports" not in {option.fill.method for option in gap.options}
    alone = _plan(service, [STATION_PRESSURE], elevation=None)
    gap = next(gap for gap in alone.gaps if gap.group == "pressure")
    assert gap.status == "unresolved" and "known elevation" in gap.note


def test_left_missing_is_recorded_as_a_choice(tmp_path):
    service = _service(tmp_path, ROWS)
    plan = _plan(service, [VariableFill(group="solar", method="leave_missing"), STATION_PRESSURE])
    assert {gap.group: gap.status for gap in plan.gaps} == {"solar": "left_missing", "pressure": "station_reports"}
    assert [issue.message for issue in plan.issues] == [
        "NOAA ISD station observations has no GHI, DNI, DHI: left missing by choice (EPW 9999)"]


def test_rules_for_another_source_do_not_apply(tmp_path):
    service = _service(tmp_path, ROWS)
    other = VariableFill(group="solar", method="source", provider="openmeteo", dataset="era5",
                         for_provider="cds", for_dataset="reanalysis-era5-single-levels")
    assert next(gap for gap in _plan(service, [other]).gaps if gap.group == "solar").status == "unresolved"


def test_gap_rows_group_places_and_mark_the_recommended_option(tmp_path):
    rows = gaps.gap_rows(_plan(_service(tmp_path, ROWS)).gaps)
    solar = next(row for row in rows if row["group"] == "solar")
    assert solar["id"] == "noaa|ISD global-hourly|solar" and solar["places"] == 1 and solar["unresolved"] == 1
    assert [option["id"] for option in solar["options"] if option["recommended"]] == ["source:openmeteo:era5"]
    assert solar["chosen"] is None


def test_fill_alignment_is_checked():
    from openepw.dataset import WeatherDataset
    from openepw.planning.hybrid import fill_group

    index = pd.date_range("2024-01-01T01:00Z", periods=3, freq="h")
    primary = WeatherDataset(data=pd.DataFrame({"dry_bulb": [1.0, 2.0, 3.0]}, index=index),
                             location=Location(lat=1, lon=1))
    shifted = WeatherDataset(data=pd.DataFrame({"ghi": [0.0, 0.0, 0.0]}, index=index + pd.Timedelta(hours=1)),
                             location=Location(lat=1, lon=1))
    with pytest.raises(OpenEPWError) as raised:
        fill_group(primary, shifted, ["ghi"], group="solar", provider="openmeteo", dataset="era5")
    assert raised.value.issue.code == "INVALID_ALIGNMENT"
