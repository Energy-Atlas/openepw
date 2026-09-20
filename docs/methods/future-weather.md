# Proposed future methods

These are Stage 2 designs, not implemented features. `generate_future` accepts a
baseline EPW/artifact and reports what role that baseline plays. A requested target
year represents a climate period, never a literal forecast. Unsupported scenario,
period, profile or variable combinations fail explicitly.

## A — CMIP6 monthly morphing

Implement Belcher-style shift/stretch from published equations in OpenEPW, using
permissive psychrometrics. Do not wrap pyepwmorph while its internal license issue
remains. References: [Belcher et al. (2005)](https://doi.org/10.1191/0143624405bt112oa),
[Jentsch et al. (2013)](https://doi.org/10.1016/j.renene.2012.12.049).

For month m, temperature uses `T' = T + delta_m + alpha_m*(T - mean_baseline_m)`;
delta is model future-minus-reference mean; alpha is the change in modeled diurnal
range divided by baseline mean diurnal range. A zero denominator falls back to
shift-only with a warning. Pressure uses a difference; wind/solar use nonnegative
ratios with explicit zero-reference handling. Humidity transformations must
recompute dew point consistently and record any clipping. Never silently retain
stale humidity after changing temperature. Validate energy closure for radiation.

Climate source: versioned Pangeo CMIP6 Zarr catalog, optional xarray/fsspec/zarr
stack. Probe verified a matched GFDL-CM4 r1i1p1f1 historical/ssp245 `tas` pair and
its calendar, units, dimensions and license. Large 600-month global chunks remain
a performance risk; planning must estimate them before data access. Full required
variable intersection and numeric decoding are early Stage 2 acceptance tests.
Accept a documented local monthly-signal table too, with units, model, member,
reference/target periods, license, source URI and checksum; it cannot be unlabeled
hardcoded warming. Expose only models/scenarios with the required variable set.

Default target-year window: year−14 through year+15 (2050 → 2036–2065); explicit
period wins. Baseline reference period must come from reliable product metadata or
an explicit request, not from mixed TMY row years. Require it when unknowable.
Record actual coverage and reject silent window truncation. Month grouping uses
the source calendar; never convert a 360-day series into Gregorian dates by fiat.

`typical`: apply climatological signals from one coherent model/member.
`ensemble`: one full EPW per model/member; no independent variable quantile mixes.
`extreme`: select a coherent model-year signal by annual warming rank (default
nearest-rank 95th percentile) and label this an extreme warming sensitivity profile,
not a heatwave probability model. Shock/persistence demands use method B where
supported; A rejects those modes rather than overstating monthly information.
`sampled`: reserved experimental capability, structured unsupported result in v0.1.

## B — select coherent profiles from dynamically downscaled hourly trajectories

Use [Argonne/OEDI dataset 5974](https://data.openei.org/submissions/5974), DOI
10.25984/2202668, CC BY 4.0. WRF 3.3.1 driven by CCSM4 supplies hourly EPWs at
published U.S. PUMA centroids (Hawaii excluded), not arbitrary North American
grid cells. Native WRF spacing is 12 km; delivered sites are a sparse subset.
Only RCP4.5/RCP8.5 and 2045–2054 / 2085–2094 are available in this source. Never
translate SSP245 to RCP4.5 or promise model ensembles this archive does not have.

Real range/ZIP64 extraction validated a full 2045 EPW from RCP8.5 v1.1 with 35
fields. Implement a cached archive index keyed by ETag, conditional range reads,
CRC validation and bounded decompression. Refuse an ignored Range response rather
than downloading 9 GB unexpectedly. Resolve available member names against the
updated location table; the advertised number of PUMAs is not proof every member
exists. [Probe](../validation/2026-09-20-future-archive.json).

Baseline input supplies the requested site and an auditable comparison identity;
it is **not morphed**. Use the archive's 1995–2004 paired baseline for model-relative
comparisons and extreme thresholds, as recommended by the authors. Warn when a
user EPW has a different baseline/source. Do not replace its location silently.

Construct profiles across the ten candidate years at the resolved site:

- `typical`: select the whole-year medoid using monthly mean temperature, RH,
  wind and monthly total GHI; normalize each feature by across-year spread, omit
  zero-spread features, equal-weight variable groups, choose lowest total distance
  and earliest year for ties. This is representative model-year selection, not
  standardized TMY generation or a month-splicing algorithm.
- `extreme`, hot shock: select the whole year with the largest 3-day mean daily
  maximum temperature; cold reverses the statistic using daily minimum.
- `extreme`, hot persistence: select the year with the longest consecutive run of
  daily mean temperature above the paired baseline's seasonally conditioned 95th
  percentile (calendar-day ±15 days); cold uses the 5th percentile. Quantile,
  threshold source and ties are recorded. Keep the full year's covarying fields.
- `ensemble`: output selected individual trajectories with
  `ensemble_kind=temporal_years`, not an invented multimodel ensemble.

For B, 2050 resolves to the explicit 2045–2054 archive window and 2090 to 2085–2094;
other years must lie inside a supported window or provide that exact period.
The caller can instead supply licensed hourly climate data with equivalent
metadata. Baseline years are used only to calibrate future profiles, never to
generate retrospective TMY/XMY.

Known issue: authors flag anomalous Great Plains warming in late-century RCP4.5.
Surface that warning on every affected-period request rather than concealing it.
Residual model bias, sparse locations, single driving model and ten-year sample
limits accompany outputs. No claimed return periods.

## Alternatives considered

Open-Meteo Climate returned three populated future days, but is daily-only with
a HighResMIP scenario convention and approximately 1950–2050 coverage. It cannot
directly supply hourly SSP245 weather. Inventing diurnal sequences now adds more
scientific uncertainty than the validated hourly archive, so defer that backend.
Its response extended into July 2050 despite inconsistent documentation on the
end date: discover availability rather than hardcoding a claimed exact final day.
[Climate API](https://open-meteo.com/en/docs/climate-api).

Two wrappers around monthly morphing were rejected as insufficiently distinct.
The chosen A changes a baseline sequence; B selects new hourly model trajectories.
