# 0004 — Map-first chat and bounded geometric scene shadows

**Date:** 2026-09-26

**Status:** Implemented for local review on `feature/chat-ui`; shadow quality remains
bounded by public vector building and DEM data.

## Decision

Keep Python `WeatherService` authoritative for catalog, planning, jobs, EPW,
quality, and prepared visualization JSON. Persist the browser conversation as
versioned facts and events in the local SQLite data root. The optional React
client renders a full-canvas MapLibre globe, a floating chat column (bubbles
without a panel, per the owner's 2026-09-27 direction), and floating
charts. The browser cannot cause provider retrieval before an explicit reviewed
plan Run action. It does not put credentials or EPW bytes into browser storage.

Use OpenFreeMap styles and the `openmaptiles` `building` source layer for
decorative buildings. The public `3d` style URL returned 404 during the live
check; six OpenEPW appearances use working public styles and local color tokens.
On 2026-09-27 the owner removed the scene panel: the UI now uses the light
appearance, enters 3D automatically at zoom 14 (leaves below 13), keeps terrain
off and holds the page-load UTC time. The other appearances and terrain remain
in `scene.ts` without a UI control.
At district zoom, query a bounded set of vector building polygons and
`render_height` values. Project each roof away from the local solar azimuth to
construct ground shadow polygons. Intersect upper roof projections with lower
roof polygons for neighboring roof occlusion. With Mapterhorn terrain enabled,
use `queryTerrainElevation` to adjust projection endpoints and ray-march a
bounded 24-by-20 ground grid toward the sun for relief occlusion. MapLibre
drapes the resulting GeoJSON fill over its terrain. All display elevation uses
the map's terrain exaggeration; MapLibre documents that
[`queryTerrainElevation` includes exaggeration](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/#queryterrainelevation).

This is geometric occlusion, separate from hillshade and extrusion-face light.
It is a bounded district approximation, not a physical shadow map or an energy
model. At night direct cast polygons are cleared. At globe zoom, flat view,
unavailable building geometry, or unavailable DEM the scene reports its limit.
Style reload temporarily removes terrain, waits for the base style to become
idle, then restores DEM and shadows; this avoids a blank scene observed during
the first live terrain/theme swap.

## Renderer comparison

| Approach | Fit for this client | Decision |
| --- | --- | --- |
| Shared-depth Three.js shadow pass | Good for owned meshes, as in [MapLibre's single-model example](https://maplibre.org/maplibre-gl-js/docs/examples/add-a-3d-model-with-shadow-using-threejs/). Public basemap buildings and MapLibre's terrain mesh are internal; duplicating them across tiles and globe transitions would be a separate renderer project. | Deferred; the example alone does not prove basemap and relief shadows. |
| Synchronized independent scene | Can own depth and softness, but duplicates camera/projection/terrain and risks tile seams and detached geometry. | Rejected for this bounded local UI. |
| Projected vector geometry on MapLibre layers | Uses the native projection and terrain draping for public basemap polygons; deterministic geometry can be tested without GPU fixtures. | Selected with explicit bounds and limitations. |

The approved plan called for a custom-layer prototype before production
shadow work. The implementation instead uses native MapLibre vector layers
because they can drape projected geometry without duplicating internal terrain
meshes. This is a rendering strategy change for review, not evidence that a
shared-depth prototype passed. The Eaui repository was read-only reference;
no code was copied from it.

## Data and visual limits

- OpenMapTiles `render_height` may come from levels or a fallback. It is not a
  surveyed building height. Roof-to-roof occlusion covers roof intersections,
  not vertical walls or all partial facade shadows. At most 120 visible
  buildings participate per update; large or highly detailed footprints are
  skipped.
- Terrain rays sample a coarse visible grid and at most 240 m toward the sun
  in 12 m increments. Distant ridge shadows, sub-grid detail, edge continuity,
  penumbra, and exact occlusion against roof mesh are outside this pass.
  Unloaded DEM cells do not create fabricated shadows. The cell budget keeps
  interaction usable on the tested desktop but is not a cross-device guarantee.
- Shadows and building extrusion are display-only. They do not provide
  building simulation inputs, solar access, weather availability evidence, or
  calibrated shadow results. The `hillshade-shadow-color` layer remains terrain
  shading only and is not counted as cast-shadow proof.
- OpenFreeMap, OpenMapTiles, OpenStreetMap, and Mapterhorn attribution is shown
  in the map. Public tiles have no guaranteed SLA. Source data and licenses
  remain with their providers; no map tiles or third-party building data are
  committed to this repository.

The [validation record](../validation/2026-09-26-chat-ui.md) identifies what
the real browser and deterministic geometry checks actually exercised.
