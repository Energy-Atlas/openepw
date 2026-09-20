# NSRDB / NLR

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
