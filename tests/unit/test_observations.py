import pandas as pd
import pytest

from openepw.models import OpenEPWError
from openepw.providers.noaa_isd import normalize_isd
from openepw.providers.nsrdb import parse_nsrdb


def test_noaa_flags_gaps_and_pressure_are_not_fabricated():
    rows = [
        {
            "DATE": "2024-01-01T01:00:00",
            "TMP": "+0200,1",
            "DEW": "+0100,1",
            "WND": "180,1,N,0020,1",
            "SLP": "10132,1",
        },
        {
            "DATE": "2024-01-01T02:00:00",
            "TMP": "+9999,9",
            "DEW": "+0100,2",
            "WND": "999,9,9,9999,9",
        },
    ]
    result = normalize_isd(rows, pd.date_range("2024-01-01T01:00Z", periods=3, freq="h"))
    assert result.dry_bulb.iloc[0] == 20
    assert result.wind_speed.iloc[0] == 2
    assert result.dry_bulb.iloc[1:].isna().all()
    assert "pressure" not in result
    assert 52 < result.relative_humidity.iloc[0] < 54


def test_nsrdb_interval_centers_and_hpa_to_pa():
    raw = b"Source,Location ID,Latitude,Longitude,Time Zone,Elevation\nNSRDB,1,42,-76,0,200\nYear,Month,Day,Hour,Minute,Temperature,Dew Point,Relative Humidity,Pressure,GHI,DNI,DHI,Wind Speed,Wind Direction\n2024,1,1,0,30,20,10,50,1000,200,100,100,2,180\n2024,1,1,1,30,21,11,50,1000,400,200,200,2,180\n"
    frame, loc, meta = parse_nsrdb(raw)
    assert frame.index[0] == pd.Timestamp("2024-01-01T01:00Z")
    assert frame.pressure.iloc[0] == 100000
    assert frame.ghi.sum() == 600
    assert loc.lat == 42


def test_nsrdb_empty_or_error_payload_rejected():
    with pytest.raises(OpenEPWError):
        parse_nsrdb(b'{"errors":["secret response"]}')


def test_nsrdb_native_tmy_preserves_source_years_and_standard_timezone():
    raw = b"Source,Location ID,Latitude,Longitude,Time Zone,Elevation\nNSRDB,1,42,-76,-5,200\nYear,Month,Day,Hour,Minute,Temperature,Dew Point,Relative Humidity,Pressure,GHI,DNI,DHI,Wind Speed,Wind Direction\n1999,1,1,0,30,20,10,50,1000,200,100,100,2,180\n2022,1,1,1,30,21,11,50,1000,400,200,200,2,180\n"
    frame, loc, meta = parse_nsrdb(raw, synthetic=True)
    assert frame.index[0] == pd.Timestamp("2001-01-01T06:00Z")
    assert loc.standard_offset_minutes == -300
    assert meta["source_years"] == [1999, 2022]
