import numpy as np
import pytest

from openepw.generation.cmip6 import make_signal, monthly_means
from openepw.models import OpenEPWError


def test_360_day_climatology_and_missing_month_rejected():
    xr = pytest.importorskip("xarray")
    pytest.importorskip("cftime")
    times = xr.date_range("2001-01-01", periods=24, freq="MS", calendar="360_day", use_cftime=True)
    values = xr.DataArray(np.tile(np.arange(1, 13), 2), dims="time", coords={"time": times})
    assert monthly_means(values, (2001, 2002)).tolist() == list(range(1, 13))
    with pytest.raises(OpenEPWError):
        monthly_means(values.isel(time=slice(1, None)), (2001, 2002))


def test_climate_signal_ratio_denominator_is_explicit():
    reference = {
        k: np.full(12, v)
        for k, v in {
            "tas": 280,
            "tasmin": 275,
            "tasmax": 285,
            "hurs": 50,
            "ps": 100000,
            "sfcWind": 0,
            "rsds": 100,
        }.items()
    }
    future = {k: v.copy() for k, v in reference.items()}
    future["tas"] += 2
    future["sfcWind"] += 1
    with pytest.raises(OpenEPWError):
        make_signal(reference, future, {})
