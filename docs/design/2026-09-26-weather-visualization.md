# Weather visualization contract

**Status:** Design for the first JSON-only implementation and later renderers.
**Owner decision:** Define the full framework-neutral contract now; implement a
smaller first family set. The CLI prints JSON and does not draw charts.

## Purpose and boundaries

An agent should turn an existing EPW artifact into a reproducible analytical
view and a rendering instruction without moving hourly tables through model
context. OpenEPW owns weather semantics, source selection, units, calculations,
missing-data decisions and plot-family selection. A later client owns fonts,
colors, interaction and actual rendering. The Python service is canonical;
MCP and CLI are adapters. No future-weather generation or simulation-readiness
judgment is introduced by this design.

Visualization calls consume existing weather EPW IDs or uploaded EPW IDs. They
never trigger provider retrieval. Source IDs and checksums, normalized request,
transforms, coverage and warnings make every result reproducible. A reference
product is labelled as such; an uploaded EPW does not acquire an invented
provider or actual-year identity. Existing future-job outputs are rejected
while future-weather MCP access is suspended.

## Tool surface

| Tool | Purpose | First release |
| --- | --- | --- |
| `weather_visualization_capabilities` | Enumerate every family, support status, input shape and limits | Yes |
| `weather_data_describe` | Inspect bounded artifact, period, variable, unit and missing-count metadata | Yes |
| `weather_visualize` | Resolve explicit artifacts and one intent; prepare data and return one or more `VisualizationSpec` objects | Yes, initial families |
| `weather_data_page` | Read a bounded page of immutable prepared rows by view ID; offset zero also returns the spec | Yes |

The common path is one `weather_visualize` call. It returns a compact spec,
summary, first page and stable `view_id`; later pages use `weather_data_page`.
The MCP has no session-local source selection. The chat layer resolves “these
years,” “that file,” and numbered outputs to artifact IDs before calling it.
Errors are typed and actionable: `INVALID_ARTIFACT`, `INVALID_VARIABLE`,
`INVALID_AGGREGATION`, `INCOMPATIBLE_SOURCES`, `NO_MATCHING_DATA`,
`VISUALIZATION_UNSUPPORTED`, `RESOURCE_LIMIT`, and `FEATURE_SUSPENDED`.

## Request and result contract

`VisualizationRequest` version 1 has `artifact_ids` (ordered unique IDs),
`family`, `variable`, optional `aggregation`, `allow_partial` (default false),
and family-specific `options` such as histogram bin count. Optional filters
are explicit local-standard-time ranges, months, hours and numeric predicates;
the capability result identifies which are active for each family. Unsupported
options fail rather than being ignored. A result ID is a digest of the
normalized request, source checksums and contract version.

`VisualizationSpec` version 1 is library-neutral JSON with:

- `family` from the finite vocabulary below and `data_ref` containing the
  `view_id`, shape, total rows and paging tool;
- `encodings` naming x/y/series or latitude/longitude/value fields, with
  canonical variable IDs, units and semantic time axis;
- `transforms` in execution order (selection, filter, grouping, statistic,
  comparison, derivation); no arbitrary executable expressions;
- `sources` with artifact ID, checksum, temporal kind, calendar, location and
  verified or unverified product identity;
- `quality` with expected/valid/missing interval counts and flags, both for
  the view and each prepared point;
- a concise factual `summary`, warnings and optional annotations, derived
  from the same prepared data rather than invented by the model.

Prepared data is immutable JSON addressed by `view_id`. `weather_visualize`
returns at most a bounded first page. `weather_data_page(view_id, offset,
limit)` returns rows and `next_offset`; offset zero also returns the spec so
a restarted client can recover it. The CLI prints the JSON response and may
page explicitly; it never emits a plotting-library configuration or image.
A future frontend validates the version and family, pages data and dispatches
to its own renderer registry.

Example, with intentionally null monthly value:

```json
{
  "schema_version": "1",
  "view_id": "content-digest",
  "specs": [{
    "family": "monthly_series",
    "data_ref": {"view_id": "content-digest", "shape": "rows", "total_rows": 12},
    "encodings": {
      "x": {"field": "period", "kind": "local_month"},
      "y": {"field": "value", "variable": "ghi", "unit": "Wh/m2"},
      "series": ["artifact_id"]
    },
    "transforms": [{"operation": "group", "by": ["artifact_id", "year", "month"]},
                   {"operation": "aggregate", "method": "sum"}],
    "sources": [{"artifact_id": "epw-id", "sha256": "source-sha",
                 "temporal_kind": "actual", "calendar": "gregorian"}],
    "quality": {"expected_hours": 8784, "valid_hours": 8740,
                "missing_hours": 44},
    "summary": "One monthly total is unavailable because 44 hours are missing."
  }],
  "rows": [{"artifact_id": "epw-id", "year": 2016, "month": 1,
            "period": "2016-01", "value": null,
            "expected_hours": 744, "valid_hours": 700,
            "missing_hours": 44, "quality": "incomplete"}],
  "next_offset": 1
}
```

