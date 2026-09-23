"""Explicit research manifest. No crawling or location/year Cartesian products."""

from urllib.parse import urlencode

from .collector import Request

LOCATIONS = {
    "ithaca": (42.44, -76.50),
    "phoenix": (33.45, -112.07),
    "london": (51.507, -0.128),
    "sydney": (-33.869, 151.209),
}
VARIABLES = ("tas", "tasmin", "tasmax", "hurs", "ps", "sfcWind", "rsds")


def manifest():
    rows = [
        (
            "openmeteo-doc",
            "openmeteo",
            "https://open-meteo.com/en/docs/historical-weather-api",
            "documentation",
            "Document ERA5/Land coverage, time bounds, variables and grid adjustments",
        ),
        (
            "pvgis-doc",
            "pvgis",
            "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis/using-pvgis-5/api-non-interactive-service_en",
            "documentation",
            "Find v5_3 coverage, source periods and TMY metadata semantics",
        ),
        (
            "onebuilding-root",
            "onebuilding",
            "https://climate.onebuilding.org/",
            "documentation",
            "Locate published country and station catalogs without crawling",
        ),
        (
            "onebuilding-sources",
            "onebuilding",
            "https://climate.onebuilding.org/sources/default.html",
            "documentation",
            "Distinguish TMYx reference periods and upstream variable sources",
        ),
        (
            "onebuilding-us",
            "onebuilding",
            "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/index.html",
            "inventory",
            "Inspect US station/product catalog structure",
        ),
        (
            "noaa-doc",
            "noaa",
            "https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database",
            "documentation",
            "Document station record meaning and ISD transition",
        ),
        (
            "noaa-history",
            "noaa",
            "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv",
            "inventory",
            "Index station identities, coordinates and operating ranges once",
        ),
        (
            "noaa-inventory",
            "noaa",
            "https://www.ncei.noaa.gov/pub/data/noaa/isd-inventory.csv",
            "inventory",
            "Determine station-year/month counts without downloading station weather",
        ),
        (
            "nsrdb-doc",
            "nsrdb",
            "https://developer.nlr.gov/docs/solar/nsrdb/",
            "documentation",
            "Separate supported GOES aggregate/TMY products from broader upstream offerings",
        ),
        (
            "cds-era5",
            "cds",
            "https://cds.climate.copernicus.eu/api/catalogue/v1/collections/reanalysis-era5-single-levels",
            "metadata",
            "Inspect ERA5 spatial/temporal extent and metadata license",
        ),
        (
            "cds-land",
            "cds",
            "https://cds.climate.copernicus.eu/api/catalogue/v1/collections/reanalysis-era5-land",
            "metadata",
            "Inspect ERA5-Land spatial/temporal extent and metadata license",
        ),
        (
            "cds-era5-process",
            "cds",
            "https://cds.climate.copernicus.eu/api/retrieve/v1/processes/reanalysis-era5-single-levels",
            "metadata",
            "Inspect allowed ERA5 years and variables without submitting a retrieval",
        ),
        (
            "cds-land-process",
            "cds",
            "https://cds.climate.copernicus.eu/api/retrieve/v1/processes/reanalysis-era5-land",
            "metadata",
            "Inspect allowed Land years and variables without submitting a retrieval",
        ),
        (
            "cmip6-doc",
            "cmip6",
            "https://pangeo-data.github.io/pangeo-cmip6-cloud/",
            "documentation",
            "Document cloud catalog scope and metadata limitations",
        ),
        (
            "cmip6-license",
            "cmip6",
            "https://raw.githubusercontent.com/WCRP-CMIP/CMIP6_CVs/main/CMIP6_source_id.json",
            "metadata",
            "Identify model-specific license records without assuming a universal grant",
        ),
        (
            "oedi-doc",
            "oedi",
            "https://data.openei.org/submissions/5974",
            "documentation",
            "Document WRF scenarios/windows, sparse delivered sites and source caveats",
        ),
        (
            "oedi-sites",
            "oedi",
            "https://data.openei.org/files/5974/PUMA%20information%20%281%29.csv",
            "inventory",
            "Index published PUMA identifiers, coordinates and elevations once",
        ),
    ]
    requests = [Request(*row) for row in rows]
    requests.append(
        Request(
            "cmip6-catalog",
            "cmip6",
            "https://storage.googleapis.com/cmip6/pangeo-cmip6.csv",
            "inventory",
            "Compute coherent seven-variable historical/SSP intersections locally",
            limit=100_000_000,
        )
    )
    for scenario in ("45", "85"):
        requests.append(
            Request(
                f"oedi-{scenario}-tail",
                "oedi",
                f"https://data.openei.org/files/5974/RCP{scenario[0]}.{scenario[1]}_v1.1.zip",
                "metadata",
                "Read ZIP directory locator only, never weather members",
                headers={"Range": "bytes=-65536"},
                limit=65536,
                archive=f"rcp{scenario}",
            )
        )
    for name in ("ithaca", "phoenix"):
        lat, lon = LOCATIONS[name]
        query = urlencode({"api_key": "DEMO_KEY", "wkt": f"POINT({lon} {lat})"})
        requests.append(
            Request(
                f"nsrdb-{name}",
                "nsrdb",
                "https://developer.nlr.gov/api/solar/nsrdb_data_query.json?" + query,
                "probe",
                f"Resolve supported product/year catalog at {name}; no weather download",
            )
        )
    return {r.id: r for r in requests}


PROVIDERS = {
    "openmeteo": {
        "products": "ERA5; ERA5-Land",
        "spatial_kind": "grid",
        "temporal_kind": "actual_year",
        "adapter_boundary": "Land excludes wind/solar in current adapter; source cell resolved on retrieval",
    },
    "pvgis": {
        "products": "PVGIS TMY v5_3",
        "spatial_kind": "grid",
        "temporal_kind": "tmy_reference_period",
        "adapter_boundary": "Published TMY only; coverage/source composition requires version-specific evidence",
    },
    "onebuilding": {
        "products": "Published EPW / TMYx",
        "spatial_kind": "sites",
        "temporal_kind": "tmy_reference_period",
        "adapter_boundary": "Explicit product or country/name catalog; no global nearest-station index",
    },
    "noaa": {
        "products": "ISD global-hourly",
        "spatial_kind": "stations",
        "temporal_kind": "station_operating_interval",
        "adapter_boundary": "ISD only; missing solar/station pressure; GHCNh not connected",
    },
    "nsrdb": {
        "products": "GOES aggregate v4; GOES TMY v4",
        "spatial_kind": "grid",
        "temporal_kind": "actual_year_or_published_product",
        "adapter_boundary": "Only hourly aggregate and published v4 products; runtime key/email required",
    },
    "cds": {
        "products": "ERA5 single levels; ERA5-Land",
        "spatial_kind": "grid",
        "temporal_kind": "actual_year",
        "adapter_boundary": "Direct adapter lacks DNI/DHI; token/terms required for weather retrieval",
    },
    "cmip6": {
        "products": "Pangeo CMIP6 monthly Amon",
        "spatial_kind": "model_grid",
        "temporal_kind": "climate_window",
        "adapter_boundary": "Seven coherent variables; licenses and actual time coordinates checked separately",
    },
    "oedi": {
        "products": "WRF/CCSM4 EPW trajectories v1.1",
        "spatial_kind": "sites",
        "temporal_kind": "climate_window",
        "adapter_boundary": "RCP4.5/8.5 only; 2045–2054 and 2085–2094; current resolver distance cap 150 km",
    },
}
