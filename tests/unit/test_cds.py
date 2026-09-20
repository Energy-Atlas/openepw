import numpy as np
import pandas as pd
import pytest

from openepw.providers.era5 import normalize_era5


def test_cds_hourly_units_and_land_reset():
    xr = pytest.importorskip("xarray")
    times = pd.date_range("2024-01-01T23:00", periods=3, freq="h")
    ds = xr.Dataset(
        {
            k: ("valid_time", v)
            for k, v in {
                "t2m": [293.15] * 3,
                "d2m": [283.15] * 3,
                "sp": [100000] * 3,
                "u10": [0] * 3,
                "v10": [-2] * 3,
                "ssrd": [720000, 1080000, 360000],
            }.items()
        },
        coords={"valid_time": times},
    )
    frame = normalize_era5(ds, land=True)
    assert np.isnan(frame.ghi.iloc[0])
    assert frame.ghi.iloc[1:].tolist() == [100, 100]
    assert frame.dry_bulb.iloc[1] == 20
    assert frame.wind_speed.iloc[1] == 2
    assert frame.wind_direction.iloc[1] == 0


def test_cds_step_types_are_merged_before_normalization():
    import io
    import zipfile

    xr = pytest.importorskip("xarray")
    from openepw.providers.era5 import decode_cds

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        for var in ["t2m", "ssrd"]:
            ds = xr.Dataset(
                {var: (("time", "latitude", "longitude"), np.ones((1, 1, 1)))},
                coords={"time": [0], "latitude": [42.5], "longitude": [-76.5]},
            )
            z.writestr(var + ".nc", ds.to_netcdf(engine="h5netcdf"))
    result = decode_cds(stream.getvalue(), 42.44, -76.5)
    assert set(result.data_vars) == {"t2m", "ssrd"}


def test_land_accumulation_across_month_boundary():
    xr = pytest.importorskip("xarray")
    times = pd.to_datetime(["2024-01-31T23:00", "2024-02-01T00:00", "2024-02-01T01:00"])
    ds = xr.Dataset(
        {
            k: ("valid_time", v)
            for k, v in {
                "t2m": [293.15] * 3,
                "d2m": [283.15] * 3,
                "sp": [100000] * 3,
                "u10": [0] * 3,
                "v10": [-2] * 3,
                "ssrd": [720000, 1080000, 360000],
            }.items()
        },
        coords={"valid_time": times},
    )
    result = normalize_era5(
        [ds.isel(valid_time=slice(0, 1)), ds.isel(valid_time=slice(1, None))], land=True
    )
    assert result.ghi.iloc[1:].tolist() == [100, 100]
