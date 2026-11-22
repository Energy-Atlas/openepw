"""Station pressure from a station's own pressure reports.

EPW wants station pressure (at the barometer), but many weather stations report only the
altimeter setting (QNH) or the sea-level pressure. Both are defined from station pressure, so
station pressure can be worked back out from them with the station elevation:

* Altimeter setting: by definition an altimeter set to it reads the station elevation in the
  ICAO standard atmosphere, so ``p = (A**n - K * z) ** (1 / n)`` with n = 0.190263 and
  K = 8.417286e-5 hPa**n per metre (Smithsonian Meteorological Tables; the US National
  Weather Service altimeter equations). It is exact apart from the 0.1 hPa rounding of A.
* Sea-level pressure: inverted with the hypsometric equation over a fictitious air column
  from the station to sea level, whose mean temperature is the station temperature plus half
  the standard 6.5 K/km lapse over the column (dry air, no humidity term). National services
  reduce pressure to sea level in different ways, so the result is approximate and is used
  only for stations at most ``SLP_MAX_ELEVATION_M`` above sea level.

Values are in hPa and metres; arrays work element by element.
"""

from __future__ import annotations

import numpy as np

GRAVITY = 9.80665              # m/s2
DRY_AIR_GAS_CONSTANT = 287.05  # J/(kg K)
STANDARD_LAPSE = 0.0065        # K/m
ALTIMETER_EXPONENT = 0.190263
ALTIMETER_K = 8.417286e-5      # hPa**n per metre
SLP_MAX_ELEVATION_M = 500.0


def from_altimeter(altimeter_hpa, elevation_m):
    """Station pressure (hPa) from the altimeter setting (hPa) and station elevation (m)."""
    altimeter = np.asarray(altimeter_hpa, dtype=float)
    return (altimeter ** ALTIMETER_EXPONENT - ALTIMETER_K * float(elevation_m)) ** (1 / ALTIMETER_EXPONENT)


def from_sea_level(sea_level_hpa, dry_bulb_c, elevation_m):
    """Station pressure (hPa) from sea-level pressure (hPa), station air temperature (°C) and
    station elevation (m), or NaN above ``SLP_MAX_ELEVATION_M``."""
    sea_level = np.asarray(sea_level_hpa, dtype=float)
    if float(elevation_m) > SLP_MAX_ELEVATION_M:
        return np.full(np.shape(sea_level), np.nan)
    column = np.asarray(dry_bulb_c, dtype=float) + 273.15 + STANDARD_LAPSE * float(elevation_m) / 2
    return sea_level * np.exp(-GRAVITY * float(elevation_m) / (DRY_AIR_GAS_CONSTANT * column))
