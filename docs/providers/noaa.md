# NOAA station observations

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
