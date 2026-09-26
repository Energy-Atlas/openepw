# Post-retrieval conversations and data views — revised plan

**Status:** Draft for owner review. The temporary future-weather MCP suspension
was authorized and implemented in `fa94923`. Download and data-view behavior
below remains planned and awaits owner review.

**Goal:** After weather retrieval, users can identify their outputs, download
existing artifacts to their own disk, ask factual questions about the data, and
request structured summaries suitable for later chart rendering. Follow-up
turns preserve the right job, output, location and year without starting a new
provider retrieval.

## Terminology and scope

- **Retrieve/fetch weather:** contact a weather provider and create a server-side
  job/artifact. This can incur provider work.
- **Download an artifact:** transfer an existing server artifact to the user's
  disk. `/download` replaces all `/save` commands and wording. “Download the
  2016 EPW” means this transfer; it does not repeat provider retrieval.
- **Upload an EPW:** send a user-provided file to the server for analysis. A file
  already downloaded to the user's disk can be uploaded as a new analysis input.
- **Data view:** a versioned, structured summary computed from existing EPW
  artifacts. No chart image, ASCII plot or plotting library is part of this
  phase. A later plot-friendly client renders the returned data; that client
  may eventually call additional MCP tools if needed.

The plan removes the proposed “Is this ready for EnergyPlus?” conversation.
QC and missing-data facts remain available where needed to interpret a data
view, with no simulation-readiness advice workflow.

## Temporary future-weather MCP suspension

Future generation is out of the conversation and data-view scope. The MCP
tool list must omit `future_plan`, `future_submit`, and the compatibility alias
`weather_generate_future`. Reject `weather_plan(kind="future")`, future-kind
`weather_assess` queries, and `job_retry_failed` on a future job with a stable
`FEATURE_SUSPENDED` code. The console must not plan or submit future weather
when asked; it gives a short suspension response. Generic `plan_inspect`,
`job_inspect`, artifact inspection and resource reads remain available for
existing jobs and artifacts. Existing running jobs are not cancelled by this
change. Existing future artifacts may still be inspected or downloaded, but
the new data-view tools reject future-job outputs during this suspension. The
Python scientific core and REST service are outside this MCP-only ban.

The current `baseline_upload` and `baseline_register_path` names are tied to
future generation. In the same suspension change, replace their MCP
registrations with generic `epw_upload` and allowed-root `epw_register_path`
input tools, and update the console upload command to call the generic tool.
The new names support user-provided EPWs for data views. Existing registered
artifact IDs remain readable. The future endpoints stay absent from the
default MCP surface until the owner explicitly restores them. Tests inspect
the MCP tool list and exercise every compatibility or retry path above.

## Existing behavior that needs repair

LangGraph checkpoints one latest job and a tuple of artifact IDs. Some exact
status/file phrases are recognized before model extraction, while other
follow-ups fall through to an unknown weather request. A multi-output job has
no durable chat mapping from requested year/location to artifact ID. A failed
new job can leave an older artifact tuple as the apparent current result.
`/status` currently calls `resume`, which can wait for the running job to end.

The canonical evidence already exists: `job_inspect` reports job state and
artifact references, and a checksum-verified manifest links weather batch rows
to output status and artifact ID. The console will use that mapping rather
than artifact order or guessed filenames.

## Conversation behavior

| User says | Planned behavior |
| --- | --- |
| “What did I get?”, “Where are my EPWs?” | List numbered outputs with location, actual year or reference-product label, status and artifact ID. Explain that server artifacts have no user-disk path until downloaded. |
| “Which one is 2016?” | Match the manifest row. If multiple locations or duplicate occurrences match, present choices, including **Other…** in the interactive console. |
| “Download the 2016 EPW to C:\\weather” | Resolve the output, transfer its verified bytes to an explicit user destination, avoid overwrite, and report the resulting local path. |
| “Download all” | Ask for a destination directory, transfer only emitted outputs with safe deterministic names, and report successes and failures. Offer the existing compact ZIP export as a separate explicit option. |
| “How is the download going?” | If an artifact transfer is in progress, report transfer progress. “How is weather retrieval going?” inspects the provider job once. `/resume` remains the wait/watch command. |
| “What happened to 2017? Retry it.” | Explain recorded job issue codes. The existing retry tool retries every failed output; if 2017 is not the only failure, state that scope before retrying. |
| “Show monthly GHI totals for 2012–2018” | Resolve actual-year artifacts, request a typed monthly summary, and give a short factual response plus the structured result reference. |
| “Plot temperature across these locations” | Return typed spatial data and an advisory view hint. The CLI reports a compact table/summary and does not render a plot. |
| “Thanks”, “What can I do next?” | Offer relevant artifact download and data-summary actions without creating a plan. |