## Scientific semantics

The EPW reader turns each field's missing sentinel into null. No sentinel is
averaged, summed or interpreted as zero. Group by fixed local standard-time
**interval start**. Preserve Gregorian leap days and explicitly declared
no-leap or synthetic calendars; never assume exactly 8,760 valid records.
Missing timestamps count as missing intervals. With `allow_partial=false`, a
group containing any missing interval has a null result. `allow_partial=true`
may emit an observed-only result marked partial; it never scales a sum to a
full-period estimate. Coverage accompanies each result point.

The variable registry defines canonical IDs, units, permitted statistics and
dependencies. Temperature means use `degC`; GHI/DNI/DHI hourly entries are
interval energy in `Wh/m2`, so their default monthly/annual operation is sum.
Wind direction uses circular statistics when aggregation is eventually added.
Precipitation accumulation semantics must be verified before a total is
offered. Mixed units or temporal kinds cannot be compared implicitly.
Duplicate location/year sources stay as separate series unless an explicit
comparison is requested. A spatial grid is emitted only for a complete
rectilinear coordinate set; otherwise a point layout is returned without
interpolation. No chart asserts simulation readiness.

## Finite family catalog

The full catalog is part of the contract now. Capability metadata reports
`implemented` or `planned` for each entry. A planned family returns
`VISUALIZATION_UNSUPPORTED` with available alternatives and does not produce
a fabricated spec. Families can become active without changing the tool list.

| Family | Intended prepared data | Status |
| --- | --- | --- |
| `time_series` | Local hourly values, one or more labelled sources | Initial |
| `annual_series` | One aggregated point per actual year/source/location | Initial |
| `monthly_series` | One aggregated point per year-month/source/location | Initial |
| `histogram` | Counts and shared numeric bin edges | Initial |
| `spatial` | Point values or a complete rectilinear matrix | Initial |
| `month_of_year_profile` | Cross-year monthly profile with contributing-year counts | Planned |
| `diurnal_profile` | Hour-of-day values and optional percentile band | Planned |
| `seasonal_summary` | Explicit season definitions and aggregate values | Planned |
| `calendar_heatmap` | Day-by-day values and calendar labels | Planned |
| `month_hour_heatmap` | Month × local-hour values | Planned |
| `cumulative_distribution` | Empirical cumulative proportion | Planned |
| `duration_curve` | Ordered exceedance values | Planned |
| `box_plot` | Quantiles and whisker rule by group | Planned |
| `scatter` | Aligned paired variables or sources | Planned |
| `correlation_matrix` | Pairwise complete-case coefficients and sample counts | Planned |
| `wind_rose` | Circular direction bins crossed with speed bins | Planned |
| `psychrometric` | Explicit psychrometric derivations and point density | Planned |
| `threshold_timeline` | Matching intervals and grouped exceedance counts | Planned |
| `extreme_event_timeline` | Reproducible event definition, duration and intensity | Planned |
| `difference_series` | Aligned source/year differences with alignment policy | Planned |
| `anomaly_series` | Values relative to an explicit reference period | Planned |
| `summary_table` | Compact variable/QC statistics | Planned |

The contract can return multiple coordinated specs in one response, but the
first release produces one. “Typical day,” “summer,” “heat wave,” “best,” and
other ambiguous terms require a documented policy or clarification before a
calculation; no renderer invents their meaning. The supplied query examples
serve as an evaluation corpus, including explicit unsupported cases.

## First implementation and limits

The initial five families accept one canonical numeric variable. `time_series`
pages hourly values. `annual_series` and `monthly_series` support registry-
allowed mean, sum, min and max; no slope or climate inference is implied.
`histogram` returns shared edges and counts, with nulls excluded and coverage
reported. `spatial` produces one comparable period statistic per location;
regular grids use ordered axes and a value matrix, irregular sets use points.
Source-to-source difference metrics, derived variables, arbitrary predicates,
event detection and multi-variable plots remain planned and explicit.

Initial limits: 100 source EPWs for aggregate views, 20,000 prepared rows for
hourly views, 50 histogram bins, 200 rows per page and 160 KB per MCP result.
The service verifies source checksums, bounds decoded EPW size, and stores
immutable prepared JSON under the local data root. Neither credentials nor
local user paths enter spec, result storage, model context or traces.

Acceptance uses synthetic annual, leap, no-leap, reference-product and
sentinel-bearing EPWs. Test exact aggregates and coverage, null/partial policy,
source identity, spatial regularity, paging/restart, capability reporting,
unsupported families, MCP size bounds and CLI JSON. Live provider calls and
chart rendering are unnecessary for this first implementation.
