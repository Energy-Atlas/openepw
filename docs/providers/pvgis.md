# PVGIS

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
