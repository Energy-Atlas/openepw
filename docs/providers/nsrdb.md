# NSRDB / NLR

## MCP Stage 2 availability — 2026-09-24

Ithaca and Phoenix point-catalog evidence is scoped to those probe locations.
Actual aggregate years and published TMY/TDY/TGY identifiers remain separate.
An unprobed location is not promoted to a verified catalog point; wider source
documentation and adapter restrictions remain distinct. Runtime key/email access
is reported separately from scientific eligibility. A parallel Stage 1 follow-up
will be reviewed before any new generation replaces this accepted baseline.

## v0.1 implementation result — 2026-09-20

Production credentials passed both aggregate v4 actual-year retrieval (2024, 8,784 hours) and native published TMY retrieval (8,760 hours). Published TMY/TDY/TGY IDs are selected from the live catalog. Hour-center actual-year timestamps become interval ends; native TMY fixed timezone and mixed original source years are retained. Only the specific NLR S3 redirect is followed without forwarding credentials. Other spatial footprints/subhourly products remain deferred.

Interactive discovery makes one NSRDB catalog attempt. If NLR returns HTTP 429,
discovery reports `RATE_LIMITED` while retaining other providers' candidates instead
of waiting through NLR's long `Retry-After` period. Download requests retain the
normal configured retry policy.

## Earlier source/access review

Use `developer.nlr.gov`, not a hardcoded legacy NREL hostname. The legacy hostname
failed DNS on this machine. `nsrdb_data_query.json` with the public `DEMO_KEY`
returned four products for Ithaca, including exact years, intervals and download
links. Aggregated V4 spans 1998–2025; CONUS and full-disc V4 span 2018–2025 in this
response. TMY/TDY/TGY names are separate published products, not calendar years.
[Current endpoints](https://developer.nlr.gov/docs/solar/nsrdb/).

No key produced `API_KEY_MISSING` (403). A single-point, single-year CSV request
with DEMO_KEY but no email returned a specific valid-email requirement (400).
Therefore full data retrieval is **not yet validated**. Do not invent an email or
submit email-delivery jobs. Stage 2 needs a user-configured NLR key and email for
the direct CSV path. Generic key limits and product limits can differ; honor
response rate headers and the [download guide](https://developer.nlr.gov/docs/solar/nsrdb/guide/).

Important variables: air temperature, dew point/RH, pressure, GHI/DNI/DHI, wind.
Confirm each product's supported attribute names/units. Resample subhourly solar
by energy-preserving integration; aggregate wind direction as vectors. Keep
native SiteID, dataset version, original interval and UTC/local-time setting.

Data are advertised as publicly available without charge; that is not an MIT
license for data. Preserve NLR/product attribution and terms; inspect downloaded
metadata before redistribution. Use HTTP directly, no NSRDB processing SDK.

Status: current discovery validated; credential-dependent CSV retrieval pending.
