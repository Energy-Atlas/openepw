# Features and implementation status

Updated 2026-09-20. No product feature is implemented yet. “Validated” below means
a bounded live probe succeeded; it does not mean production support.

| Capability | v0.1 intent | Current status |
| --- | --- | --- |
| Python package / CLI | `openepw`; small scripting CLI | Designed |
| Geocode / discover / plan / execute / fetch | Typed, serializable workflow; alternatives visible | Point geocoding/API access probed; design only |
| EPW I/O and QC | Own parser/writer; sentinels, leap/time handling | Dictionary inspected; three native sample formats inspected |
| Open-Meteo ERA5 | Global historical conversion | 48-hour sample validated |
| PVGIS | Published native TMY + metadata | Full TMY access validated |
| OneBuilding | Published TMYx/TMY catalog and retrieval | Catalog + EPW validated; redistribution terms unresolved |
| NOAA/ISD | Station observations and explicit hybrids | One-day observations validated; successor noted |
| NSRDB/NLR | U.S. solar-rich historical/TMY access | Discovery validated; download needs email/key |
| Direct CDS ERA5/Land | Optional direct access | Catalog/auth gate validated; token/terms needed |
| Spatial/batch | Points, bbox, GeoJSON Polygon; source dedup | Designed |
| Hybrids / provenance | Explicit source assignments and warnings | Designed |
| Future method A | CMIP6 monthly morphing; model/member outputs | Metadata access + reuse review complete; numeric/runtime check pending |
| Future method B | Representative/extreme hourly WRF profiles | One full future EPW range-read validated |
| Future profiles | Typical, method-specific extreme, coherent ensemble | Designed; sampled reserved/experimental |
| REST / local jobs / artifacts | FastAPI, SQLite, filesystem | Designed |
| MCP | Thin stdio/Streamable HTTP adapter | Designed |

See [provider matrix](docs/providers/README.md), [future definitions](docs/methods/future-weather.md)
and [implementation plan](docs/plans/2026-09-20-stage-2.md) for exact capabilities.

Boundaries: no historical TMY/XMY synthesis; no frontend; no fabricated fine-grid
weather; no implicit source blending; no SSP/RCP relabeling. NOAA alone generally
lacks solar. Open-Meteo free service is noncommercial. Method B is initially
limited to published U.S. locations, RCP4.5/8.5 and two periods; it is not a global
SSP method or a multimodel ensemble. Unknown geocoding modes fail explicitly.
