# NSRDB / NLR

## Himawari-8 — 2026-10-27

- **Downloaded, hourly only** (owner decisions Q1, Q2). Its hourly rows are instantaneous samples
  at :00: each equals the 10-minute file's :00 sample, and the solar zenith angle is the label
  instant's (H1, Singapore 2018).
- **EPW hours:** instantaneous variables are the hour-end values; GHI, DNI and DHI are the mean of
  the samples at the hour's start and end. Against 10-minute hour means: annual GHI +0.10%,
  hourly RMSE 9.45% of mean daylight GHI (ADR 0002 amendment).
- **Live check (H4):** Sapporo 2018 through the service, 8,760 rows, no missing GHI, solar-noon
  offset 0.05 h.
- **Coverage:** the Himawari-7 mask gates it; NLR documents 2016–2020 and every probe inside the
  mask lists those years. See the [record](../validation/availability-followups-2026-10-27/README.md).

## Years per coverage mask — 2026-10-13

- **Edge probes.** Ten more data-query probes at grid edges list, for every dataset, the same
  years and files as the five earlier probes:
  - Honolulu, Recife, Juneau, Cape Town, Oslo, Dakar, Auckland, Sapporo and Almaty;
  - Buenos Aires, just outside the GOES mask, lists only GOES full disc.
- **Earliest years.** Downloads at four edges hold full data with no fill values: GOES 1998 at
  Juneau and Honolulu, Meteosat 2005 at Oslo, Himawari-7 2011 at Auckland.
- **The rule (owner decision D4).** Where the probes agree and NLR's dataset page lists nothing
  more, that list applies throughout the dataset's mask.
- **Documentation lag.** NLR's GOES TMY page omits the -2025 files that every probe lists.
- **New upstream products.** NSRDB Polar (2013–2023) and Polar TMY appear at Oslo and are
  catalogued as upstream products the adapter does not download.
- **A quality note.** Meteosat 2005 wind speed at Oslo never exceeds 1.3 m/s, which looks
  implausible. This is a data-quality observation, not an availability one.
- **The record.** See the [record](../validation/availability-gaps-2026-10-13/README.md).

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
