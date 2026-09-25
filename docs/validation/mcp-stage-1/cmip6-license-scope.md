# CMIP6 model-license scope screen from accepted Stage 1 snapshots

This is an offline addendum to the accepted [Stage 1 findings](README.md), made
on 2026-09-25. It joins existing local metadata; it makes no new network requests
and does not change the accepted combination, coordinate or weather evidence.

## Inputs and method

The ignored `.local/mcp-availability/` contains the downloaded Pangeo catalog
(`cmip6-catalog`, SHA-256
`a19a343d57f3137d11ce89e07e4c66586ed02e3d396361bf209eb7a324328b89`)
and WCRP [CMIP6 source-ID license registry](https://github.com/WCRP-CMIP/CMIP6_CVs/blob/main/CMIP6_source_id.json)
(`cmip6-license`, SHA-256
`6e6772a545d8abcfdce6e79ed1dc92fdee90a351f5a6b8748920d7e817404759`).
Both hashes match the saved ledger. The catalog response was last modified
2022-06-28; both snapshots were retrieved 2026-09-23. These dates and hashes
describe this evidence, not current upstream completeness or license terms.

The existing catalog analysis produces 636 distinct combinations across 28
`source_id` models. Each combination requires one member and grid with all seven
monthly variables in historical and one SSP experiment. The new offline analysis
joins each model once to `source_id[model].license_info` in the saved registry and
compares its effective `id` with the current OpenEPW runtime allow-list:
`CC BY 4.0`, `CC BY-SA 4.0`, `CC0 1.0`. A missing or unrecognized ID is `unknown`,
never silently allowed or called legally restricted. The local result retains
the registry's `id`, URL, history, license text and `source_specific_info` by
model. Combination records continue to reference the model, avoiding a
per-store or per-request registry read.

| Effective model-license ID | Models | Catalog combinations |
| --- | ---: | ---: |
| CC BY 4.0 | 27 | 596 |
| CC BY-SA 4.0 | 0 | 0 |
| CC0 1.0 | 1 (`GISS-E2-1-G`) | 40 |
| Missing or unrecognized | 0 | 0 |

Thus all 636 combinations **pass the effective model-license allow-list in this
pinned snapshot**. This is an initial scope gate, not a declaration that all 636
stores are current, downloadable, complete for a requested window, or cleared
for every redistribution or downstream use. The four sampled ACCESS-CM2 store
metadata documents still say CC BY-SA 4.0; the WCRP record states a 2022-06-10
relaxation to CC BY 4.0. Preserve the original store text and effective registry
record separately. Uninspected stores have `original_license=unknown`; the model
join does not fill that field. Four catalog models have a nonempty
`source_specific_info` link, which remains visible with the model record.

## Stage 2 consumption rule

Import the catalog and registry as one versioned, checksum-verified generation.
Precompute one effective-license gate per model and inherit it for its listed
combinations. If either source is absent, mismatched or stale for a current claim,
report the license gate as `unknown`; never reuse this addendum's count as an
unversioned permission. A known adapter or policy exclusion may still exclude
independently. Re-evaluate the join when either source changes. Keep the requested
historical/reference and future-window gate separate: no Stage 1 CMIP6 time
coordinate or climate chunk work established those windows. Execution still
checks the selected stores and records their original terms and per-variable
provenance.

The offline implementation is `cmip_license_scope` in
`scripts/mcp_research/analysis.py`; `analyze --root <existing snapshot root>`
places the model map and counts under
`inventories["cmip6-catalog"]["license_scope"]` in ignored `analysis.json`.
It never invokes `collect`.

The [local availability map view](../mcp-stage-2/cmip6-license-map.md) displays
these model-level counts by SSP scenario while leaving geographic footprint and
requested climate windows unshaded and unknown.
