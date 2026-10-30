# v0.1 limitations and deferred follow-ups

## MCP Stage 2 availability boundaries

Availability assessments use the explicitly imported, dated local Stage 1
snapshot. They retain source evidence, accepted review decisions and three-valued
eligibility. A `supported` option means that catalog evidence does not rule out a
retrieval attempt; it does not establish all hours, valid variables, EPW quality or
simulation readiness. Unknown coordinates, stale sources, sparse inventory gaps,
unverified future periods and access restrictions are reported rather than filled.
Refresh is opt-in and source-specific; aged evidence loses authority to exclude.
Aged evidence (past its check cadence: 1 day for CDS, 30 for the Open-Meteo
documentation, 7 otherwise) keeps durable facts listed, with a `SOURCE_CHECK_DUE`
reason: site positions, published-file lists and closed dated years. It no longer
vouches for the newest listed year, an open-ended period's last two years, CDS or
future-window directories, which become unknown.
Unsupported or partial raw metadata formats retain the last good generation and
report a refresh failure. With no local inventory, only bundled Open-Meteo/CDS
contracts screen documented capabilities. A query emits at most 50 ranked
options per occurrence and reports omitted alternatives. Filter by product/model
for more detail. Original raw inventories remain local and are not bundled.

Stage 3a supplies batch fetch-equivalence, per-row outcomes and explicit local
export. These still depend on successful provider retrieval and QC; an eligible
catalog option may yield a failed or QC-limited row. The local ZIP does not grant
redistribution rights for source files. Stage 3b accepts a registered user EPW or
fetched weather artifact ID as a future baseline only after annual and essential
variable QC. Fetched provenance requires verified companion manifest/QC artifacts.
Stage 4 exposes bounded structured tools and verified artifact resources through
local MCP. Ordinary results cap at 160 KB; plan/job pages show at most 50 rows,
uploads at most 5 MB and resource reads at most 10 MB. Hosts may impose smaller
limits. Local path registration requires an explicit allowed root. The v0.1
weather inline tools remain compatibility aliases; new clients submit stored
hashes. Future-weather MCP planning, submission and retry are temporarily
suspended with `FEATURE_SUSPENDED`; prior future records remain readable.
Generic EPW upload and allowed-root registration remain available. The Python
and REST future services are outside this MCP suspension.
Visualization currently prepares hourly time series, annual and monthly
series, histograms and spatial views. Other families appear as `planned` in
capabilities and return `VISUALIZATION_UNSUPPORTED`. Result pages are JSON,
not plotted graphics. The standard CLI accepts an explicit JSON request.
`openepw-chat` routes simple hourly, annual, monthly, histogram and spatial
requests using the current completed EPWs; source filtering, advanced options
and multi-action analytical turns still require explicit MCP or CLI requests.
Uploaded EPWs retain unverified year/provider identity, and multi-artifact
annual trends require verified actual-year sources. Missing intervals yield
null complete-period aggregates unless observed-only partials are requested.
The tested client is the MCP Python SDK stdio client on Windows. Remote MCP
authentication and other host behavior remain untested.
The Stage 5 reference agent uses a bounded model only to parse intent; its
template explanations and fixed rubric do not establish real-user
comprehension. Host/model availability and natural-language interpretation
vary. Local records omit prompts and raw weather; the model API receives
sanitized task text when explicitly used. The single-request command has no
LangSmith tracing. The console sends bounded turn, intent and tool traces to
LangSmith when a key is present; natural-language requests are sanitized before
transmission, and a terminal option disables tracing. This hosted record has
LangSmith's retention and access controls, separate from local run records.
The interactive console carries its request draft, geocoder choices and artifact
references only within its current process, so a restarted chat needs a new
request or explicit artifact/job IDs. Ambiguous natural-language choices may
still need clarification; a catalog assessment is read-only and must not be
mistaken for actual-year completeness. Its weather intent uses the UTC
default; it does not expose an explicit fixed standard-time offset. Automatic
submission can invoke live providers, but catalog eligibility remains only
permission to try retrieval and emitted EPWs still require QC review.
The Stage 6 pilot used a scripted agent and MCP Python SDK stdio client on
Windows. It did not test a human participant, another desktop MCP host,
Linux/macOS behavior or EnergyPlus consumption. A model initially classified
an explicitly named TMYx batch as generic published weather and capitalized
the provider ID; refined intent guidance and provider-ID normalization passed
a bounded rerun. No arbitrary-prompt reliability claim follows from that run.

