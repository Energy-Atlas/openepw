# v0.1 limitations and deferred follow-ups

## MCP Stage 2 availability boundaries

Availability assessments use the explicitly imported, dated local Stage 1
snapshot. They retain source evidence, accepted review decisions and three-valued
eligibility. A `supported` option means that catalog evidence does not rule out a
retrieval attempt; it does not establish all hours, valid variables, EPW quality or
simulation readiness. Unknown coordinates, stale sources, sparse inventory gaps,
unverified future periods and access restrictions are reported rather than filled.
Refresh is opt-in and source-specific; aged evidence loses authority to exclude.
Unsupported or partial raw metadata formats retain the last good generation and
report a refresh failure. With no local inventory, only bundled Open-Meteo/CDS
contracts screen documented capabilities. A query emits at most 50 ranked
options per occurrence and reports omitted alternatives. Filter by product/model
for more detail. Original raw inventories remain local and are not bundled.

Stage 3a supplies batch fetch-equivalence, per-row outcomes and explicit local
export. These still depend on successful provider retrieval and QC; an eligible
catalog option may yield a failed or QC-limited row. The local ZIP does not grant
redistribution rights for source files. Stage 3b baseline choice and future
execution workflow are pending. Stage 4 will settle
the final MCP tool names and conversation shape. The existing `weather_discover`
tool carries shared assessment facts when a catalog is loaded.

## Scientific meaning

QC distinguishes structural failures from physical warnings. Outputs always carry
`simulation_ready=false`: neither format validity nor provider availability proves
simulation suitability. EnergyPlus execution is not part of ordinary tests.

Meteorology may be instantaneous at interval ends while solar is interval energy.
EPWs use fixed standard time; callers must supply the offset they intend (UTC is
the default). Area sampling can explicitly use a longitude-derived nominal offset;
this is not a legal time-zone lookup and can differ from local civil time.
Historical retrieval currently requires output offsets aligned to
whole provider hours; use UTC for fractional-hour zones pending explicit temporal
interpolation support. No DST shifts, gap interpolation or implicit hybrid fill.
Actual-year requests preserve leap days unless `skip_feb_29=True` is explicitly
set. That compatibility option is available only with `years`, removes February 29
in local standard time, and does not make other 8,760-row truncations valid.

Monthly CMIP6 morphing preserves the baseline's sequence and most untransformed
fields. It does not predict new hourly extremes. RH clipping is reported, dew point
is recomputed when humidity/temperature change, and longwave needs opaque sky.
Unchanged and derived variables have provenance. The same solar ratio scales all
three components, preserving baseline proportions rather than solving new clouds.

Hourly WRF uses one driving model and sparse PUMA centroids, not a global SSP
product. Nearest-site lookup has a 150 km guard and always reports distance. Source
EPWs use a 365-day calendar even for leap-labeled years; normalized files explicitly
mark this and preserve original year labels. No real leap observations are removed.
Typical is a whole-year medoid, not standardized TMY generation. Shock is a three-day
statistic; persistence uses paired 1995–2004 calendar-day thresholds. Ensemble means
ten temporal years. The late-century RCP4.5 source warning is retained.

## Provider boundaries

- Open-Meteo free hosting is noncommercial. Native source cells are resolved at
  fetch time, so plans cannot promise inferred grid-cell reuse beforehand.
- PVGIS is a published TMY product; selected month years are not availability for
  actual-year weather. Native location/time basis remains authoritative.
- OneBuilding uses explicit product paths or a country catalog plus a location
  name. Automatic worldwide nearest-site discovery is not included. Redistribution
  remains unverified; no source weather is committed as a fixture.
- NOAA ISD supports the surviving historical endpoint, not its GHCNh successor.
  Inventory dates are not completeness guarantees. Missing solar and station
  pressure remain missing. A hybrid can explicitly supply other variables.
- Discovery of a station is not proof that every requested hour is complete. A
  dataset selection resolves the locally ranked station independently at each
  point; failed/unsupported point-dataset outputs are reported rather than silently
  filled from other stations.
- NSRDB supports aggregated v4 hourly historical CSV and published TMY/TDY/TGY v4
  products. Other v4 footprints and subhourly API products are not claimed. Nonzero
  output offsets can require neighboring annual downloads; unavailable edge years
  produce an explicit error rather than a truncated year.
- Direct CDS requests are monthly, bounded to ten minutes of polling each. A slow
  queue can fail a job without blocking other providers. GHI is available; direct
  and diffuse radiation remain missing. Copernicus dataset terms must be accepted.

## Operational boundaries

Use one worker/server process per data root. SQLite item records let a restarted
server reuse completed outputs and verify their checksums. Cancellation is
cooperative at item boundaries; it cannot interrupt every provider SDK/network
call. Queued CDS work can outlive the client polling limit. There is no distributed
scheduler, object-storage integration or automatic artifact retention cleanup.
Retry creates a linked job for only missing output identities; the original job and
successful artifacts remain unchanged. Future ensemble retries may recompute the
coherent source profiles, but emit only missing members.

Map coverage polygons are not evidence of actual temporal or station completeness.
The UI branch's broad coverage overlays are pending replacement with documented,
provider-specific footprints; they are not promoted to the canonical data model.

Remote REST requires a bearer token and bounded requests. MCP HTTP is loopback-only;
use stdio or authenticated REST for remote deployments. Baseline uploads accept
EPW only; custom signal artifacts are registered through Python, not arbitrary
server filesystem paths. Optional SDKs may emit deprecation warnings listed in
acceptance; these do not replace test failures.

Raw data and downloaded climate subsets are local caches, not licensed public
redistribution. Cache reuse is checksummed; provider versioned URLs can still change
upstream before first retrieval. Plans are reproducible instructions, not a promise
that an uncached external source can never change.
