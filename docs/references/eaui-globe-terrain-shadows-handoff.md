> External design reference copied from
> `C:/github/eaui/docs/globe-terrain-shadows-handoff.md` on 2026-09-26.
> It describes the Eaui map at the source revision below. Its implementation
> directions and source paths are reference material, not OpenEPW requirements
> or authorization to copy code or implement cast shadows.

# Globe, 3D terrain, and cast shadows — feature handoff

Date: 2026-09-26

Source revision: `563b152a5243839c56c247a82e07b44235b64929` (`feature/agentic`; the same local commit is checked out by `feature/basemap`)

## Feature intent

Render one continuous map that reads as a globe from afar and as a tilted, terrain-aware scene up close. The sun has one global position derived from season and UTC time. At close range, terrain and modeled buildings receive directional light and cast visible, geographically aligned shadows. The map remains an analytical surface: geographic context stays quiet, modeled geometry and data remain legible, and all lighting, relief, and shadows are **display only**. They do not alter energy, shading, or PV calculations.

This document covers the map scene, its theme, and its basic parameters. It specifies no surrounding application layout or control arrangement.

## Current baseline and gap

| Part | Observed in this revision | Target for this feature |
| --- | --- | --- |
| Projection | MapLibre globe projection is reapplied after style changes. The sphere becomes apparent at low zoom; the district is viewed at street zoom. | Preserve a continuous camera transition between globe and district views. |
| Basemap | OpenFreeMap vector context is recolored from the active appearance; its own buildings are hidden. Failure falls back to an appearance-colored background. | Keep geographic context subordinate to modeled geometry, with attribution and a usable failure state. |
| Terrain | Live Mapterhorn Terrarium DEM is available in the tilted 3D view only, with a separate hillshade layer. Failure falls back to flat ground. | Keep terrain geometry and all ground shadows in the same elevation frame. |
| Buildings | Modeled footprints are extruded from synthetic heights; MapLibre shades their faces. | Buildings cast onto ground and other buildings, and receive occlusion from terrain and neighboring buildings. |
| Sun and sky | A single subsolar point drives the district sun, MapLibre's directional extrusion light, theme-colored sky/fog, and hillshade direction. | Use that same sun vector for every cast-shadow calculation. |
| Shadows | **No cast shadows exist.** Hillshade and dark extrusion faces are tonal shading, not geometric shadows. MapLibre 6.9.1's light does not cast them. | Add a real shadow rendering pass in the close-range 3D scene. |

The current globe also has no geographic day/night terminator. Its atmosphere and light-theme globe dimming are visual treatment, not a shadow over the planet. A globe-scale terminator is outside the close-range cast-shadow requirement and must not be implied by the shadow control.

## Scene and theme

- **Geography:** Preserve the OpenFreeMap roads, water, parks, and labels as orientation. Hide source buildings so they do not double the modeled buildings. Keep OpenFreeMap/OpenMapTiles/OpenStreetMap and terrain attribution visible where their data is used.
- **Modeled geometry:** Render buildings over the terrain at their sampled ground elevation. Use the current analytical color ramp, distinct missing-data color, and selection outline. Shadows must not obscure selection or make a value appear to belong to a different class.
- **Terrain:** Use Mapterhorn's live Terrarium DEM for display, with hillshade under labels. Terrain is active only in 3D; a flat view does not fetch or display relief. Start at true scale. Exaggeration changes the rendered mesh and the shadow geometry together, avoiding detached shadows.
- **Light and atmosphere:** Derive the local sun at the rendered location from the globe's single subsolar state. Directional light shades extrusions; hillshade uses the same azimuth. Sky, twilight, fog, and light color blend from the active appearance's `data.sky` tokens as solar elevation changes. Haze thickens the horizon veil and dims the light. Sun diffusion is a visual sky/light treatment; it is not physical sun size or a substitute for cast-shadow softness.
- **Six curated appearances:** Light, Dark, Technical monochrome, Lieflat-inspired, Clean technical light, and Dark engineering each supply basemap, data, and sky colors. Light appearances dim the zoomed-out globe to avoid a pale veil; dark appearances do not. Preserve readable labels and building contrast in every appearance. Shadow tint and opacity should derive from appearance tokens, with enough contrast to read on both light and dark ground without becoming a solid black overlay.
- **Night:** With the sun below the local horizon, direct solar cast shadows disappear. The themed night sky and low ambient visibility remain. Do not add illuminated windows or area-based night lights; decision 0019 removed them.

## Basic parameters

These are scene values and valid ranges, not a specification of where or how controls are drawn. Changes to existing values go through the validated map view operations; shadow settings need the same explicit operation path.