## Scientific meaning

QC distinguishes structural failures from physical warnings. Outputs always carry
`simulation_ready=false`: neither format validity nor provider availability proves
simulation suitability. EnergyPlus execution is not part of ordinary tests.

Meteorology may be instantaneous at interval ends while solar is interval energy.
EPWs use fixed standard time. Direct Python, REST, MCP and CLI callers must supply
the offset they intend (UTC is the default). The location review used by browser
chat, the agent and MCP (`weather_locations_review`) gives points without one the
standard offset of their time zone, found offline from the coordinates (tzfpy with
timezone-boundary-builder boundaries, accurate to about 111 m near borders; IANA rules
from tzdata), and does the same for each point of a sampled area. Standard time is the
smallest offset in force during the year, so no daylight saving enters EPW time. At sea
the nautical zone applies (longitude / 15); a zone missing from the installed tz rules
falls back to longitude, and the review says which was used. Fractional standard
offsets (India +5:30, Nepal +5:45, Newfoundland -3:30, central Australia +9:30) are
rounded to the nearer whole hour, a tie going to the hour nearer mean solar time, so two
places in one zone can differ by an hour (Mumbai +5, Kolkata +6, both +5:30); the review names the
civil offset. The owner kept this rule on 2026-10-27 (Q7) over one offset per zone; EPW data stay
hourly, so no sub-hour shift is planned. The review
uses the zone's current standard time; a plan warns when a requested year used another
(Singapore before 1982). Explicit offsets are preserved. Existing files retain the offset used when they were generated;
download a new EPW after changing it. Older saved browser chats require the
location to be re-entered and reviewed before an actual-year plan can run.
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
- PVGIS TMY radiation is SARAH3 or ERA5 by location, and the run records which.
  - The catalog's PVGIS domain mask leaves coasts, lakes and small islands unknown. This is
    17% of published station positions, including Cape Town and Singapore.
  - Points refused at sea can lie inside JRC's documented 25 km coastal zone.
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

## Agent chat guardrails

The guards in the agent chat reduce, but do not remove, misuse. The off-topic clamp and the
model's own scope decisions can misjudge borderline weather-science questions; knowledge answers
are general information, not checked against openepw data. Ending a session does not stop the
same person from starting a new one until P4 adds per-user and per-IP limits and spend caps.
Moderation sends message text to OpenAI's moderation endpoint (also in guided mode) when a
profile enables it. Map-input values and choice ids in form answers are not moderated. Host
small-talk replies match whole messages only; other conversation is left to the model, which
may still misjudge it. The legacy `/v1/chat/*` and
`openepw-chat` paths have none of these guards.

## Map-first local browser client

`feature/chat-ui` adds an optional local browser client. Its MapLibre scene uses
public OpenFreeMap and Mapterhorn tiles, so a tile outage can leave only chat and
coordinate entry. Source scope outlines show documented evidence extents, not
verified point eligibility or weather completeness. Source assessment remains
read-only until the user runs a reviewed plan. Sessions and artifacts remain in
the local data root; the browser retains only a session ID.

The initial availability display draws only product footprints explicitly
stored in the active catalog. The current local catalog has mappable CDS
footprints in 0–360 longitude and many products with no mapped scope. The map
normalizes those rectangles for display and counts unmapped source datasets.
Faint scope color does not imply a source is usable at every point or year.

