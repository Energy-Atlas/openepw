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

- Enter a place, coordinates, years, and product in chat. Select `Map` beside
  the message field to open the point/box/polygon input toolbar; it disappears
  when the input is accepted or closed. Use `+` in the composer to attach an
  EPW or WGS84 GeoJSON file. The plan shows exact service-accepted points
  before retrieval.
- Select a geocoder candidate or type an alternative. `Assess and review plan`
  reads catalog and planning evidence. `Run reviewed plan` starts provider work.
- The job card shows processed outputs. Download one successful EPW or a compact
  ZIP of successful outputs from the local server to your browser's download
  folder. The ZIP includes the output mapping; failures remain in the job card.
- An attached user EPW is a separate analysis input. View prompts or the `Open chart`
  controls prepare JSON from existing artifacts. Charts float over the map;
  `Earlier views` reopens a closed panel.
- `District view` enables close 3D context. One UTC scene time is initialized
  from the current UTC clock; moving the globe changes the displayed local sun
  angle while keeping that UTC time fixed. Terrain, season, UTC time, six map
  appearances, and approximate geometric cast shadows are visual controls.
  Every catalog product with a documented footprint receives a faint source
  scope layer. Unmapped products are counted in the legend. These documentary
  scopes are evidence context, not verified coverage promises.

The UI resumes its session and current job after refresh in the same browser
session. Browser storage holds only the session ID. Server-side SQLite and
artifact files live below the configured data root. Future-weather planning is
temporarily unavailable in this UI.

## Checks and limits

Run `npm test` and `npm run build` from this directory. See the
[acceptance record](../../docs/validation/2026-09-26-chat-ui.md) and
[scene decision](../../docs/decisions/0004-map-first-chat-scene.md) for live
checks and remaining rendering limits. OpenFreeMap and Mapterhorn are public
external tile services without a local availability guarantee; coordinate and
chat input remain usable during a map outage.
