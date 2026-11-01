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
    assert result["specs"][0]["encodings"]["x"]["unit"] == "degC"
    assert [step["operation"] for step in result["specs"][0]["transforms"]] == [
        "select", "bin"]
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
    assert "x" not in spec["encodings"]
    assert spec["encodings"]["value"]["unit"] == "degC"


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


def test_hourly_row_limit_is_checked_before_rows_are_expanded(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)
    refs = [saved(store, synthetic(2023, 8000), bundle=f"{index + 1:032d}")
            for index in range(3)]

    def unexpected_expansion(*_args):
        pytest.fail("Hourly rows were expanded before the size check")

    monkeypatch.setattr("openepw.visualization.engine._hourly_rows", unexpected_expansion)
    with pytest.raises(OpenEPWError, match="RESOURCE_LIMIT"):
        build_view(store, VisualizationRequest(
            artifact_ids=[ref.id for ref in refs], family="time_series",
            variable="dry_bulb"))


def test_histogram_coverage_counts_absent_epw_hours(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2023, 24)
    data.data = data.data.drop(data.data.index[5])
    ref = saved(store, data)
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="histogram", variable="dry_bulb"))
    assert result["specs"][0]["quality"] == {
        "expected_hours": 24, "valid_hours": 23, "missing_hours": 1}


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
    with pytest.raises(OpenEPWError, match="INCOMPATIBLE_SOURCES"):
        build_view(store, VisualizationRequest(
            artifact_ids=[ref.id], family="annual_series", variable="dry_bulb"))


def test_spatial_map_rejects_mixed_provider_products(tmp_path):
    store = ArtifactStore(tmp_path)
    ids = []
    for index, provider in enumerate(("openmeteo", "noaa")):
        bundle = f"{index + 1:032d}"
        data = synthetic(2023, 24)
        data.location.lon = float(index)
        ref = saved(store, data, bundle)
        ids.append(ref.id)
        store.json(bundle, "plan.json",
                   {"kind": "weather", "request": {"product": "historical"}}, "plan")
        store.json(bundle, "manifest.json", {"outputs": [
            {"artifact_id": ref.id, "source": {"provider": provider,
                                                "dataset": "test"}}]}, "manifest")
    with pytest.raises(OpenEPWError, match="INCOMPATIBLE_SOURCES"):
        build_view(store, VisualizationRequest(
            artifact_ids=ids, family="spatial", variable="dry_bulb", allow_partial=True))


def test_irregular_sites_remain_points_without_interpolated_matrix(tmp_path):
    store = ArtifactStore(tmp_path)
    ids = []
    for index, (lat, lon) in enumerate(((0, 0), (0, 1), (1, 0))):
        data = synthetic(2023, 24)
        data.location.lat, data.location.lon = lat, lon
        ids.append(saved(store, data, f"{index + 1:032d}").id)
    result = build_view(store, VisualizationRequest(
        artifact_ids=ids, family="spatial", variable="dry_bulb", allow_partial=True))
    assert result["specs"][0]["data_ref"]["shape"] == "points"
    assert "values" not in result["specs"][0]["encodings"]
    assert len(result["rows"]) == 3


