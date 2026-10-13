# Product availability and real time zones: findings and proposal

Status: proposal, 2026-10-12. Not approved for implementation. The owner's answers to §5 decide
what is built. It extends, and does not replace, the evidence ladder in
[the NSRDB geospatial design](2026-09-24-nsrdb-geospatial-availability-design.md) and ADR 0003.

## 1. What happened

On Render staging, a chat for Singapore (1.2897, 103.8501), year 2018, offered
"NSRDB actual year · GOES v4" as *not verified; checked when planning*. Planning correctly
found no candidate (`DATASET_UNAVAILABLE`). The review still offered Run, which failed with
"Weather plan has no executable outputs". The Run part is fixed on `fix/chat-unrunnable-plan`
(a plan with no outputs is blocked and leads back to the product choice). This document is
about the two causes behind it:

- the product list cannot tell which products exist at a place;
- standard time is estimated from longitude, which made Singapore UTC+07:00. Its civil
  standard time is UTC+08:00.

## 2. Availability findings

Every result below comes from the local catalog (built 2026-09-23) and `point_availability`
for 12 places. The exception is the probe log in §6.

| Place | ERA5 Open-Meteo | ERA5 CDS | ERA5-Land (both) | NSRDB actual | NOAA ISD | NSRDB TMY | PVGIS TMY | OneBuilding |
|---|---|---|---|---|---|---|---|---|
| Ithaca, Singapore, Mumbai, Nairobi, Sydney, São Paulo, London, Reykjavik, Honolulu, Tokyo, Anchorage | listed | ? | ? | ? | ? | ? | ? | ? |
| Mid-Pacific (0, −150) | listed | ? | ? | ? | none | ? | ? | ? |

The list carries almost no information. Only ERA5 through Open-Meteo is ever "listed", and
it is listed everywhere. Every other product is "not verified" everywhere, including NSRDB at
Ithaca, which is one of its two probe points.

**F1. Evidence ages into "unknown" after a week.** `freshness.cadence` gives each evidence
source a check cadence: 1 day for CDS, 30 days for the Open-Meteo documentation and 7 days for
everything else. After that, every option that uses the source gains `STALE_SOURCE_EVIDENCE`,
and an option with an unknown is never "supported". The catalog was built on 2026-09-23, so
since about 2026-09-30 every station position, published-file list and probe has read
"unknown". Render installs the same pinned package and never refreshes it, so the same is
true there. The cadence was written as "local evidence check cadences, not upstream
completeness guarantees". In effect it now erases durable facts, such as where a station is,
together with time-sensitive ones, such as the latest year.

**F2. NSRDB and PVGIS evidence is point-only.**
- NSRDB actual-year and TMY entries are targeted probes at Ithaca and Phoenix (NSRDB).
  PVGIS has one probe, in London.
- Away from those points the decision is `TARGETED_PROBE_ONLY`, which means unknown. That
  follows the evidence ladder. The trouble is that "unknown" is all the list can say about
  NSRDB anywhere, including Singapore, which is far outside GOES coverage.
- A reviewed NSRDB coverage mask exists only for the published `tdy-2023` file. By design it
  is display-only: the ladder says a mask is not positive eligibility, and outside it is
  excluded only when the grid is proven exhaustive for that exact product, year and version.

**F3. The authoritative point check runs too late.**
- NSRDB's `nsrdb_data_query` returns, for one coordinate, every NSRDB dataset and its years.
  The provider already calls it at planning time.
- It is one small request, and it is the ladder's top level, "exact point catalog".
- For Singapore it lists `himawari` (2016–2020), `himawari7` (2011–2015), `himawari-tmy` and
  `msg-iodc` (2017–2019), and no GOES dataset (§6).
- So the right answer was one request away when the list was built. Users in Asia and Africa
  would also benefit from NSRDB Himawari and Meteosat products, which the app does not offer
  today.

**F4. OneBuilding has no distance limit, and half its inventory is missing.**
- The catalog has 21,653 OneBuilding sites from four regions: the USA (WMO region 4), the
  Southwest Pacific (5), Europe (6) and the US normals and TMY3 lists.
