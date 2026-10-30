# PVGIS

## Coasts — 2026-10-27

- **Refinement.** Inside the mask's unknown band, a point is inside when Natural Earth's 1:10m land
  (public domain) covers its 0.0125° cell and the eight around it, about 1.4 km inland. Sea points
  in the band stay unknown. The layer is `refine` in the mask (97,000 runs; the mask grows from
  0.7 MB to 2.5 MB, 0.6 MB gzipped).
- **Effect.** Of 38,820 published station positions between 60° S and 75° N, unknown falls from
  16.6% to 13.7%; Cape Town and Honolulu become inside. Coastal city centres within about 1.4 km
  of the water (Singapore, Lisbon, Venice) stay unknown.
- **Probes.** Cape Town (newly inside) and Table Bay about 4 km offshore both returned a SARAH3
  TMY. With the North Sea refusal at 19 km, PVGIS serves some near-shore sea, so sea points are
  neither inside nor outside here.
- **Not changed.** The 0.1° rule counts a cell inside when ERA5-Land's land fraction is at least
  0.5, which includes some near-shore sea.
- The map still draws the 0.1° mask only.

## Coverage — 2026-10-13

- **Radiation source by location.** PVGIS 5.3 TMY uses SARAH3 radiation where it is JRC's
  default, and ERA5 radiation elsewhere (owner decision: one product).
  - Ithaca returned `PVGIS-ERA5` with a 0.5 h irradiance offset.
  - London and Lake Victoria returned `PVGIS-SARAH3`.
  - All three report 2005–2023.
- **Refused points.** The open Atlantic, the North Sea about 19 km offshore, and Svalbard return
  400 "Location over the sea". The 25 km sea zone in JRC's report does not hold for `tmy` there.
- **Domain mask.** The catalog gates the product by a mask, documented in the
  [record](../validation/availability-gaps-2026-10-13/README.md):
  - inside: land between 60° S and 75° N;
  - unknown: coasts, lakes and small islands;
  - outside: open sea and polar land.
- **Provenance.** The adapter's warning and lineage name the run's radiation database.

## MCP Stage 2 availability — 2026-09-24

The local London v5_3 metadata sample records a 2005–2023 reference period and
selected source-month years as TMY evidence. This does not establish actual-year
weather in London or the same database/window worldwide. The catalog preserves
documented product access separately from the scoped probe result.

## v0.1 implementation result — 2026-09-20

The v5_3 native TMY adapter passed 8,760-hour acceptance. It retains the original EPW plus JSON inputs and selected source-month years. Published TMY requests do not accept actual-year selectors. The singular PVGIS HOLIDAYS/DAYLIGHT SAVING header is accepted explicitly.

## Earlier source/access review

Pin the validated `/api/v5_3/tmy` route. At 45°N, 8°E it returned 8,760 native EPW
rows and JSON records with T2m, RH, GHI, DNI, DHI, infrared, wind and pressure.
JSON identifies SARAH3 radiation, ERA5 meteorology, selected months and a
2005–2023 source period. Store that upstream hybrid provenance and the returned
irradiance time offset. Do not infer a single native resolution for all fields.
SARAH3 is approximately 0.05°; ERA5 is 0.25°. Availability varies geographically.
The [JRC 5.3 coverage figure](../validation/mcp-stage-2/pvgis-map-evidence.md)
now appears as documented default irradiance-source context in the local
availability map. It does not convert the London TMY probe into a regional
API-eligibility claim.

The native EPW has hours 1–24 and minute 0, despite the dictionary's 1–60 minute
convention. Preserve downloaded bytes; normalized re-exports use canonical hourly
end labels and record this compatibility correction. Source years differ by month.

No key. TMY is provider-generated, which satisfies existing-product retrieval;
OpenEPW does not construct historical TMY. Use JSON metadata alongside the native
EPW. Do not imply hourly `seriescalc` provides every EPW variable.
[API documentation](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/getting-started-pvgis/api-non-interactive-service_en).

JRC states its information is free without use restrictions; retain source
acknowledgment and upstream notices. [Usage conditions](https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/general-information/usage-conditions-data-protection_en).
Respect documented 30 requests/second maximum and overload responses; OpenEPW
will use much lower concurrency. Later PVGIS versions exist; support them only
after a separate contract check, never by silently changing v5_3 semantics.

Status: native product access validated; adapter and metadata preservation planned.
