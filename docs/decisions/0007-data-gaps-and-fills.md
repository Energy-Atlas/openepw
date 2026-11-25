# ADR 0007 — Data gaps: warn, then fill from a second source

Date: 2026-11-22. Status: owner approved the plan and its recommendations on 2026-11-22;
implemented on `feature/data-gaps-and-fills` (not yet merged).

## Context

The owner tested NOAA ISD at Paya Lebar, Singapore, and got an EPW with no GHI, DNI or DHI.
The raw ISD records for Paya Lebar and Changi (checked 2026-11-21, 1–3 June 2023) carry no
solar fields at all. The EPW was right to mark them missing. The problem was that nobody was
told before the run:

- a candidate's `missing_fields` were computed but never shown;
- the catalog path only added a generic coverage warning;
- explicit hybrids (`HybridPolicy`) could not be used from the guided chat. They could not be
  combined with dataset selections, matched sources by provider name only, and needed every
  variable assigned by hand.

## Decision

1. **Find gaps when planning.** For each place, chosen source and variable group (solar:
   GHI+DNI+DHI; pressure; humidity; temperature; wind), the plan records which requested
   variables the source lacks (`WeatherPlan.gaps`, `planning/gaps.py`).
   - Each gap carries the ways to cover it, the recommended one marked.
   - An uncovered gap adds a `DATA_GAP` issue (warning), which reaches batch rows and job
     outputs.
   - Output identities and plan hashes do not change when nothing is lacking or filled.
2. **The person decides on a data-gaps form** (form kind `data_gaps`, gate `fill_gaps`).
   - It sits after planning and before the plan review, in both modes.
   - In agent mode `review_plan` shows it first, under the same question, so the model cannot
     skip it or choose a fill.
   - Choices can also be typed ("fill solar from Open-Meteo", "leave pressure missing", "ok").
   - The plan review lists each gap's resolution and offers "Change data gaps".
   - Run is refused while a gap is undecided.
3. **Fill rules ride on the request** (`WeatherRequest.fills`, `VariableFill`): `source`,
   `station_reports` or `leave_missing`, optionally limited to one chosen source. For each
   output, the first rule possible there applies. Rules work alongside dataset selections;
   explicit hybrids stay a separate, exclusive mode.
4. **Whole variables only** (owner decision 1).
   - A source fill replaces every requested variable of the group with another source's values
     for exactly the same UTC hours. GHI, DNI and DHI always come from one source.
   - Values are not adjusted toward the station (no bias correction).
   - Lineage marks each filled variable `filled`, names the source and records the distance
     between the two sources' locations; the dataset gets a `VARIABLE_FILLED` info issue.
   - A filling source that fails leaves its group missing with `FILL_FAILED`; the output is
     still written.
5. **Station pressure from the station's own reports** (owner decision 2, extended).
   - The owner approved "work it out from NOAA's sea-level pressure using the station
     elevation". Paya Lebar reports no sea-level pressure, only the altimeter setting, so the
     NOAA adapter takes each report's station pressure in this order:
     1. measured station pressure (ISD MA1);
     2. the altimeter setting, through the ICAO standard-atmosphere definition (exact apart
        from rounding);
     3. sea-level pressure, through the hypsometric equation, for stations up to 500 m.
   - Lineage counts the hours from each route and marks the variable derived.
   - It needs a NOAA station with a known elevation; elsewhere the next rule (for example
     Open-Meteo surface pressure) applies.
6. **Hours missing inside a variable are reported** (owner decision 3a).
   - After a job the host lists the missing hours per variable in each file (`DATA_GAPS_AFTER`),
     and the hours interpolated (item 8).
   - Where a group is wholly missing and the plan offered a source for it, What next offers to
     fill it and plan again. Where short gaps were left missing, it offers to interpolate them.
7. **Fill sources**: Open-Meteo ERA5 (all variables, no key), Open-Meteo ERA5-Land
   (temperature, humidity, pressure), and Copernicus CDS ERA5/ERA5-Land (no DNI or DHI; offered
   only when the server has a CDS key). NSRDB is not a fill source yet.
8. **Short gaps inside station records are interpolated by choice** (owner decision 3b, built
   2026-11-25; `planning/short_gaps.py`).
   - Plans for station observations (NOAA ISD) get one more gap row, `short_gaps`, whatever
     else is missing: interpolate gaps of up to 3 hours (recommended) or leave them missing. It
     is a `VariableFill` with group `short_gaps` and method `interpolate` or `leave_missing`.
     Reanalysis and satellite grids get no such row; they do not routinely miss hours.
   - Whether a record misses hours is known only after retrieval, so the row adds no `DATA_GAP`
     warning to the plan.
   - A short gap is at most 3 consecutive missing hours with a value on both sides, exactly that
     many hours apart. Gaps at the start or end and longer gaps stay missing. Solar is never
     interpolated.
   - Dry bulb, dew point, station pressure and wind speed: linear in time. Relative humidity:
     worked out again from the interpolated dry bulb and dew point (Magnus) where the source
     derived it that way, else linear. Wind direction: along the shorter arc, only where the
     wind blows at both ends and through the gap (a calm hour has no direction).
   - It runs after whole-variable fills and before leap-day removal and QC. The retrieval is
     the same (the fetch task's cache key does not change); the output identity includes the
     rule.
   - Records: lineage notes the hours and gaps per variable; `metadata.interpolated` lists each
     gap's UTC start and length; the manifest and job outputs carry `interpolated_hours`; the
     dataset gets a `GAPS_INTERPOLATED` info issue. The EPW's per-hour source flags are left as
     they were, because the flag codes for interpolated values were not confirmed against the
     EPW specification.

## Consequences

- An EPW built this way is still `simulation_ready: false`. QC still flags missing values;
  manifests record `missing_hours`, `gaps` and `fills` per output.
- A station-plus-reanalysis file mixes a point measurement with a grid cell (25 km for ERA5).
  The distance is recorded but not corrected.
- Plans with fills fetch one more source per place and period. Fill tasks deduplicate like any
  other fetch.
- `HybridPolicy` remains for explicit per-variable assignment by API clients.
