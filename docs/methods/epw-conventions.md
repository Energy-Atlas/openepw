# EPW contract for Stage 2

Use the current [EnergyPlus auxiliary-programs dictionary](https://energyplus.readthedocs.io/en/latest/auxiliary-programs/auxiliary-programs.html#energyplus-weather-file-epw-data-dictionary)
and verify against a stable EnergyPlus release during implementation. The web
reader exposed the dictionary; direct urllib returned 403 on the versioned page.

Eight header records and 35 data columns. Canonical hourly writer: hours 1–24,
minute 60, local fixed standard-time offset; no DST shift. Preserve original year
labels for published TMY month provenance separately from the synthetic calendar.
Parser supports valid partial periods; annual-output validation is a separate
requirement. Preserve 8,784 rows for actual leap years unless an explicit recorded
policy removes Feb 29. Future representative years default to 8,760 with the leap
policy recorded. Never discard leap data implicitly.

| Fields | Missing sentinel | Format/QC distinction |
| --- | --- | --- |
| Dry bulb / dew point °C | 99.9 | Dictionary range roughly −70 to 70; physical QC can be stricter |
| Relative humidity % | 999 | Format permits 0–110; >100 is a physical warning |
| Station pressure Pa | 999999 | 31,000–120,000; sea-level pressure is different |
| Radiation Wh/m² over interval | 9999 | Check nonnegative, interval energy and solar consistency |
| Wind direction degrees | 999 | 0–360; use circular aggregation |
| Wind speed m/s | 999 | Nonnegative; plausibility and missingness separate |
| Sky cover tenths | 99 | Preserve missing, do not replace with zero |

All other fields receive their field-specific dictionary sentinels, not a common
blank/zero. Preserve uncertainty flags. Missing essential variables produce strong
QC warnings (or strict-profile errors), not automatic fabricated values. Missing
optional fields do not invalidate an EPW.

Empirical compatibility case: PVGIS, OneBuilding and OEDI samples all use minute
0 in hourly rows. Accept that known convention with a warning, interpret hour 1
as the first hourly interval, and emit minute 60 when normalizing. Preserve raw
downloaded artifacts and hashes. Do not interpret hour 24 as an invalid datetime.

Internally retain interval start/end plus measurement semantics (instantaneous,
mean, accumulated). UTC API requests need boundary padding before conversion to
a local standard-time year. Irradiance W/m² is not numerically interchangeable
with Wh/m² for arbitrary intervals. Record resampling and derivations. Nighttime
solar QC needs location and interval-aware solar geometry.

Acceptance: synthetic sentinel/partial/leap fixtures, real-source opt-in structure
checks, timestamp and energy-conservation tests, and an EnergyPlus weather smoke
path when executable setup is practical. No EnergyPlus execution occurred in Stage 1.
