"""A point's time zone and its fixed standard-time offset (no daylight saving).

The zone comes from offline boundary data (tzfpy, timezone-boundary-builder, ODbL 1.0); the
offset rules from the IANA tz database (zoneinfo with the tzdata package). At sea the zone is
a nautical ``Etc/GMT±N`` zone, which is the longitude rule. EPW files hold whole-hour local
standard time here, so a fractional standard offset (India, Nepal, Newfoundland, central
Australia) is rounded to the nearer whole hour; a tie goes to the hour nearer the point's
mean solar time (longitude / 15), which keeps solar geometry consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import nominal_offset_minutes

LOOKUP = "time zone"
NAUTICAL = "nautical zone"
LONGITUDE = "longitude"


@dataclass(frozen=True)
class ZoneOffset:
    zone: str | None             # IANA name, None when no zone could be resolved
    source: str                  # LOOKUP, NAUTICAL or LONGITUDE (the fallback)
    offset_minutes: int          # whole-hour standard offset written to the EPW
    civil_minutes: int | None    # the zone's own standard offset, when it differs (fractional)
    changed: bool = False        # the zone's standard offset changed during the year


def _zone_name(lat: float, lon: float) -> str | None:
    try:
        from tzfpy import get_tz
    except ImportError:                                  # optional at import, required at runtime
        return None
    return get_tz(lon, lat) or None


@lru_cache(maxsize=4096)
def _standard_minutes(zone: str, year: int) -> tuple[int, bool] | None:
    """The smallest offset in force during ``year`` (clocks spring forward from standard time;
    this also handles zones the tz database models with negative daylight saving, such as
    Ireland), and whether the standard offset itself changed during the year."""
    try:
        info = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    offsets, standards = set(), set()
    moment = datetime(year, 1, 1, tzinfo=timezone.utc)
    while moment.year == year:
        local = moment.astimezone(info)
        offset = local.utcoffset() or timedelta(0)
        offsets.add(int(offset.total_seconds() // 60))
        standards.add(int((offset - (local.dst() or timedelta(0))).total_seconds() // 60))
        moment += timedelta(days=7)
    return min(offsets), len(standards) > 1


def whole_hour(minutes: int, lon: float) -> int:
    """The nearer whole hour; a tie goes to the hour nearer mean solar time."""
    lower = (minutes // 60) * 60
    upper = lower + 60
    if minutes - lower != upper - minutes:
        return lower if minutes - lower < upper - minutes else upper
    return lower if abs(lower - lon * 4) <= abs(upper - lon * 4) else upper


def zone_offset(lat: float, lon: float, year: int | None = None) -> ZoneOffset:
    """The point's zone and fixed standard offset for ``year`` (the current year by default)."""
    year = year or date.today().year
    zone = _zone_name(lat, lon)
    standard = _standard_minutes(zone, year) if zone else None
    if zone is None or standard is None:
        return ZoneOffset(None, LONGITUDE, nominal_offset_minutes(lon), None)
    minutes, changed = standard
    rounded = whole_hour(minutes, lon)
    return ZoneOffset(zone, NAUTICAL if zone.startswith("Etc/") else LOOKUP, rounded,
                      minutes if rounded != minutes else None, changed)


def label(minutes: int) -> str:
    return f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def describe(result: ZoneOffset) -> str:
    """One point's offset and where it came from, for the location review."""
    text = label(result.offset_minutes)
    if result.source == LOOKUP:
        text += f" ({result.zone}"
        if result.civil_minutes is not None:
            text += f"; civil standard time is {label(result.civil_minutes)}, rounded to the whole hour"
        text += ")"
    elif result.source == NAUTICAL:
        text += " (at sea: nautical zone)"
    else:
        text += " (estimated from longitude)"
    return text
