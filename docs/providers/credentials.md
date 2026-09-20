# Credentials for implementation testing

## v0.1 implementation result — 2026-09-20

The owner supplied the three required local values and accepted CDS terms. Final adapter checks passed NSRDB actual/native TMY and CDS ERA5/Land. Use RuntimeConfig.load(env_file=".env") or CLI --env-file .env explicitly; environment variables also work. No further credential or account action is required for the tested v0.1 scope.

## Earlier source/access review

Owner setup before Stage 2, updated 2026-09-20. Credentials do not constitute
Stage 2 approval; the plan review gate remains separate.

## NSRDB / NLR

Request a developer API key through the [NLR signup](https://developer.nlr.gov/signup/).
Provide locally:

- `OPENEPW_NLR_API_KEY`: the issued developer key.
- `OPENEPW_NLR_EMAIL`: an active email address you authorize us to submit with
  NSRDB requests; using the signup address is the simplest choice.

The [current API](https://developer.nlr.gov/docs/solar/nsrdb/nsrdb-GOES-aggregated-v4-0-0-download/)
requires key and email. Full name, affiliation and reason are optional, so they
are not needed for initial testing. Use direct single-point/year CSV downloads;
do not subscribe to mailing lists or initiate email-delivery jobs by default.
No account password is needed.

## Copernicus CDS: direct ERA5 and ERA5-Land

Create/sign into your CDS account and obtain its personal access token using the
[official setup instructions](https://cds.climate.copernicus.eu/how-to-api).
Provide `OPENEPW_CDS_KEY` locally. This is the current personal token, not the
legacy UID:key format. The API URL is already known; no login password is needed.

In your own account, accept the terms shown on each intended dataset's download
form. Acceptance is dataset-specific and cannot be replaced by supplying a token:

- [ERA5 hourly single levels](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels?tab=download).
- [ERA5-Land hourly](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=download).

A pre-existing local `.cdsapirc` is an alternative for cdsapi; do not copy its
contents into git or messages. Confirm which dataset terms you have accepted.

## Sources that do not need credentials for the selected tests

Stage 1 already accessed Open-Meteo's free noncommercial endpoints, PVGIS,
OneBuilding, NOAA Access Data Service/HTTPS, Pangeo's public CMIP6 catalog/Zarr
metadata and OEDI's hourly archive without personal credentials. No NOAA CDO
token, Google Cloud key, AWS key or NASA Earthdata account is required for those
specific access paths. Further dataset-specific restrictions remain possible.

Open-Meteo's free service is limited to noncommercial use. For commercial endpoint
testing, optionally provide `OPENEPW_OPENMETEO_API_KEY` from an existing suitable
subscription. Do not purchase a subscription just for these research tests.
[Open-Meteo terms](https://open-meteo.com/en/terms).

## Local handoff

Copy the repository's `.env.example` to `.env` **only if `.env` does not already
exist**, then fill the three required values:

```dotenv
OPENEPW_NLR_API_KEY=your-issued-key
OPENEPW_NLR_EMAIL=your-active-email
OPENEPW_CDS_KEY=your-personal-access-token
```

`.env` is gitignored. Alternatively set these environment variables in the
environment running the tests. A `.env` file is not automatically loaded by the
Stage 1 scripts; those scripts intentionally remain credential-free. During
implementation, explicitly load the local values into the test process, without
printing them or modifying the credential-free Stage 1 evidence scripts.

Tell the implementer only that local setup is ready and which CDS terms were
accepted. Keys/email must be removed from request logs, provider-echoed inputs,
error bodies, manifests and committed fixtures. Supplying these credentials
unblocks live authentication checks, not a guarantee that all downloads will pass.
OneBuilding redistribution uncertainty is independent of account credentials.
