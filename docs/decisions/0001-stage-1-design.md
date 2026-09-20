# ADR 0001 — Stage 1 design recommendations

Date: 2026-09-20. Status: proposed, awaiting the single Stage 1 owner gate.

The brief requires a Python-first research utility, practical providers, two
distinct future methods and transparent provenance. Live probes justify:

1. **Own core, thin adapters.** Use pandas/Pydantic, own EPW codec, optional server
   and climate dependencies. A monolithic weather framework adds coupling;
   independent REST/MCP logic would duplicate scientific behavior.
2. **Start with Open-Meteo ERA5 and PVGIS.** They returned useful hourly/native
   products without credentials. Add OneBuilding/NOAA breadth, then credentialed
   NSRDB/CDS without counting access paths to the same source as independent data.
3. **Independent CMIP6 morphing + hourly WRF selection.** This satisfies the two
   method families. Two morphing wrappers do not; daily disaggregation is deferred
   because a real hourly alternative is accessible. Method B's limited geography,
   RCP namespace and windows are explicit proposed v0.1 constraints.
4. **Exclude ambiguous/restrictive implementation reuse.** pyepwmorph's MIT banner
   conflicts with its copied AGPL module; FWG is NC-SA. Use published methods and
   permissive dependencies. epwshiftr is a reference rather than an R dependency.
5. **Preserve source semantics.** Strict model selection, no hidden hybrids,
   per-variable lineage, fixed-standard-time EPW output, field-specific missing
   markers and separate structural/physical QC. Native source files remain intact.
6. **Local durable jobs.** SQLite/filesystem with bounded workers and atomic writes
   serves v0.1; distributed scheduling and a frontend are outside scope.

Consequences: core remains light; some provider authentication is pending; data
licenses must not be conflated with MIT code. OneBuilding public redistribution
needs clarification. Full CMIP6 numeric/runtime acceptance is early Stage 2 work,
not a Stage 1 success claim. Source-cell deduplication may be provisional until
the provider exposes actual identity.

Evidence and alternatives: [provider feasibility](../providers/README.md),
[reuse review](../methods/reuse-review.md), [future methods](../methods/future-weather.md),
[validation](../validation/README.md).
