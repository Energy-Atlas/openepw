import numpy as np
from test_epw import synthetic

from openepw.preview import preview


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