- It has no Africa (1), Asia (2) or South America (3), and none of region 4 outside the USA.
- NOAA ISD and OEDI exclude stations beyond 100 km and 150 km. OneBuilding has no such
  rule, so Singapore is offered the nearest listed station, 2,666 km away.

**F5. Other gaps.**
- *CDS ERA5:* the documented operating interval is not report coverage, so it is unknown.
- *ERA5-Land:* there is no land–sea mask, so it is unknown.
- *NOAA ISD:* years missing from the dated inventory are unknown.

These are honest unknowns. Their fixes (a land mask, and treating CDS like Open-Meteo ERA5
when both document the same reanalysis) are smaller and can follow.

## 3. Availability proposal

**A1. Run point checks while the product list is built.**
- The list is built for up to *N* locations; default N = 5, a single place being the common
  case.
- For each, run the provider's cheap point check before showing the list. For NSRDB this is
  `nsrdb_data_query`. Open-Meteo and PVGIS need none.
- Record each answer as exact-point evidence for that coordinate, product and year:
  - **listed** when the product and years are returned;
  - **not available here** when the query succeeds and does not list the product. This is a
    point exclusion, which the ladder allows.
  - **unknown** when the query fails, the key is missing, or the request has more than N
    locations. Those still say "checked when planning".
- Answers are cached per rounded coordinate for a day, so the planner reuses them.
- Cost: one NLR request per location shown. Product lists for batches keep today's
  behaviour.

**A2. Separate durable facts from time-sensitive ones.** An aged source no longer changes
"listed" to "unknown" for:
- station and site positions;
- published-file lists;
- documented footprints;
- dataset periods that end before the newest year.

The list shows "last checked YYYY-MM-DD" instead. Aged evidence still means unknown for:
- years at or after the documented or dated end;
- a moving end;
- CDS queue and access state.

This changes the meaning of `STALE_SOURCE_EVIDENCE`, so it would be recorded in ADR 0003.
The alternative is a scheduled catalog refresh on Render (§5 Q2).

**A3. Distance limit for published-file stations.** OneBuilding stations beyond 100 km are
excluded (`BEYOND_PROVIDER_SEARCH_RADIUS`), the same rule as NOAA ISD. The limit is a routine
default and would be documented in limitations.

**A4. Complete the OneBuilding inventory.**
- Import the published TMYx location workbooks for regions 1, 2, 3, the rest of 4, and 7,
  one bounded download each, the same way as the existing ones.
- Per ADR 0003, each download is stated beforehand: its source, size cap and stopping
  condition.

**A5. More NSRDB satellites (later).**
- Offer NSRDB Himawari (Asia-Pacific) and MSG (Europe, Africa, Indian Ocean) products where
  the point query lists them.
- The provider currently accepts only the GOES names.
- This needs adapter checks for each dataset: variables, interval, years and terms. It is a
  separate change.

**A6. Show "not checked here" products apart.** Products that are still unknown after A1
appear under their own heading, below the listed ones, with "checked when planning". The
blocked review from `fix/chat-unrunnable-plan` remains the safety net.

## 4. Time zone proposal

Today every location starts at UTC+0, and chat, the agent and MCP replace a missing offset
with `round(lon / 15)` hours (`models.nominal_offset_minutes`). Known wrong results include:
- Singapore: +7 instead of +8;
- western Nebraska: −7 instead of −6;
- China: one zone across 60° of longitude;
- India: +5 instead of +5:30.

Both name sources already know the zone and drop it: the Open-Meteo geocoder's `timezone`
(`service.py:283-299`) and GeoNames column 17 (`places/geonames.py:126`).

**T1. Find the IANA zone for every location.**
1. Use the zone the geocoder or GeoNames row gives, when there is one.
2. Otherwise look it up from the coordinate with `tzfpy`, offline:
   - MIT licence; boundary data from timezone-boundary-builder (ODbL 1.0, attribution
     recorded in third-party notices);
   - one ~3 MB wheel for Linux and Windows, with no other dependencies;
   - borders accurate to about 111 m.
3. At sea it returns nautical `Etc/GMT±N` zones, which are the longitude rule. Those are
   marked as nautical, not civil.

