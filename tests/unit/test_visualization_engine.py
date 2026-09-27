"""Prepared views preserve EPW calendars, sentinels and source identity."""

import pytest
from test_epw import synthetic

from openepw.artifacts.store import ArtifactStore
from openepw.dataset import without_feb_29
from openepw.epw.writer import epw_bytes
from openepw.models import OpenEPWError
from openepw.visualization import VisualizationRequest
from openepw.visualization.engine import build_view, describe_sources


def saved(store, dataset, bundle="a" * 32):
    return store.write(bundle, "weather.epw", epw_bytes(dataset), "weather",
                       "application/vnd.energyplus.epw")


def test_describe_reports_leap_year_missing_value_and_unverified_identity(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2024, 8784)
    data.data.loc[data.data.index[0], "dry_bulb"] = float("nan")
    ref = saved(store, data)

    description = describe_sources(store, [ref.id])

    source = description["sources"][0]
    assert source["calendar"] == "gregorian"
    assert source["temporal_kind"] == "unverified"
    assert source["years"] == [2024]
    assert source["rows"] == 8784
    assert source["variables"]["dry_bulb"]["missing_hours"] == 1


def test_monthly_missing_value_is_null_unless_partial_is_requested(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2024, 8784)
    data.data.loc[data.data.index[0], "dry_bulb"] = float("nan")
    ref = saved(store, data)
    request = VisualizationRequest(artifact_ids=[ref.id], family="monthly_series",
                                   variable="dry_bulb", aggregation="mean")

    complete = build_view(store, request)
    january = complete["rows"][0]
    february = complete["rows"][1]
    assert (january["expected_hours"], january["valid_hours"],
            january["missing_hours"], january["value"]) == (744, 743, 1, None)
    assert february["expected_hours"] == 696
    assert february["value"] == 20.0

    partial = build_view(store, request.model_copy(update={"allow_partial": True}))
    assert partial["rows"][0]["value"] == 20.0
    assert partial["rows"][0]["quality"] == "partial"


def test_future_output_is_rejected_during_mcp_suspension(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = saved(store, synthetic(2023, 24))
    store.json("a" * 32, "plan.json", {"kind": "future"}, "plan")
    request = VisualizationRequest(artifact_ids=[ref.id], family="time_series",
                                   variable="dry_bulb")
    with pytest.raises(OpenEPWError, match="FEATURE_SUSPENDED"):
        build_view(store, request)


def test_annual_solar_sum_counts_leap_day_energy(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2024, 8784)
    data.data["ghi"] = 2.0
    ref = saved(store, data)
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="annual_series", variable="ghi"))
    assert result["rows"][0]["value"] == 17568.0
    assert result["rows"][0]["expected_hours"] == 8784
    assert result["specs"][0]["encodings"]["y"]["unit"] == "Wh/m2"


def test_histogram_excludes_missing_sentinel_and_keeps_shared_bin_edges(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2023, 24)
    data.data["dry_bulb"] = [0.0] * 12 + [10.0] * 11 + [float("nan")]
    ref = saved(store, data)
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="histogram", variable="dry_bulb",
        options={"bins": 2}))
    assert [row["count"] for row in result["rows"]] == [12, 11]
    assert result["specs"][0]["encodings"]["x"]["bin_edges"] == [0.0, 5.0, 10.0]
    assert result["specs"][0]["quality"]["missing_hours"] == 1


def test_spatial_grid_requires_complete_rectilinear_coordinates(tmp_path):
    store = ArtifactStore(tmp_path)
    refs = []
    for index, (lat, lon) in enumerate(((0, 0), (0, 1), (1, 0), (1, 1))):
        data = synthetic(2023, 24)
        data.location.lat, data.location.lon = lat, lon
        data.data["dry_bulb"] = float(index)
        refs.append(saved(store, data, bundle=f"{index + 1:032d}"))
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id for ref in refs], family="spatial",
        variable="dry_bulb", allow_partial=True))
    spec = result["specs"][0]
    assert spec["data_ref"]["shape"] == "matrix"
    assert spec["encodings"]["latitudes"] == [0.0, 1.0]
    assert spec["encodings"]["longitudes"] == [0.0, 1.0]
    assert spec["encodings"]["values"] == [[0.0, 1.0], [2.0, 3.0]]


def test_missing_timestamp_is_present_as_null_in_hourly_view(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2023, 24)
    data.data = data.data.drop(data.data.index[5])
    ref = saved(store, data)
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="time_series", variable="dry_bulb"))
    assert len(result["rows"]) == 24
    assert result["rows"][5]["period"] == "2023-01-01T05:00:00"
    assert result["rows"][5]["value"] is None
    assert result["rows"][5]["missing_hours"] == 1


def test_declared_noleap_year_keeps_8760_expected_hours(tmp_path):
    store = ArtifactStore(tmp_path)
    data = without_feb_29(synthetic(2024, 8784))
    ref = saved(store, data)
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="annual_series", variable="dry_bulb"))
    assert result["rows"][0]["year"] == 2024
    assert result["rows"][0]["expected_hours"] == 8760
    assert result["rows"][0]["value"] == 20.0


def test_published_tmy_months_do_not_claim_an_actual_calendar_year(tmp_path):
    store = ArtifactStore(tmp_path)
    body = epw_bytes(synthetic(2001, 8760)).decode()
    lines = body.splitlines()
    for index in range(8, len(lines)):
        fields = lines[index].split(",")
        fields[0] = str(1990 + int(fields[1]))
        lines[index] = ",".join(fields)
    ref = store.write("b" * 32, "weather.epw", "\n".join(lines).encode(),
                      "weather", "application/vnd.energyplus.epw")
    store.json("b" * 32, "plan.json",
               {"kind": "weather", "request": {"product": "tmy"}}, "plan")
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="monthly_series", variable="dry_bulb"))
    assert result["specs"][0]["sources"][0]["temporal_kind"] == "reference"
    assert result["rows"][0]["year"] is None
    assert result["rows"][0]["period"] == "reference-01"
