"""Standard-time offsets from a point's time zone (tzfpy boundaries, IANA rules)."""

import pytest

from openepw.models import Location
from openepw.planning import timezones
from openepw.planning.offsets import year_offset_warnings
from openepw.planning.timezones import LONGITUDE, LOOKUP, NAUTICAL, whole_hour, zone_offset


@pytest.mark.parametrize(("lat", "lon", "zone", "minutes"), [
    (1.2897, 103.8501, "Asia/Singapore", 480),        # longitude alone gives +7
    (42.44, -76.5, "America/New_York", -300),
    (41.0, -100.0, "America/Chicago", -360),          # western Nebraska; longitude gives -7
    (33.45, -112.07, "America/Phoenix", -420),        # no daylight saving
    (53.35, -6.26, "Europe/Dublin", 0),               # negative daylight saving in the tz database
    (39.47, 75.99, "Asia/Shanghai", 480),             # one zone across China
])
def test_offset_is_the_zone_standard_time(lat, lon, zone, minutes):
    found = zone_offset(lat, lon, 2018)
    assert (found.zone, found.source, found.offset_minutes, found.civil_minutes) == (zone, LOOKUP, minutes, None)


def test_fractional_offsets_round_to_the_hour_nearer_solar_time():
    mumbai, kolkata = zone_offset(19.076, 72.8777, 2018), zone_offset(22.57, 88.36, 2018)
    assert mumbai.zone == kolkata.zone == "Asia/Kolkata"
    assert (mumbai.civil_minutes, mumbai.offset_minutes) == (330, 300)    # 72.9 E: solar +4:52
    assert (kolkata.civil_minutes, kolkata.offset_minutes) == (330, 360)  # 88.4 E: solar +5:53
    assert zone_offset(27.7, 85.3, 2018).offset_minutes == 360            # Nepal +5:45: not a tie
    assert whole_hour(-210, -52.7) == -240 and whole_hour(570, 138.6) == 540


def test_open_sea_uses_the_nautical_zone():
    found = zone_offset(0.0, -150.0, 2018)
    assert (found.zone, found.source, found.offset_minutes) == ("Etc/GMT+10", NAUTICAL, -600)


def test_the_offset_follows_the_year():
    assert zone_offset(1.2897, 103.8501, 1980).civil_minutes == 450         # Singapore before 1982
    warnings = year_offset_warnings(
        [Location(lat=1.2897, lon=103.8501, name="Singapore", standard_offset_minutes=480)], [1980, 2018])
    assert warnings == ["Singapore: standard time in Asia/Singapore was UTC+07:30 in 1980; this file uses UTC+08:00."]
    assert year_offset_warnings([Location(lat=1.2897, lon=103.8501, standard_offset_minutes=0)], [1980]) == []


def test_an_unknown_zone_falls_back_to_longitude(monkeypatch):
    monkeypatch.setattr(timezones, "_zone_name", lambda lat, lon: "Nowhere/Unlisted")
    found = zone_offset(1.2897, 103.8501, 2018)
    assert (found.zone, found.source, found.offset_minutes) == (None, LONGITUDE, 420)