| Parameter | Current default and range | Scene effect |
| --- | --- | --- |
| 3D view | Off by default; on/off | Enables camera tilt, building extrusion, scene lighting, and eligibility for terrain and cast shadows. Current 3D camera starts at 50° pitch and −20° bearing; maximum pitch is 70°. |
| Terrain | Off by default; on/off in 3D | Adds the live DEM and hillshade. If 3D is turned off, the chosen terrain state is retained but rendering pauses. |
| Terrain exaggeration | 1× default; whole numbers 1–10× | Scales displayed relief. Shadow projection must use the displayed elevation. |
| Season | Day 172 default; integer day 1–365 | Sets solar declination. |
| Time of day | 16:00 UTC default; minute 0–1439 UTC | Sets the globe's shared solar time. The current slider moves in 10-minute increments. |
| Light intensity | 100% default; integer 0–200% | Changes directional light strength within theme-specific headroom. |
| Sun diffusion | 25% default; integer 0–100% | Widens visual twilight and horizon glow and slightly flattens direct light. It must be labeled separately from geometric shadow softness. |
| Horizon haze | 20% default; integer 0–100% | Thickens fog and reduces direct light. |
| Cast shadows | **Proposed:** on/off, active only in 3D after geometry and terrain are ready | Enables geometric occlusion from terrain and buildings. The default and any quality/softness setting need a rendering prototype before being fixed. No shadow parameter or operation exists yet. |

The map starts centered on Boston Back Bay at zoom 15. Zoom, pitch, and bearing remain ordinary camera interactions. The globe projection applies in both flat and 3D views; 3D adds tilt rather than switching projections.

## Shadow rendering contract

1. Use the sun vector derived from `subsolarPoint` and `sunFromSubsolar`. The direction visible in facade shading, hillshade, and cast shadows must agree at the same place and time. Recompute for the relevant local scene as the camera moves; a sun sampled only at the original Boston center cannot remain correct for every place on the globe.
2. At district scale, terrain should cast onto terrain and buildings should cast onto terrain and other buildings. A shadow must follow real projected geometry, including building height and displayed terrain elevation, rather than a flat translated footprint.
3. Shadows move continuously as season or UTC time changes, lengthen as the sun lowers, and vanish when the sun is below the local horizon. Avoid discontinuities at longitude wraparound and the globe-to-local camera transition.
4. Keep shadows visually subordinate to metric colors, selection, labels, and terrain detail. Use theme-derived tint/strength. Do not use `hillshade-shadow-color` as evidence that cast shadows are implemented.
5. If shadow rendering is unavailable or too slow, report that state and keep the lit map usable. If DEM tiles fail, retain the existing flat-ground fallback and either project building shadows onto that flat ground with a clear limitation or pause shadows explicitly; never show shadows that appear to follow terrain that is absent.

MapLibre 6.9.1 does not supply cast shadows through `setLight` or `fill-extrusion`. A depth-based shadow pass over a terrain mesh and modeled building geometry is a plausible implementation direction, but integration with MapLibre's globe projection, terrain elevation, layer ordering, and camera matrices needs a focused rendering prototype before selecting the renderer. Treat shadow resolution, filtering, and performance budgets as prototype outcomes, not settled product parameters.

## Acceptance checks

- Globe and district views retain the same map center and theme through zoom, appearance changes, and basemap reloads. Projection, light, sky, terrain, and shadows restore after a style swap.
- In 3D, terrain at 1× and an exaggerated setting shows buildings and shadows attached to the same ground. A known morning/noon/evening sequence changes shadow direction and length consistently with the local sun.
- A building shadows its surroundings, a neighboring building can receive that shadow, and relief can occlude direct light. No daytime solar shadows appear when the local sun is below the horizon.
- Light, dark, and monochrome appearances preserve metric and selection contrast with shadows enabled. Review the other three appearances as well; the existing globe review did not cover every theme.
- Loading, ready, failed, retry, and paused states are legible for basemap, terrain, and shadow rendering. Turning 3D off pauses terrain and shadows without losing chosen values.
- Keyboard users can change every exposed parameter and understand its value and unavailable state. Verify a real rendered scene visually; the browser terrain stub is flat, so automated screenshots using that stub cannot prove relief or shadow geometry.

## Source trail

- Projection and globe treatment: `src/app/pages/MapPage.tsx`, `src/app/pages/lighting.ts`, [decision 0019](decisions/0019-globe-projection-and-solar-state.md).
- Terrain source, activation, and hillshade: `src/app/pages/terrain.ts`, `src/app/pages/useTerrain.ts`, [decision 0015](decisions/0015-terrain.md).
- Sun, sky, and current no-shadow limitation: `src/app/pages/sunPosition.ts`, `src/app/pages/lighting.ts`, `src/app/pages/useSceneLighting.ts`, [decision 0018](decisions/0018-map-scene-lighting.md).
- Appearance tokens and basemap recoloring: `src/app/appearance/appearances.ts`, `src/app/pages/basemapStyle.ts`, [decision 0012](decisions/0012-openfreemap-basemap-back-bay.md).
- Current parameters and validation: `src/app/view/viewOperations.ts`, `src/app/panels/MapProperties.tsx`, `src/app/pages/MapPage.tsx`.
