# ERA5 and ERA5-Land via CDS

The current CDS API root is `https://cds.climate.copernicus.eu/api`, with personal
access tokens rather than legacy UID:key assumptions. Dataset terms must be
accepted manually in the account. [Official setup](https://cds.climate.copernicus.eu/how-to-api).

Public ERA5 collection and retrieval-process schemas returned 200. A one-hour,
one-variable, small-area POST returned 401 `authentication required`. This proves
the access gate, not successful data retrieval. No account was created or terms
accepted. Stage 2 can build and fixture-test the adapter, but live acceptance needs
the account token and accepted terms. The Open-Meteo path already supplies ERA5
without those credentials and must retain its different access-path metadata.

ERA5 provides global hourly data from 1940; the delivered regular atmospheric grid
is 0.25°, distinct from the model's roughly 31 km native scale. ERA5-Land starts
1950 with 0.1° delivery, roughly 9 km native land scale. Use dataset-specific
variables; direct CDS Land capabilities are not inferred from Open-Meteo Land.
Convert accumulated radiation J/m² into interval Wh/m², with dataset-specific
accumulation resets; derive RH and wind from appropriate components.
[ERA5 catalog](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels), [Land catalog](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land).

The live ERA5 collection declares CC BY 4.0. Capture the actual license record
per dataset/retrieval. `cdsapi` is Apache-2.0 and belongs in an optional `cds` extra;
NetCDF/xarray must not become core EPW dependencies. Queue limits vary; do not
invent a fixed quota. Cache and serialize bounded submissions.

Status: schema and auth gate validated; direct downloaded data untested.