`timezonefinder` would also work, but it needs 33 MB of data plus h3 and cffi.

**T2. Standard offset from the zone and the year.**
- Use `zoneinfo` with the `tzdata` package (Apache 2.0), which is added explicitly because
  the Docker image has no system zone files.
- Standard offset = `utcoffset − dst` at a reference instant in the requested year, so
  daylight saving never enters EPW time.
- The offset is the one in force for that year: Singapore was +7:30 before 1982.
- When a zone's standard offset changes within a requested year, or differs between
  requested years, the review lists the years and the offsets, and asks the person.
- Typical-year products keep the offset of the published file, as now (ADR 0002).

**T3. Review and provenance.**
- The location review shows each point's zone and offset, for example "Asia/Singapore ·
  UTC+08:00 (standard time; no daylight saving)".
- The source is marked as geocoder, GeoNames, boundary lookup or nautical.
- A typed offset still wins, and a typed reply such as "use UTC+7" corrects it.
- The manifest records the zone, the offset source and the tzdata and boundary-data
  versions.
- The longitude estimate stays only as the fallback for areas, until those are sampled
  point by point.

**T4. Where it applies.**
- `WeatherService.review_locations`, used by chat, the agent and MCP, and place-set
  previews.
- A new opt-in `standard_offset: "zone"` on `SamplingSpec` for areas.
- Direct Python, REST and CLI callers keep the UTC default, so plan hashes for existing
  requests do not change.

**T5. Fractional offsets.** These include India (+5:30), Nepal (+5:45), Newfoundland
(−3:30), South Australia (+9:30) and Iran (+3:30). Actual-year output for them is refused
today (`UNSUPPORTED_TIMEZONE`), because hourly provider data sits on whole UTC hours. A real
lookup would turn today's silently wrong +5 for India into that refusal. Options are in §5 Q1.

**T6. Tests that change.**
- `test_spatial`, `test_location_review`, `test_mcp_review_offers` and
  `test_chat_sessions`.
- `test_chat_places`, which pins Nebraska at −7, a known wrong value.
- `test_service`'s chat EPW header.
- The agent's guided and model-mode Ithaca cases.
- The eval grader `OFFSET_NOT_ESTIMATED` and task S3, which become checks of the zone
  source.

## 5. Decisions for the owner

**Q1. Fractional standard offsets for actual-year output.** Options:
- *(a)* Use the nearest whole hour, with a note that it differs from civil time
  (recommended).
  - EnergyPlus computes solar position from the EPW time zone and longitude, so the file is
    internally consistent.
  - Only civil-clock schedules are off by the fraction. Today's estimate already does this,
    silently.
- *(b)* Interpolate to the half or quarter hour. This is a new temporal transform: radiation
  is hour-ending integrated, and the transform needs its own method, tests and labelling.
- *(c)* Keep refusing, and offer UTC or the nearest hour as explicit choices.

**Q2. Stale evidence.** Options:
- A2's split, where durable facts keep their status with a "last checked" date
  (recommended);
- a scheduled catalog refresh on Render;
- both.

**Q3. Point checks at list time.** Options:
- A1 with N = 5 (recommended);
- a different N;
- planning-time checks only, as now.

**Q4. Scope and order.** Options:
- Time zones (T1–T4) first, then A1–A3, then A4 and A6. A5 is a separate later proposal
  (recommended).
- A different order.

## 6. Probe log (ADR 0003)

| Date (UTC) | Request | Purpose and bound | Result |
|---|---|---|---|
| 2026-10-12 | `nsrdb_data_query` at Singapore (1.2897, 103.8501) | Does any NSRDB dataset cover the failing point? One request, configured key, no retries | `himawari` 2016–2020, `himawari7` 2011–2015, `himawari-tmy`, `msg-iodc` 2017–2019; no GOES |
| 2026-10-12 | `nsrdb_data_query` at Ithaca (42.44, −76.5) | Control at a Stage 1 probe point. One request | GOES aggregated v4 1998–2025, GOES CONUS and full-disc v4 2018–2025, GOES TMY v4 |

Stopping condition met: the Singapore failure is explained, and the query is confirmed as a
per-point discriminator. No grid sweep or further probes were made.
