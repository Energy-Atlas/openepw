# Reuse and licensing review

Reviewed 2026-09-20. OpenEPW code remains MIT; upstream data licenses remain
separate and travel with artifacts. No third-party implementation code was copied
into the tracked repository in Stage 1. This is a scoped reuse assessment.

| Candidate | Inspected license/dependencies | Decision |
| --- | --- | --- |
| pyepwmorph 2.2.0, revision `374d5eec414181dd5a9c184043c574db2d95c3aa` | Top-level MIT; imported `ladybug_psychrometrics.py` says copied from AGPL-3.0 Ladybug. Requires xarray, dask/distributed, intake, gcsfs, pyarrow, pvlib, skyfield, timezonefinder, others | Do not depend on or copy it while this conflict remains. Use methodology references, not code |
| epwshiftr development 0.1.4.9001, revision `90ad1f4f0338d8077027dff34f74ebf2d3168d34` | MIT + named copyright holders; R with RNetCDF, DuckDB, data.table, mirai, S7 | Useful reference/oracle; avoid an R runtime requirement in the Python package |
| Future Weather Generator CMIP6 Global 5.1.0 | First-party download page declares CC BY-NC-SA 4.0; Java JARs and Bitbucket source | No copying/bundling/dependency; noncommercial/share-alike restriction conflicts with intended permissive code reuse |
| PsychroLib | MIT; focused psychrometrics, optional numerical acceleration | Candidate permissive dependency for humidity conversions; retain notices if adapted |
| pvlib-python | BSD-3-Clause; scientific Python | Optional solar derivation/reference, no dependency for plain EPW I/O |
| cdsapi | Apache-2.0 | Optional direct CDS client; retain notices if redistributing |
| Open-Meteo server / Ladybug | AGPL implementation code | HTTP data access only / no Ladybug code reuse |

Evidence: [pyepwmorph license](https://github.com/justinfmccarty/pyepwmorph/blob/374d5eec414181dd5a9c184043c574db2d95c3aa/LICENSE),
[conflicting module](https://github.com/justinfmccarty/pyepwmorph/blob/374d5eec414181dd5a9c184043c574db2d95c3aa/pyepwmorph/tools/ladybug_psychrometrics.py),
[epwshiftr DESCRIPTION](https://github.com/ideas-lab-nus/epwshiftr/blob/90ad1f4f0338d8077027dff34f74ebf2d3168d34/DESCRIPTION),
[FWG download/licensing](https://future-weather-generator.adai.pt/download/),
[PsychroLib](https://github.com/psychrometrics/psychrolib/blob/master/LICENSE.txt),
[pvlib](https://github.com/pvlib/pvlib-python/blob/main/LICENSE),
[cdsapi](https://github.com/ecmwf/cdsapi/blob/master/LICENSE.txt).
Hashes of fetched license/source files are in [research evidence](../validation/2026-09-20-research.json).

pyepwmorph implements monthly shift/stretch morphing, reads Pangeo CMIP6 or custom
monthly CSV, and exposes SSP126/245/370/585. epwshiftr's inspected development tree
also includes distributional, daily-adjustment and interpolation methods beyond
original morphing; do not equate all its backends. Its public workflow uses ESGF
CMIP6 and optional ERA5 calibration. FWG offers CMIP6 and regional CORDEX variants,
multiple morphing options, solar/humidity adjustments and scenario selections.
None was installed or executed here; runtime compatibility is not claimed.

Data findings: Open-Meteo CC BY data and hosted-service restrictions are separate.
OEDI 5974 declares CC BY 4.0. The inspected GFDL-CM4 historical and SSP245 Zarr
attributes still declare CC BY-SA 4.0, but the official
[CMIP6 license registry](https://wcrp-cmip.github.io/CMIP6_CVs/docs/CMIP6_source_id_licenses.html)
records GFDL-CM4's relaxation to CC BY 4.0 on 2022-06-08. Preserve both the original
attribute and the authoritative updated grant with its lookup date. Do not relabel
data MIT or infer updates for unrelated sources. A data-license policy must expose
attribution and any applicable restrictions, reject unknown/NC data by default,
and allow compatible model selection. OneBuilding redistribution is unverified.

No license conflict forces a project-wide stop: exclude restricted code, implement
published formulas independently, and keep restricted/unclear data out of bundled
fixtures. Escalate only if an essential future change actually requires that reuse.


## Implemented reuse and license policy

No pyepwmorph, epwshiftr, FWG, PsychroLib or pvlib source code was copied.
OpenEPW implements the documented equations independently; optional scientific
libraries perform array/NetCDF access. Software remains MIT and source data keeps
its separate terms. No downloaded weather fixtures are bundled.

The actual default ACCESS-CM2 stores still declare CC BY-SA 4.0. WCRP's registry
records relaxation to CC BY 4.0 on 2022-06-10. The backend fetches the authoritative
CMIP6_source_id.json, caches its body, and records checksum, retrieval time,
original attributes and effective grant in the signal/manifest. Its default
allowlist is CC BY 4.0, CC BY-SA 4.0 or CC0 1.0; unknown and NC grants fail before
numeric retrieval. The cached registry is an auditable snapshot; remove that
cache file deliberately to refresh it. No update is inferred across models.
