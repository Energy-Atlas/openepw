# Map-first weather chat

This optional browser client uses the shared OpenEPW Python REST service. The
globe, terrain, decorative buildings, and charts are display layers; they do not
change weather data or certify an EPW for simulation.

## Run locally

From the repository root, start the API in one terminal:

```powershell
.venv\Scripts\openepw.exe --data-root .local/openepw --env-file .env serve --host 127.0.0.1 --port 8000
```

The existing ignored `.env` is read by the Python service. The browser does not
read it. In another terminal:

```powershell
cd web/chat-ui
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. For a local production-build check, run
`npm run build` followed by `npm run preview`. Both Vite modes proxy `/v1` to
the loopback API on port 8000. The package can be installed and used without
Node or this UI.

## Use

- The chat floats over the right side of the map as separate message bubbles.
  The reply area follows the current question: the message field appears only
  when free text is expected. A choice shows its options with `Other — type an
  answer`; a plan review shows `Assess and review plan` or `Run reviewed plan`
  with `Type a correction`; a map question shows `Choose on map`, GeoJSON
  attachment and `Type coordinates`.
- Attachments (`+`) and map geography input (`Map`) are hidden for now
  (`ATTACH_AND_MAP_INPUT` in `src/App.tsx`); the notes below describe them
  for when they return.
- Enter a place, coordinates, years, and product in chat. Select `Map` beside
  the message field to open the point/box/polygon input toolbar; it disappears
  when the input is accepted or closed. Use `+` in the composer to attach an
  EPW or WGS84 GeoJSON file. The plan shows exact service-accepted points
  before retrieval.
- Geocoder candidates appear as numbered options in chat and matching filled,
  numbered markers on the map. Choosing either only selects: the globe rotates
  to the point (zooming out and back in when it is off screen) and a popup
  shows the name, coordinates and `Confirm`. Nothing is answered until
  `Confirm` in the popup or the reply area. `Other — type an answer` reopens
  the message field with a `Confirm` button.
- A confirmed candidate or typed coordinates are then summarised (name and
  coordinates) with `Approve location`. The message field stays open: a reply
  such as "the one in England" or "no, Somerville" is read as a correction of
  that location. A place list is approved the same way (`Approve locations`)
  and corrected with edits such as "remove 3" or "add Reno". Other replies
  patch the list rather than replace it: "should be San Francisco" or just
  "San Francisco" fixes a row that was not found (the closest spelling if
  several), "I meant Honolulu for hawaii" replaces the row it names, a place
  spelled like a listed one fixes it, "and / also / add …" appends, anything
  else is added, and only "only …" or "… instead" replaces the list. A "place, region" pair that is not
  found is retried as two places. Any change needs approval again.
- Hovering the globe (outside the chat) opens a card listing every named
  product at the cursor: a filled green dot when the catalog lists it there, a
  green ring when it is checked only when planning, a grey ring when it is not
  available, and the looked-up station and distance for station products,
  whose icon is a three-bar signal for distance (under 10 km 3 bars, 10–100 km
  2, 100–250 km 1, farther 0; green when listed, grey when unverified). The
  card waits for the cursor to rest, caches each 0.1° cell and follows the
  session's years. Clicking the globe does nothing (no double-click zoom);
  dragging pans. Custom cursors mark normal, selectable, text, globe and
  dragging states. The legend is titled "Weather Product Coverage".
- The product question lists named products, grouped into actual year and
  typical year, e.g. `NSRDB actual year · GOES v4`, `NOAA ISD station
  observations`, `PVGIS TMY 5.3 · SARAH3` or `OneBuilding TMYx.2009-2023`;
  each names exactly what is downloaded. A typed type or provider ("TMYx",
  "NSRDB") narrows the list. While it is open the map frames the locations and
  tags each with the products available there, one pill per product in the
  colour of its catalog layer. Solid tags are listed in the catalog; outlined
  tags with `?` are checked when planning. Station products (NOAA, OneBuilding)
  draw a dashed line, moving away from the location, to the looked-up station,
  with their tags beside the line. The products are a list of tick boxes with
  names only; the info icon at the end of each row opens its description on
  hover or focus. Tick several products, or click their map tags to select or
  deselect them, then confirm; selected tags stay bright and the rest dim.
  Actual-year and typical-year products can be ticked together; each kind
  (and Copernicus CDS, which queues at Copernicus) becomes its own plan and job, shown in one job card, and one ZIP downloads
  all of them. With several locations each row shows `available / sites`;
  hovering it says where the product is available. Only typical-year products
  skip the year question. Years may be written as `2012`, `2012-18`,
  `2012-2018`, `2012, 2013, 2015-16, 2020`, `[2012, 2013, 2016, 2020]`, `the
  2010s`, or relative phrases such as "the last three years", which the model
  expands with today's date. The dialog and options have no height limit. While the
  question is open only the looked-up stations keep their name pills, and every
  station name carries a `NOAA` or `One` prefix pill.
- Select a geocoder candidate or type an alternative. `Assess and review plan`
  reads catalog and planning evidence. `Run reviewed plan` starts provider work.
- The job card shows processed outputs. Download one successful EPW or a compact
  ZIP of successful outputs from the local server to your browser's download
  folder. The ZIP includes the output mapping; failures remain in the job card.
- An attached user EPW is a separate analysis input. View prompts or the `Open chart`
  controls prepare JSON from existing artifacts. Charts float over the map;
  `Earlier views` reopens a closed panel.
- There is no scene control panel. Zooming to 14 or closer tilts the map into
  3D with decorative buildings and approximate geometric cast shadows; zooming
  out below 13 returns to the flat globe. The scene uses the light appearance,
  terrain off, and the UTC time at page load; moving the map recomputes the
  local sun angle while keeping that UTC time fixed.
  The bottom-left legend lists every Stage 1 availability layer with its own
  toggle, all on by default: NOAA ISD stations (filtered to stations with
  reports in every year the conversation names), OneBuilding published EPWs
  (approximate positions as rings), the NSRDB `tdy-2023` source grid, the
  approximate PVGIS SARAH3 region with its London probe, and ERA5/ERA5-Land
  documented extents. `What these layers mean` gives each caveat, the
  unmapped products and credits. All layers are documentary context, not point
  eligibility or weather completeness.
- The NSRDB grid layer needs the reviewed derived mask. Copy `manifest.json` and
  `mask.json` (not `meta.bin`) from the `feature/data-avail` acquisition into
  `.local/openepw/footprints/nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/`. The service
  checks the mask SHA-256 against the manifest and skips stale or mismatched
  masks; without it, NSRDB is listed as unmapped.

The UI resumes its session and current job after refresh in the same browser
session. Browser storage holds only the session ID. Server-side SQLite and
artifact files live below the configured data root. Future-weather planning is
temporarily unavailable in this UI.

## Colour system

All browser colours come from `src/theme.ts` and the matching `--oe-*`
variables in `src/app.css`, including the recoloured Positron basemap and the
charts. The UI is true greyscale: neutral greys from paper to ink on a dark
grey backdrop, separated by lightness and shape. Weather-source layers keep
their colours (`SOURCE_COLORS`: teal NOAA, deep-ocean OneBuilding, slate
regions and extents), and amber is reserved for the user's own selection. Add colours there
rather than inline; `tests/theme.test.ts` rejects stylesheet colours outside
the theme.

## Checks and limits

Run `npm test` and `npm run build` from this directory. See the
[acceptance record](../../docs/validation/2026-09-26-chat-ui.md) and
[scene decision](../../docs/decisions/0004-map-first-chat-scene.md) for live
checks and remaining rendering limits. OpenFreeMap and Mapterhorn are public
external tile services without a local availability guarantee; coordinate and
chat input remain usable during a map outage.