def test_direction_cannot_use_an_arithmetic_annual_mean(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = saved(store, synthetic(2023, 24))
    with pytest.raises(OpenEPWError, match="INVALID_AGGREGATION"):
        build_view(store, VisualizationRequest(
            artifact_ids=[ref.id], family="annual_series",
            variable="wind_direction", allow_partial=True))


def test_duplicate_epw_hours_are_rejected_before_aggregation(tmp_path):
    store = ArtifactStore(tmp_path)
    data = synthetic(2023, 24)
    data.data = data.data.iloc[[0, 0, *range(1, 24)]]
    ref = saved(store, data)
    with pytest.raises(OpenEPWError, match="INVALID_ARTIFACT"):
        build_view(store, VisualizationRequest(
            artifact_ids=[ref.id], family="monthly_series", variable="dry_bulb"))


def test_corrupt_linked_plan_cannot_be_silently_downgraded_to_unverified(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = saved(store, synthetic(2023, 24))
    store.json("a" * 32, "plan.json", {"kind": "weather",
                                      "request": {"product": "historical"}}, "plan")
    (tmp_path / "jobs" / ("a" * 32) / "plan.json").write_text("corrupted")
    with pytest.raises(OpenEPWError, match="INVALID_ARTIFACT"):
        describe_sources(store, [ref.id])


def test_unverified_uploaded_epws_do_not_become_an_actual_year_trend(tmp_path):
    store = ArtifactStore(tmp_path)
    first = saved(store, synthetic(2023, 24), "a" * 32)
    second = saved(store, synthetic(2024, 24), "b" * 32)
    with pytest.raises(OpenEPWError, match="INCOMPATIBLE_SOURCES"):
        build_view(store, VisualizationRequest(
            artifact_ids=[first.id, second.id], family="annual_series",
            variable="dry_bulb", allow_partial=True))


def test_spec_keeps_selected_variable_lineage_and_resolved_source_location(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = saved(store, synthetic(2023, 24))
    store.json("a" * 32, "plan.json",
               {"kind": "weather", "request": {"product": "historical"}}, "plan")
    store.json("a" * 32, "manifest.json", {"outputs": [{
        "artifact_id": ref.id,
        "source": {"provider": "openmeteo", "dataset": "era5",
                   "location": {"lat": 42.5, "lon": -76.5}},
        "lineage": {"dry_bulb": {"source": {"provider": "openmeteo",
                                                 "dataset": "era5"},
                                   "transforms": ["hourly mean"]}},
    }]}, "manifest")
    result = build_view(store, VisualizationRequest(
        artifact_ids=[ref.id], family="monthly_series", variable="dry_bulb"))
    source = result["specs"][0]["sources"][0]
    assert source["provider"] == "openmeteo"
    assert source["resolved_location"] == {"lat": 42.5, "lon": -76.5}
    assert source["lineage"]["transforms"] == ["hourly mean"]


def test_nonfinite_epw_numeric_value_fails_with_typed_error(tmp_path):
    store = ArtifactStore(tmp_path)
    body = epw_bytes(synthetic(2023, 24)).decode()
    lines = body.splitlines()
    fields = lines[8].split(",")
    fields[6] = "inf"
    lines[8] = ",".join(fields)
    ref = store.write("a" * 32, "weather.epw", "\n".join(lines).encode(),
                      "weather", "application/vnd.energyplus.epw")
    with pytest.raises(OpenEPWError, match="INVALID_ARTIFACT"):
        build_view(store, VisualizationRequest(
            artifact_ids=[ref.id], family="time_series", variable="dry_bulb"))


def actual_year(store, year, bundle, *, value=20.0, location=None):
    """An actual-year (historical) weather EPW whose dry-bulb is ``value`` all year."""
    data = synthetic(year, 8784 if year % 4 == 0 else 8760)
    data.data["dry_bulb"] = value
    if location is not None:
        data.location = location
    ref = saved(store, data, bundle)
    store.json(bundle, "plan.json", {"kind": "weather", "request": {"product": "historical"}}, "plan")
    return ref


def test_month_of_year_profile_averages_each_month_over_the_years(tmp_path):
    store = ArtifactStore(tmp_path)
    first, second = actual_year(store, 2022, "c" * 32, value=10.0), actual_year(store, 2023, "d" * 32, value=20.0)
    result = build_view(store, VisualizationRequest(
        artifact_ids=[first.id, second.id], family="month_of_year_profile", variable="dry_bulb"))
    rows = result["rows"]
    assert len(rows) == 12 and [row["month"] for row in rows] == list(range(1, 13))
    january = rows[0]
    assert january["value"] == 15.0 and january["years"] == [2022, 2023] and january["quality"] == "complete"
    assert (january["year_months"], january["expected_year_months"], january["expected_hours"]) == (2, 2, 1488)
    assert set(january["artifact_ids"]) == {first.id, second.id}
    spec = result["specs"][0]
    assert spec["encodings"]["x"] == {"field": "month", "kind": "month_of_year"}
    assert spec["encodings"]["series"] == ["series"]


def test_profile_month_with_an_incomplete_year_is_null_unless_partial(tmp_path):
    store = ArtifactStore(tmp_path)
    first = actual_year(store, 2022, "c" * 32, value=10.0)
    data = synthetic(2023, 8760)
    data.data.loc[data.data.index[0], "dry_bulb"] = float("nan")
    second = saved(store, data, "d" * 32)
    store.json("d" * 32, "plan.json", {"kind": "weather", "request": {"product": "historical"}}, "plan")
    request = VisualizationRequest(artifact_ids=[first.id, second.id], family="month_of_year_profile",
                                   variable="dry_bulb")
    strict = build_view(store, request)["rows"]
    assert strict[0]["value"] is None and strict[0]["quality"] == "incomplete" and strict[0]["missing_hours"] == 1
    assert strict[1]["value"] == 15.0 and strict[1]["quality"] == "complete"
    partial = build_view(store, request.model_copy(update={"allow_partial": True}))["rows"]
    assert partial[0]["value"] == 15.0 and partial[0]["quality"] == "partial"


def test_profile_keeps_places_apart_and_never_mixes_reference_with_actual(tmp_path):
    from openepw.models import Location

    store = ArtifactStore(tmp_path)
    ithaca = actual_year(store, 2022, "c" * 32, location=Location(lat=42.44, lon=-76.5, name="Ithaca"))
    boston = actual_year(store, 2022, "d" * 32, value=12.0, location=Location(lat=42.36, lon=-71.06, name="Boston"))
    rows = build_view(store, VisualizationRequest(
        artifact_ids=[ithaca.id, boston.id], family="month_of_year_profile", variable="dry_bulb"))["rows"]
    assert {row["series"] for row in rows} == {"Ithaca", "Boston"} and len(rows) == 24
    assert {row["value"] for row in rows if row["series"] == "Boston"} == {12.0}
    reference = saved(store, synthetic(2001, 8760), "e" * 32)
    store.json("e" * 32, "plan.json", {"kind": "weather", "request": {"product": "tmy"}}, "plan")
    with pytest.raises(OpenEPWError, match="INCOMPATIBLE_SOURCES"):
        build_view(store, VisualizationRequest(
            artifact_ids=[ithaca.id, reference.id], family="month_of_year_profile", variable="dry_bulb"))
