# NOAA station observations

## MCP Stage 2 availability — 2026-09-24

The local importer preserves the dated 2025-08-30 ISD history and 154,841 sparse
station/year inventory rows, including alphanumeric and zero-padded IDs. A listed
year indicates reports exist, while an unlisted year inside a station operating
span remains unknown. Monthly counts do not prove hourly or variable completeness.
The GHCNh successor is not inferred from this ISD catalog. See the
[Stage 1 findings](../validation/mcp-stage-1/README.md) for evidence and limits.

## v0.1 implementation result — 2026-09-20

The ISD adapter passed a 48-hour request. The endpoint returned no rows for an initial cross-year request; calendar-year splitting recovered the reports. QC flags 0/1/4/5 are accepted and the nearest report within 30 minutes supplies each hourly target. Missing solar and station pressure remain missing; sea-level pressure is not substituted. NOAA announced the ISD service transition to GHCNh: https://www.nesdis.noaa.gov/news/service-location-change-integrated-surface-data-global-hourly . This adapter targets available historical ISD access, not the new GHCNh schema.

## Earlier source/access review

Use public Access Data Service and HTTPS archives for `global-hourly`, not the
separate token-requiring CDO API. The initial USAF/WBAN combination was wrong:
HTTP 200 with `[]` was not success. The station inventory identified Binghamton
as `72515004725`; requesting 2024-01-01 returned 64 records with TMP, DEW, SLP,
WND and quality flags. The annual CSV also responded, but the probe deliberately
stopped at 5 MB and does not certify the entire file.

Parse encoded units/sentinels and QC flags. Resolve competing subhourly reports
with a documented selection rule, never arbitrary last-write-wins. Sea-level
pressure is not station pressure. Derive station pressure only with an explicit
physical method/elevation record or leave it missing. Solar generally needs an
explicit complementary source; do not claim a complete simulation-ready EPW.
[ISD](https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database), [access API](https://www.ncei.noaa.gov/support/access-data-service-api-user-documentation).

The sampled inventory's station records end 2025-08-27. Current NOAA documentation
says GHCNh replaces ISD. Expose historical availability accurately; Stage 2 adds
a GHCNh capability probe before offering current-year observations. Retain
`noaa_isd` as a compatibility provider identifier with separate dataset identities.
[GHCNh](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly).

Preserve NOAA attribution and supplied source/QC metadata; use synthetic fixtures
unless dataset-specific redistribution has been confirmed. No token or rate ceiling
was needed/verified for these endpoints; default one concurrent request and cache.

Status: historical data validated; hourly normalization, solar hybrid, successor
access and full-year completeness remain implementation work.