Pure follow-ups make no new `weather_plan` or `weather_submit` call. A turn
containing both a follow-up and a new retrieval request executes both in user
order. Follow-ups never erase a pending draft or reviewed plan.

## Structured data-view design

### Inputs and interpretation

The MCP request identifies sources explicitly by **one job ID or a list of
artifact IDs**. The conversation layer resolves “these”, “last”, numbered
outputs, years and locations to those IDs; the MCP server has no implicit
conversation memory. Inputs include completed weather EPWs and uploaded EPWs.
Failed/cancelled output rows are reported as omissions and never treated as
files. An uploaded EPW with unverified historical identity can be summarized
within its own calendar; it cannot be silently assigned to a real trend year.

The view request carries a canonical variable, temporal scope, grouping,
aggregation, optional year/month/location filters, histogram bins where
relevant, and an explicit `allow_partial` flag. Natural-language aliases map
through a controlled registry: “temperature” can mean `dry_bulb`, while
ambiguous terms such as “solar” or “wind” require a choice. A describe tool
lists available variables, units, calendar/period labels, locations, missing
counts and permitted aggregations before the agent makes a view request.

Initial view families:

| View | Grouping and result | Example |
| --- | --- | --- |
| Annual series | One period value per actual year and location; line/bar hint | Annual mean dry-bulb temperature, 2012–2018 |
| Monthly series | One value per year × month × location | Monthly GHI total for 2016, or 2012–2018 |
| Month-of-year profile | First aggregate each year-month, then summarize corresponding months across selected years; retain contributing-year counts | Mean January temperature across 2012–2018 |
| Spatial snapshot | One comparable period value per location; rectilinear matrix only for a complete regular coordinate grid, otherwise point records | 2018 annual mean temperature across locations |
| Distribution | Bounded histogram bins, counts and quantiles, optionally grouped by year or location; no raw hourly series in the tool response | Distribution of hourly dry-bulb values in 2018 |

“Trend” in this phase means an ordered annual series. No fitted slope,
significance or climate-change inference is produced by default. Published
TMY/TMYx can have monthly and distribution views labelled **reference year**;
mixed source-year labels never become an actual-year trend. When “monthly
average across many years” could mean per-year months or a 12-month profile,
the agent asks which grouping is wanted.

### Scientific and quality rules

- Use the canonical EPW reader. Its field-specific sentinels become nulls;
  never treat NOAA gaps, missing solar fields or other sentinels as zeros.
- Group intervals by fixed local standard-time **interval start**, preserving
  the declared Gregorian, no-leap or synthetic calendar and all actual leap
  hours. Include expected, valid and missing hour counts for every result
  point. Do not silently align unlike local years by UTC date.
- Default to a null summary value when any required interval is missing. An
  explicit `allow_partial=true` may return an observed-only value marked
  `partial`; a partial sum is never scaled to an estimated complete sum.
- Use a variable registry with units, allowed operations and defaults.
  Temperature/humidity/pressure/wind-speed means and extrema, and
  GHI/DNI/DHI interval-energy sums are first-class. An explicit mean of
  hourly solar energy retains its interval-energy unit and label. Wind
  direction requires circular aggregation; ordinary arithmetic mean and sum
  are invalid. Unverified precipitation interval semantics or categorical
  weather codes are not silently aggregated.
