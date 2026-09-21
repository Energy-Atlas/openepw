"""Attributed, documented coverage metadata; never point availability."""

from .models import CoverageLayer

_OBSERVED_AT = "2026-09-20T00:00:00+00:00"


def _world_polygon():
    return {
        "type": "Polygon",
        "coordinates": [[[-180, -89.9], [180, -89.9], [180, 89.9], [-180, 89.9], [-180, -89.9]]],
    }


LAYERS = (
    CoverageLayer(
        id="openmeteo-era5",
        provider="openmeteo",
        dataset="era5",
        label="ERA5 via Open-Meteo",
        kind="vector",
        geometry=_world_polygon(),
        products=["historical", "amy"],
        start_year=1940,
        resolution_km=28,
        attribution="Open-Meteo historical API; ERA5 by ECMWF/Copernicus",
        source_url="https://open-meteo.com/en/docs/historical-weather-api",
        limitations=[
            "Documented global extent does not prove requested-year completeness at a point",
            "Hosted Open-Meteo access terms differ from the underlying ERA5 license",
        ],
        observed_at=_OBSERVED_AT,
    ),
    CoverageLayer(
        id="cds-era5",
        provider="cds",
        dataset="reanalysis-era5-single-levels",
        label="ERA5 via Copernicus CDS",
        kind="vector",
        geometry=_world_polygon(),
        products=["historical", "amy"],
        start_year=1940,
        resolution_km=28,
        attribution="Copernicus Climate Change Service",
        source_url="https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels",
        limitations=["Account token and accepted dataset terms are required for retrieval"],
        observed_at=_OBSERVED_AT,
    ),
    CoverageLayer(
        id="pvgis-published",
        provider="pvgis",
        dataset="published-tmy",
        label="PVGIS published TMY",
        kind="unknown",
        products=["tmy", "published"],
        attribution="European Commission Joint Research Centre PVGIS",
        source_url="https://re.jrc.ec.europa.eu/pvg_tools/en/",
        limitations=[
            "Coverage varies by radiation database; no single approved extent is asserted"
        ],
        observed_at=_OBSERVED_AT,
    ),
)


def coverage_layers(provider=None, product=None, year=None):
    result = []
    for layer in LAYERS:
        if provider and layer.provider != provider:
            continue
        if product and product not in layer.products:
            continue
        if year is not None and (
            (layer.start_year is not None and year < layer.start_year)
            or (layer.end_year is not None and year > layer.end_year)
        ):
            continue
        result.append(layer.model_copy(deep=True))
    return result
