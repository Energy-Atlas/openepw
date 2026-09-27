# Place lists, coordinate lists and descriptive place sets

**Status:** Owner-requested on 2026-09-27 after the map-first chat UI review
("that should be all for the chat ui"). Implemented on `feature/mcp`; the chat
UI adopts it later by merging this branch. Owner decisions: enumerate
descriptive sets from **GeoNames** city dumps; keep the existing **1,000-point**
request cap for previews.

## Problems seen in the chat UI

- Several named places in one message went through one-at-a-time geocoder
  confirmation, which does not scale past a handful of sites.
- Typed coordinates and coordinate lists were only handled by loose phrase
  parsing.
- A set description such as "all cities in America" had no defined meaning,
  source or size, and was treated like a single place name.

## Contract

1. **Place list, no confirmation.** A list of names and/or coordinates is
   resolved in one call. Each name takes the geocoder's top-ranked match; rows
   with several matches carry `ambiguous: true` and their candidate count, so
   the uncertainty stays visible (production MCP plan, Stage 4). The result is
   a numbered preview (rows, GeoJSON points and a ready-to-plan `locations`
   list with a digest). The user corrects it by text only ("replace 3 with
   Portland, Oregon", "remove 2", "add Reno"); there is no per-row
   confirmation step. Unresolved rows are reported, never dropped silently.
2. **Coordinate geometry, points only.** "lat, lon" and lists of them
   (separated by `;`, newlines or `), (`) parse into points in the stated
   order, latitude first. Out-of-range values fail; nothing is swapped or
   repaired. Boxes, polygons and other geometry words are rejected with a
   clear issue.
3. **Descriptive sets ask first.** Phrases such as "all/every <cities|towns|
   capitals> in <region>" return `needs_clarification` with the unresolved
   fields: region (country, or country + first-level division; "America" is
   ambiguous between the United States and the Americas), definition
   (minimum population, or first-level capitals) and limit (≤ 1,000, ordered
   by population). Only a fully specified `PlaceSetQuery` enumerates places,
   and it returns the same preview shape with GeoNames attribution.

## Data source

GeoNames `cities15000` / `cities5000` / `cities1000` dumps, `admin1CodesASCII`
and `countryInfo` (CC BY 4.0, "provided as is"). The smallest file that covers
the requested minimum population is downloaded once into
`<data_root>/places/geonames/` with its SHA-256, size and retrieval time.
Minimum populations below 1,000 are unsupported. GeoNames population is the
dump's value, not a census figure; previews say so and carry the attribution.

## Units

| Unit | Files | Behaviour |
| --- | --- | --- |
| Place parsing | `src/openepw/planning/places.py` | Classify text (coordinates, list, single, descriptive); parse coordinates; split lists; detect set descriptions and missing fields; apply text edits to a preview |
| GeoNames store | `src/openepw/places/geonames.py` | Bounded download/cache with checksum, parsing, region resolution, population-ordered query |
| Service | `WeatherService.interpret_places`, `preview_places`, `place_set` | Canonical behaviour shared by MCP, REST and CLI |
| MCP | `weather_places_interpret`, `weather_places_preview`, `weather_place_set` | Thin wrappers with bounded outputs |
| Harness | `harness/graph_chat.py` think node | Route location text to preview, clarification or the existing single-place choice; apply text fixes to the current preview |

## Tests

Offline and deterministic: coordinate formats and failures, list splitting,
set detection and clarification fields, preview ambiguity/unresolved rows and
cap, GeoNames parsing and queries from a synthetic fixture (no network),
checksum and cache reuse, MCP tool shapes, and harness routing for all three
paths plus text edits. A live GeoNames download is opt-in and tagged.