- Compare locations only for the same variable, unit, aggregation and
  period. A spatial `imshow` hint requires a complete rectilinear grid;
  irregular sites return point data without interpolation. Duplicate
  location/year outputs from different sources stay separate until the
  user selects a source; no silent average across providers. Keep both
  requested and resolved coordinates and identify which is used for the
  spatial axes.
- Keep source artifact IDs and hashes, requested/resolved location, product
  temporal kind, period, units, calendar, variable lineage summary, coverage
  and warnings with the result. Do not claim a plotted pattern is a forecast
  or a validated simulation input.

The EnergyPlus EPW dictionary identifies radiation as interval energy
`Wh/m2`, wind direction as degrees, and liquid precipitation depth as mm with
a separate accumulation-period field. These distinctions inform the variable
registry: [EnergyPlus EPW dictionary](https://energyplus.readthedocs.io/en/latest/auxiliary-programs/auxiliary-programs.html).

### MCP contract and response

Implement the computations in the shared Python service. MCP remains a thin
adapter so Python, REST and CLI can use the same summary definitions. The
proposed MCP tools are:

1. `weather_data_describe(source_selector)` — bounded source/variable/period
   inventory and allowed operations; no hourly payload.
2. `weather_data_view(view_request)` — validate and compute an immutable,
   versioned result. Return a short factual summary, provenance, total row
   count, first page and result ID.
3. `weather_data_page(result_id, offset, limit)` — read later pages of the same
   immutable result. Existing artifact resources may carry the full JSON
   result when within resource limits.

The result uses a discriminated `series`, `spatial` or `distribution` shape.
Every shape has `schema_version`, normalized request, variable/unit,
source references, temporal kind, grouping/aggregation, quality warnings and
an advisory `view_hint`. Series and irregular spatial results use tidy rows
with dimension keys and `value`, `expected_hours`, `valid_hours`,
`missing_hours`, `quality`. Regular spatial results additionally contain
ordered latitude/longitude axes and a same-shape value/quality matrix.
Distribution results contain explicit bin edges, counts, quantiles and sample
coverage. Comparable grouped histograms share bin edges. No chart-specific
color, styling or image bytes enter this contract.

An illustrative incomplete monthly result, with placeholder IDs and no
invented weather value:

```json
{
  "schema_version": "1",
  "result_id": "view-id",
  "shape": "series",
  "variable": "ghi",
  "unit": "Wh/m2",
  "aggregation": "sum",
  "temporal_kind": "actual",
  "group_by": ["year", "month", "location"],
  "rows": [{
    "artifact_id": "epw-id",
    "year": 2016,
    "month": 1,
    "location_id": "location-id",
    "value": null,
    "expected_hours": 744,
    "valid_hours": 700,
    "missing_hours": 44,
    "quality": "incomplete"
  }],
  "total_rows": 12,
  "next_offset": 1,
  "warnings": [{"code": "INCOMPLETE_PERIOD"}],
  "view_hint": "line"
}
```

The matching agent response would say: “January 2016 GHI total is unavailable:
700 of 744 hourly values are present. No partial total was calculated. Result
`view-id` contains the monthly rows.” The result also carries normalized
request and source/provenance references in its metadata; the example shows
the first page only.

Results are bounded: the first page and follow-up pages respect the MCP
response limit; the service processes source EPWs one at a time. Initial
limits are 100 source EPWs, 50 histogram bins and 200 rows per page. A larger
request returns a typed limit or a
result ID with paging rather than an oversized MCP message. The agent's
response cites the grouping, unit, coverage and any null/partial results and
provides the result ID; it does not invent numeric observations. The CLI may
print a concise table or JSON, but no plots.

Artifact download uses the existing checksum-verified MCP resource for files
within its 10 MB limit. If a compact ZIP exceeds that limit, report it
explicitly and offer individual EPW downloads until a bounded chunked
transfer is designed; an export ID alone is not a completed user download.

## Implementation sequence after review

1. **Suspend future MCP paths — completed before plan review.** Remove dedicated future registrations,
   reject compatibility and future retry paths, remove future chat choices,
   and replace future-named upload tools with generic EPW input tools.
   Test tool-list visibility and explicit `FEATURE_SUSPENDED` errors.
   Preserve read-only access to existing artifacts. Committed as `fa94923`.
2. **Repair post-retrieval references and download.** Add a bounded recent-job
   index in LangGraph state, derive output mapping from verified manifests,
   migrate old checkpoints, and distinguish current failed jobs from older
   results. Replace `/save` with `/download`; download uses the artifact
   resource and writes to the client/user disk with exclusive create and
   cleanup of incomplete writes. Keep paths/bytes outside model input,
   checkpoints and traces. Test one/many/duplicate outputs, restart, failed
   jobs, no overwrite and no provider call. Commit this boundary.
3. **Define data-view schemas and calculation core.** Add source selection,
   variable registry, calendar/coverage rules and the five view families to
   the shared Python service. Test synthetic analytic cases for means, sums,
   circular direction, leap/no-leap, published TMY, missing sentinels,
   partial coverage, mixed units, distributions and regular/irregular grids.
   Commit this boundary.
4. **Expose bounded data-view MCP tools.** Add describe/view/page tools,
   immutable result storage, provenance and typed limits. Test real stdio
   calls and response-size/pagination behavior, with no EPW bytes or secrets
   in model context or logs. Commit this boundary.
5. **Route user follow-ups and format responses.** Extract ordered actions
   for listing, selecting, downloading, status, retry and data views in at
   most one model call per ordinary turn. Keep direct commands deterministic;
   pass a placeholder for user paths to the model. Test paraphrases and
   mixed-action turns. Provide factual text and result IDs, never CLI plots.
   Commit this boundary.
6. **Acceptance and documentation.** Run an offline real-stdio journey from
   multi-year retrieval through year selection, download, monthly/annual
   summaries, restart and retry. Run harness/unit/pilot tests, Ruff, mypy and
   optional small live model smoke within the established budget. Do not
   change `.env`. Update harness docs, features, limitations and the MCP
   contract. Commit the verified result.

## Acceptance examples

- “Download my 2016 file” chooses the artifact by manifest year and transfers
  from the server resource to an explicit client destination. It never starts
  weather retrieval.
- “Annual average dry-bulb temperature across Cambridge 2012–2018” returns
  seven ordered, unit-labelled values or nulls with per-year coverage. A NOAA
  missing interval remains missing unless partial output was requested.
- “Monthly GHI total for 2016 and 2017” returns 24 year-month rows with
  `Wh/m2` totals, not averages of hourly irradiance.
- “Average January temperature over those years” returns the January point
  from a month-of-year profile; if per-year January values are also plausible,
  the agent clarifies which grouping the user wants.
- A complete 3×4 coordinate grid returns spatial axes and a 3×4 value
  matrix. Twelve irregular sites return twelve points, no fabricated grid.
- A published TMY supports a reference-year monthly view but is rejected as
  a real 2012–2018 trend source.
- Pure follow-ups and data views make no `weather_plan`/`weather_submit`
  call. A compound status-plus-new-retrieval turn executes each action once
  and preserves the correct plan hash.
- MCP tool listing has no future-generation tools; compatibility and retry
  attempts cannot create future jobs. Prior future artifacts remain readable.

## Optional user-prompt corpus request

If a separate test agent is used to broaden utterance coverage, give it this
prompt without any credentials or project data:

> Act as 30 different building-energy and climate-data users. Write 60 short,
> realistic follow-up messages after an EPW retrieval: artifact download to
> user disk, ambiguous year/location selection, annual and monthly summaries,
> distributions, spatial comparisons, uploaded EPWs, missing data, TMY versus
> actual years, and combined requests. Vary phrasing and include incomplete or
> contradictory requests. Do not provide answers, implementation advice or
> future-weather requests. Label each message with its intended action and
> any ambiguity a safe assistant should clarify.

**Boundary:** This phase produces structured data and factual responses.
Chart rendering and any future-weather re-enablement require separate review.
