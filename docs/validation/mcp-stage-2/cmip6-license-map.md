# Local CMIP6 license-scope map display

Updated 2026-09-25 on `feature/data-avail`. The local availability map's CMIP6
view now displays the [offline Stage 1 model-license join](../mcp-stage-1/cmip6-license-scope.md)
without drawing a geographic coverage polygon or claiming a verified climate
window. This is a visualization of catalog and license scope, not a production
availability-service decision.

The map builder verifies the saved ledger/raw checksums, reads the accepted local
combination inventory and WCRP registry, and applies the same model-level
effective-license allow-list as the offline analysis. It embeds aggregate counts
only: no model store URLs, full catalog, climate chunks or credentials. A missing
registry makes listed combinations' license status unknown. The source catalog
was last modified 2022-06-28 and the registry snapshot was retrieved 2026-09-23;
the display labels them as pinned evidence.

| Scenario | Combinations | Models | CC BY 4.0 | CC0 1.0 |
| --- | ---: | ---: | ---: | ---: |
| SSP126 | 138 | 25 | 132 | 6 |
| SSP245 | 170 | 25 | 156 | 14 |
| SSP370 | 151 | 24 | 137 | 14 |
| SSP585 | 177 | 26 | 171 | 6 |
| All listed combinations | 636 | 28 distinct | 596 | 40 |

The SSP selector changes the count and proportional license bar in the map.
Neutral land geometry supplies orientation only; the panel explicitly states
that geographic footprint and requested climate windows are unverified. The
four sampled original store-license texts remain separate from this effective
model-license screen. No Stage 1 collection was repeated.

The land shapes are uniformly neutral in CMIP6 mode by design: the colored bar
and its legend encode model-license counts, not location. The saved catalog and
license registry contain no validated per-model geographic footprints. Spatial
coloring would require separately reviewed coordinate evidence; assigning the
license colors to land would fabricate a geographic availability claim.

The rebuilt ignored worktree HTML and the browser visualization copy are each
730,344 bytes with SHA-256
`23bf7389a531f1830bacf7c92d5da8f941d514f6c7f299f1f590f337e1d8afbe`.
It was generated from the copied Stage 1 snapshot root, the existing ignored
world topology and reviewed NSRDB footprint manifest. The browser check selected
SSP245 and SSP585 and observed the expected count and license-bar labels. The
normal offline map-builder command remains in the
[NSRDB map acceptance](nsrdb-footprint-acceptance.md); it never calls `collect`.
The full offline suite passed (186 passed, 14 live tests skipped); Ruff and the
JavaScript syntax check passed. Two existing dependency deprecation warnings
remain in the full suite.
