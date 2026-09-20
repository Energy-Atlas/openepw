# UI provenance and dependencies

Appearance definitions in src/shell/appearances.ts are adapted from
Energy-Atlas/energyatlas-ui at e52d513, src/app/appearance/appearances.ts.
The owner explicitly requested reuse of this repository's UI foundations.
The reference has no root license declaration; confirm an explicit license grant
for these definitions before public redistribution. This does not block the
owner-authorized local implementation. Do not imply the reference data is MIT.

Layout, map interaction and shell modules are new OpenEPW code informed by the
reference. The small MapLibre worker build hook follows its verified Vite setup.
No synthetic district datasets, simulated stage engine, LLM code or credentials
were copied. Dependencies retain their own bundled licenses: inspect package-lock
and node_modules/<package>/LICENSE for the installed versions.

Basemap: OpenFreeMap / OpenMapTiles / OpenStreetMap contributor attribution
is displayed by MapLibre. Terrain: Mapterhorn attribution is displayed on the map.
Geist is distributed through @fontsource-variable/geist; retain its font license.
Weather/source licensing remains in the Python-generated artifact manifests.
