import numpy as np
import pandas as pd
import pytest

from openepw.dataset import WeatherDataset, irradiance_to_energy, without_feb_29
from openepw.epw import read_epw, write_epw
from openepw.models import Location, OpenEPWError
from openepw.qc import validate


def synthetic(year=2023, periods=24):
    index = pd.date_range(f"{year}-01-01 01:00", periods=periods, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "dry_bulb": 20.0,
            "dew_point": 10.0,
            "relative_humidity": 50.0,
            "pressure": 101325.0,
            "ghi": 0.0,
            "dni": 0.0,
            "dhi": 0.0,
            "wind_speed": 2.0,
            "wind_direction": 180.0,
        },
        index=index,
    )
    return WeatherDataset(data=data, location=Location(lat=42, lon=-76))


@pytest.mark.parametrize("year,rows", [(2023, 24), (2023, 8760), (2024, 8784)])
def test_roundtrip_preserves_hour_24_leap_and_missing(tmp_path, year, rows):
    dataset = synthetic(year, rows)
    dataset.data.iloc[0, 0] = np.nan
    path = tmp_path / "weather.epw"
    write_epw(dataset, path)
    lines = path.read_text().splitlines()
    assert len(lines) == rows + 8
    assert all(len(line.split(",")) == 35 for line in lines[8:])
    assert lines[31].split(",")[3:5] == ["24", "60"]
    assert lines[8].split(",")[6] == "99.9"
    result = read_epw(path)
    assert len(result.data) == rows
    assert result.data.index.equals(dataset.data.index)
    assert np.isnan(result.data.dry_bulb.iloc[0])
    assert result.data.pressure.iloc[-1] == 101325
    annual = validate(result, profile="annual")
    assert ("INCOMPLETE_YEAR" in [x.code for x in annual]) == (rows == 24)


def test_native_minute_zero_and_tmy_years(tmp_path):
    d = synthetic(2001, 8760)
    p = tmp_path / "tmy.epw"
    write_epw(d, p)
    lines = p.read_text().splitlines()
    for i in range(8, len(lines)):
        fields = lines[i].split(",")
        fields[0] = str(1990 + int(fields[1]))
        fields[4] = "0"
        lines[i] = ",".join(fields)
    p.write_text("\n".join(lines))
    r = read_epw(p)
    assert r.calendar == "synthetic"
    assert r.data.index.is_unique
    assert r.source_years[0] == 1991
    assert "NATIVE_MINUTE_ZERO" in [i.code for i in r.issues]


def test_half_hour_solar_energy_and_qc():
    assert irradiance_to_energy(200, 30) == 100
    d = synthetic()
    d.data.loc[d.data.index[0], ["dew_point", "relative_humidity", "ghi"]] = [25, 105, -1]
    codes = {i.code for i in validate(d)}
    assert {"DEW_ABOVE_DRY", "RH_SUPERSATURATED", "NEGATIVE_SOLAR"} <= codes
    d.data = pd.concat([d.data, d.data.iloc[:1]])
    assert "DUPLICATE_TIME" in {i.code for i in validate(d)}


def test_pvgis_singular_daylight_header(tmp_path):
    p = tmp_path / "native.epw"
    write_epw(synthetic(), p)
    p.write_text(p.read_text().replace("HOLIDAYS/DAYLIGHT SAVINGS", "HOLIDAYS/DAYLIGHT SAVING"))
    assert len(read_epw(p).data) == 24


def test_explicit_native_noleap_calendar_roundtrip(tmp_path):
    p = tmp_path / "noleap.epw"
    d = synthetic(2001, 8760)
    d.source_years = [2048] * 8760
    write_epw(d, p)
    explicit = read_epw(p, calendar="noleap")
    assert explicit.calendar == "noleap"
    assert not any(i.severity == "error" for i in validate(explicit, "annual"))
    write_epw(explicit, p)
    result = read_epw(p)
    assert result.calendar == "noleap"
    assert result.source_years == [2048] * 8760


def test_explicit_noleap_allows_only_the_feb_29_gap():
    data = without_feb_29(synthetic(2024, 8784))
    assert len(data.data) == 8760
    assert not any(i.severity == "error" for i in validate(data, "annual"))

    data.data = data.data.drop(data.data.index[100])
    codes = {i.code for i in validate(data, "annual")}
    assert {"MISSING_INTERVAL", "INCOMPLETE_YEAR"} <= codes


@pytest.mark.parametrize("feb_29_rows", [23, 25])
def test_skip_feb_29_rejects_malformed_source_day(feb_29_rows):
    data = synthetic(2024, 8784)
    local = data.data.index.tz_localize(None) - pd.Timedelta(hours=1)
    feb_29 = (local.month == 2) & (local.day == 29)
    positions = np.flatnonzero(feb_29)
    if feb_29_rows == 23:
        data.data = data.data.drop(data.data.index[positions[0]])
    else:
        data.data = pd.concat([data.data, data.data.iloc[[positions[0]]]]).sort_index()

    with pytest.raises(OpenEPWError) as exc:
        without_feb_29(data)

    assert exc.value.issue.code == "INVALID_LEAP_DAY"
