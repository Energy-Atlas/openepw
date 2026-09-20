# Local monthly signal JSON

`generate_future(..., signals="signals.json")` is an explicit alternative to
online CMIP6 access. It is not an automatic fallback. Supply a JSON array of
coherent signal records, one per output model/member. Typical requires one record;
ensemble retains each record. The schema is `openepw.generation.morph.MonthlySignal`.

Required provenance: `model`, `member`, `scenario`, `reference_period`,
`climate_period`, `license`, `source_uri`, `source_checksums`. Periods are two-element
inclusive year arrays. Optional `calendar`, `source_location` and `warnings` retain
source context. Each numeric array has twelve finite values in January–December
order; absent transform arrays explicitly default to identity:

| Field | Units | Meaning / identity |
| --- | --- | --- |
| temperature_delta | K | future minus reference; required |
| dtr_delta | K | change in mean daily temperature range; 0 |
| humidity_delta | percentage_point | change in relative humidity; 0 |
| pressure_delta | Pa | change in surface pressure; 0 |
| wind_ratio | 1 | future/reference wind; 1 |
| solar_ratio | 1 | future/reference shortwave; 1 |

The `units` mapping must match this table exactly when supplied. Negative ratios,
missing months, nonfinite values and mismatched requested scenario/windows fail.
If you intentionally apply temperature-only changes, document that reduced transform
set in `warnings` and the source methodology. Extreme local signals must additionally
identify `profile_year`; the caller is responsible for recording its ranking method.
Local signal files are snapshotted and checksummed during planning.

The online backend supplies every transform from a seven-variable intersection,
checks units and monthly completeness, and weights climatologies using each source
calendar's actual month lengths. It rejects zero-reference/nonzero-future ratios.
Historical and scenario series are joined across 2014/2015 when the reference
window requires it; periods are never silently truncated.
