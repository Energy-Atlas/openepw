# Open-Meteo

## v0.1 implementation result — 2026-09-20

The ERA5 adapter passed a full 2024 local-standard-year check (8,784 hours). UTC padding, returned units, pressure conversion, hourly solar energy and coverage are checked. ERA5-Land is an explicit selectable model but is not included in the final live acceptance matrix; missing provider variables remain explicit. Native response location is recorded; unknown planning cells are not rounded into artificial reuse.

## Earlier source/access review

Use `/v1/archive` with `models=era5`, UTC and `wind_speed_unit=ms`.
The Ithaca probe resolved to 42.5, -76.5 and returned temperature, dew point, RH,
surface pressure, GHI, DNI, DHI and wind speed/direction without nulls. Pressure is
hPa and radiation W/m²; normalize units and interval meaning before EPW output.
Native resolution is not the elevation-adjusted output resolution.

Explicit ERA5-Land returned 24 temperature/humidity values but 24 nulls each for
solar and wind. Do not silently select `best_match` or `era5_seamless`; these mix
models. An approved hybrid may select Land temperature with ERA5 radiation/wind
and retain per-variable source metadata. [Archive documentation](https://open-meteo.com/en/docs/historical-weather-api).

Data: CC BY 4.0. Free hosted service: noncommercial only, under 10,000 calls/day,
5,000/hour and 600/minute; weighted requests may count as more than one call.
Support a configured commercial endpoint/key without purchasing anything.
Server implementation is AGPL; use HTTP, do not incorporate that code.
[Terms](https://open-meteo.com/en/terms), [code license](https://github.com/open-meteo/open-meteo).

Separate geocoding endpoint returned two Ithaca candidates. Initial geocoding
supports named representative points and ambiguity metadata; area/airport resolver
modes must report unsupported until a suitable resolver is added. GeoNames-backed
results require attribution. [Geocoding documentation](https://open-meteo.com/en/docs/geocoding-api).

Status: access validated; adapter, full-year boundary alignment and tests planned.
