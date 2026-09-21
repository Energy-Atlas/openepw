import numpy as np
import pytest
from test_epw import synthetic

from openepw.dataset import without_feb_29
from openepw.models import OpenEPWError
from openepw.preview import preview, visualize


def test_preview_retains_missing_energy_and_calendar():
    data = synthetic(2023, 8760)
    data.data.loc[:, "ghi"] = 10.0
    data.data.iloc[0, data.data.columns.get_loc("ghi")] = np.nan
    result = preview(data, variables=["dry_bulb", "ghi"])
    assert result.rows[0].values["ghi"] is None
    assert result.total_rows == 8760
    assert len(result.rows) == 168
    january = result.monthly[0]
    assert january.values["ghi"].sum == 7430
    assert january.values["ghi"].valid == 743
    assert january.expected == 744
    assert january.values["dry_bulb"].mean == 20
    data.calendar = "noleap"
    assert preview(data).calendar == "noleap"


def test_preview_preserves_source_year_mapping():
    data = synthetic(2001, 8760)
    data.calendar = "noleap"
    data.source_years = [1998] * 744 + [2004] * (8760 - 744)
    result = preview(data, start=743, limit=2)
    assert [row.source_year for row in result.rows] == [1998, 2004]
    assert result.monthly[0].source_years == [1998]
    assert result.monthly[1].source_years == [2004]
    assert result.synthetic_chronology is True


@pytest.mark.parametrize("year,rows", [(2023, 8760), (2024, 8784)])
def test_visualization_preserves_full_annual_calendar(year, rows):
    result = visualize(synthetic(year, rows), ["dry_bulb", "dni"])

    assert result.total_rows == rows
    assert len(result.timestamps) == rows
    assert len(result.source_years) == rows
    assert len(result.series["dry_bulb"]) == rows
    assert result.timestamps[0].endswith("00:00:00")
    february = result.monthly[1]
    assert february.expected == (696 if rows == 8784 else 672)


def test_visualization_summarizes_partial_span_and_retains_gaps():
    data = synthetic(2023, 24)
    data.data["liquid_precipitation"] = 1.0
    data.data.loc[data.data.index[0], "liquid_precipitation"] = np.nan
    data.data.loc[:, "dni"] = np.nan
    data.data = data.data.drop(data.data.index[12])

    result = visualize(data, ["dry_bulb", "liquid_precipitation", "dni"])

    assert result.total_rows == 23
    assert result.monthly[0].expected == 24
    assert result.monthly[0].values["dry_bulb"].mean == 20
    assert result.monthly[0].values["liquid_precipitation"].sum == 22
    assert result.monthly[0].values["liquid_precipitation"].valid == 22
    assert result.monthly[0].values["dni"].sum is None
    assert result.series["liquid_precipitation"][0] is None
    assert result.series["dni"] == [None] * 23


def test_visualization_preserves_noleap_and_mixed_source_years():
    data = without_feb_29(synthetic(2024, 8784))
    data.source_years = [1998] * 744 + [2004] * (8760 - 744)

    result = visualize(data, ["dry_bulb"])

    assert result.calendar == "noleap"
    assert result.total_rows == 8760
    assert not any(timestamp.startswith("2024-02-29") for timestamp in result.timestamps)
    assert result.source_years[743:745] == [1998, 2004]
    assert result.monthly[0].source_years == [1998]
    assert result.monthly[1].source_years == [2004]
    assert result.synthetic_chronology is True


def test_visualization_enforces_variable_and_row_bounds():
    with pytest.raises(OpenEPWError, match="one to four"):
        visualize(synthetic(), [])
    with pytest.raises(OpenEPWError, match="one to four"):
        visualize(synthetic(), ["dry_bulb", "dew_point", "pressure", "ghi", "dni"])
    with pytest.raises(OpenEPWError, match="Unknown"):
        visualize(synthetic(), ["not_weather"])
    with pytest.raises(OpenEPWError, match="8,784"):
        visualize(synthetic(2024, 8785), ["dry_bulb"])