Decorative building heights are derived from public vector map fields or a
fallback. Projected building and roof shadows and sampled DEM relief occlusion
are approximate, bounded visual context. They omit vertical facade occlusion,
distant ridges and fine terrain detail; a live browser image is not a calibrated
shadow validation. The map, terrain, sunlight, and shadows never change EPW,
QC, availability, or energy-model inputs. See [decision 0004](decisions/0004-map-first-chat-scene.md).

Product choices and their map tags come from the offline Stage 1 catalog
assessment only. A product "not verified in the catalog" (outlined tag with ?)
is checked live when planning, and is listed after the products checked here under
"Not checked here". NSRDB GOES products are gated by the reviewed coverage map (the
NSRDB map layer, a 0.25 degree summary of the published `tdy-2023` file's grid
sites, used for actual-year and typical-year GOES products alike): outside it they
are not offered; inside it the probed years and file names apply; next to its edge
they stay unverified. Without an installed map they exist only at the saved probe
points. Inside a mask, each adapted dataset's years and files are the list that NLR's dataset
page documents and every probe repeats (15 probes, ten at grid edges). NLR's pages can lag the
data query, as the GOES TMY page did for the -2025 files. The years are not checked at every
grid site. OneBuilding and NOAA ISD stations beyond 100 km are not offered. OneBuilding
files come from every TMYx regional workbook (all WMO regions); national typical-year
families (CWEC, ISHRAE and others) are not catalogued. NSRDB Himawari-7 and Himawari TMY,
Meteosat (with its typical years) and Meteosat IODC are gated by their own grids' masks,
like GOES; NSRDB Himawari-8 (2016-2020) is not downloaded
because its hourly values are centred on the hour. ERA5-Land is gated by the points where
ERA5-Land has a value (one CDS field), which includes lakes. Points next to the mask's edge stay
unverified, and open sea is not offered. Before
years are given, actual-year availability is shown for the last complete
year. The station on the map is the catalog's best-ranked station for that
product; planning re-ranks with the chosen years and may pick another. Tags are
drawn for the first 25 locations, and at continental zoom the tag stacks of
nearby locations can overlap. OneBuilding file families are recognised from the
published file name. A request mixing actual-year and typical-year products runs
one job per kind, and Copernicus CDS products run as a job of their own because
each CDS request (one per month, polled up to 10 minutes) waits in Copernicus's
queue; several years at several places can take hours. Jobs run in plan order,
one output at a time, on two workers. Retry reruns only the jobs with failed
outputs. Relative year
phrases are expanded by the optional model with today's date; written years
always win, and without the model only written years and decades are read.

The initial client is local and single-process. Chat turns use a bounded,
durable SQLite FIFO with withdrawable waiting entries; other session actions
still use revision conflicts. The model-assisted parser depends on an optional
local credential and falls back to a narrower offline parser. A single hourly
view up to 10,000 rows loads all pages for plotting; larger or other paged views
state how many rows are plotted and offer `Load more`. No future-weather UI
flow is exposed.

## Place lists and descriptive sets

Place previews take the geocoder's top match for each name without asking;
ambiguous rows are flagged and must be corrected by text. The deterministic list
splitter keeps US state and a small set of country qualifiers with their place;
other phrasing relies on the model parser. Descriptive place sets come from
GeoNames city dumps (minimum population 1,000; capitals are first-level seats).
GeoNames populations are its own values, some city sections (such as New York
boroughs) appear as separate places, and continent-wide sets are not supported.

## Hosted deployment

The Render deployment ([guide](deploy/render.md)) is a single instance behind one shared
site password: there are no user accounts, and everyone who signs in uses the owner's
NLR, Copernicus and OpenAI credentials and shares chat storage. The Stage 1 catalog is
built from a pinned, checksummed version of the public catalog package in
Energy-Atlas/open-data, so it is only as fresh as that version. Deploys restart running jobs, which resume but resend queued Copernicus requests.
The package holds catalog metadata only; OneBuilding's redistribution terms are unclear and it is published by owner decision (see the package's data card).
