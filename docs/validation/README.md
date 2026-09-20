# Stage 1 evidence

Observed 2026-09-20 from Windows, Python 3.14 standard library. These are small
feasibility experiments, not production provider implementations or CI tests.

| Evidence | Contents |
| --- | --- |
| [Initial probes](2026-09-20-probes.json) | All six targets plus geocoding and Open-Meteo daily climate |
| [Follow-ups](2026-09-20-followup-probes.json) | Corrected catalog/station requests, bounded NOAA archive, OEDI locations, FWG page |
| [Downloads](2026-09-20-download-probes.json) | OneBuilding EPW, NSRDB CSV email gate and legacy hostname failure |
| [Research](2026-09-20-research.json) | License hashes/revisions, paired CMIP6 metadata, CDS 401 |
| [Hourly future sample](2026-09-20-future-archive.json) | ZIP64 range requests and a CRC-checked 8,760-row future EPW |

Reproduce selected HTTP requests from the repository root:

```powershell
python scripts/probe_providers.py --only openmeteo_era5 pvgis_epw noaa_isd_corrected onebuilding_epw
python scripts/probe_research.py
python scripts/probe_future_archive.py
```

Provider reports default to ignored `.local/probe-report.json`; the other two
research scripts refresh their dated tracked evidence. Review a new run before
committing it. Raw third-party responses/code remain under ignored `.local/`.
Do not commit them by force. Reports contain no real API secrets; `DEMO_KEY` is
the provider's public example key. Error bodies are inspected before committing.

Limits: provider bodies capped at 5 MB, research documents at 2 MB, hourly archive
probe at 15 MB with strict Range handling. NSRDB data and authenticated CDS were
not downloaded. CMIP6 Zarr metadata was read, not the large numeric chunks;
multi-variable generation and dependency runtime remain Stage 2 acceptance work.
Malformed initial OneBuilding paths and NOAA station ID are retained as evidence,
not described as provider failures. An initial CMIP6 URL join added a second slash;
normalizing the catalog URI fixed the 404 before the final research report.

ReadTheDocs returned 403 to urllib; the EnergyPlus dictionary was inspected via
the web reader instead. FWG/OEDI had the reverse behavior: the web reader failed
but direct bounded HTTP succeeded. An HTTP success alone is not a completeness test.
