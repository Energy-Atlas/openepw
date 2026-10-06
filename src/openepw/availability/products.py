"""Named weather products and where each is available for the chosen locations.

Each choice names one downloadable product (provider, dataset and, for published files, the
file family). Availability comes from the offline catalog assessment only: a product is
"supported" or "unknown" at a location, excluded products are left out, and nothing is
inferred beyond what the catalog records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..models import DatasetSelection, WeatherRequest, published_variant
from .map_layers import onebuilding_station_name
from .models import WeatherAvailabilityQuery

# Map callouts are drawn for at most this many locations; the options still cover all.
MAX_CALLOUT_LOCATIONS = 25


@dataclass(frozen=True)
class Product:
    id: str
    product: str            # WeatherRequest.product
    provider: str
    dataset: str
    label: str              # the option label: names exactly what is downloaded
    tag: str                # the short map tag
    layer: str              # the catalog map layer that shows its coverage
    detail: str
    variant: str | None = None

    @property
    def actual(self) -> bool:
        return self.product == "historical"

    def selection(self) -> dict:
        return DatasetSelection(provider=self.provider, dataset=self.dataset,
                                variant=self.variant).model_dump(mode="json")


FIXED_PRODUCTS = (
    Product("era5-openmeteo", "historical", "openmeteo", "era5", "ERA5 actual year · Open-Meteo",
            "ERA5 · Open-Meteo", "era5", "25 km reanalysis grid, all EPW weather fields"),
    Product("era5-cds", "historical", "cds", "reanalysis-era5-single-levels",
            "ERA5 actual year · Copernicus CDS", "ERA5 · CDS", "era5",
            "Reanalysis grid from Copernicus; needs CDS terms; no DNI or DHI; requests queue at "
            "Copernicus one month at a time, so several years can take hours"),
    Product("era5land-openmeteo", "historical", "openmeteo", "era5_land",
            "ERA5-Land actual year · Open-Meteo", "ERA5-Land · Open-Meteo", "era5-land",
            "11 km land grid; temperature, humidity and pressure only"),
    Product("era5land-cds", "historical", "cds", "reanalysis-era5-land",
            "ERA5-Land actual year · Copernicus CDS", "ERA5-Land · CDS", "era5-land",
            "Land grid from Copernicus; needs CDS terms; no DNI or DHI; requests queue at Copernicus "
            "one month at a time, so several years can take hours"),
    Product("nsrdb-actual", "historical", "nsrdb", "nsrdb-GOES-aggregated-v4-0-0",
            "NSRDB actual year · GOES v4", "NSRDB actual year", "nsrdb",
            "4 km satellite solar grid, hourly; needs an NLR key"),
    Product("noaa-isd", "historical", "noaa", "ISD global-hourly", "NOAA ISD station observations",
            "NOAA ISD", "noaa", "Nearest reporting station; no solar radiation"),
    Product("nsrdb-tmy", "tmy", "nsrdb", "nsrdb-GOES-tmy-v4-0-0", "NSRDB TMY · latest release",
            "NSRDB TMY", "nsrdb", "4 km satellite typical year; needs an NLR key"),
    Product("pvgis-tmy", "tmy", "pvgis", "PVGIS TMY", "PVGIS TMY 5.3 · SARAH3", "PVGIS TMY", "pvgis",
            "Typical year from the PVGIS point service"),
)
STATION_LAYERS = {"noaa", "onebuilding"}
_ORDER = {product.id: index for index, product in enumerate(FIXED_PRODUCTS)}


def onebuilding_product(variant: str) -> Product:
    tmyx = variant.startswith("TMYx")
    return Product(f"onebuilding:{variant}", "tmyx" if tmyx else "published", "onebuilding",
                   "OneBuilding published EPW", f"OneBuilding {variant}", variant, "onebuilding",
                   "Published EPW file from the nearest listed station", variant)


def product_for(choice_id: str) -> Product | None:
    if choice_id.startswith("onebuilding:"):
        return onebuilding_product(choice_id.split(":", 1)[1])
    return next((product for product in FIXED_PRODUCTS if product.id == choice_id), None)


def _product_of(option) -> Product | None:
    record = option.product
    if record.provider == "onebuilding":
        variant = published_variant(record.native_product_id)
        return onebuilding_product(variant) if variant else None
    return next((product for product in FIXED_PRODUCTS if (product.provider, product.dataset)
                 == (record.provider, record.dataset)), None)


def _unloaded_products(option, request_kind: str) -> list[Product]:
    """The fixed products of a provider whose catalog is not loaded (status stays "unknown")."""
    actual = request_kind == "historical"
    return [product for product in FIXED_PRODUCTS
            if product.provider == option.product.provider and product.actual == actual]


def _station(option) -> dict | None:
    site = option.site
    if site is None or site.lat is None or site.lon is None:
        return None
    name = site.name or onebuilding_station_name(option.product.native_product_id)
    return {"lat": site.lat, "lon": site.lon, "name": name,
            "distance_km": round(option.distance_km, 1) if option.distance_km is not None else None}


def _wanted(product: Product, kind: str | None, provider: str | None) -> bool:
    if provider and product.provider != str(provider).lower():
        return False
    if kind in ("historical", "amy"):
        return product.actual
    if kind == "tmyx":
        return product.provider == "onebuilding" and (product.variant or "").startswith("TMYx")
    if kind in ("tmy", "published"):
        return not product.actual
    return True


def product_offers(service, locations: Any, *, kind: str | None = None, provider: str | None = None,
                   years: list[int] | None = None, today: date | None = None) -> dict:
    """Options for the product choice plus per-location availability for the map."""
    years = list(years or [])
    years_assumed = not years
    if years_assumed:
        years = [(today or date.today()).year - 1]
    assessed: dict[str, dict[int, dict]] = {}     # product id -> occurrence -> best entry
    found: dict[str, Product] = {}
    assess = getattr(service, "assess_availability", None)
    points: list[dict] = []
    catalog_loaded = True
    if assess is not None:
        for request_kind, kind_years in (("historical", years), ("tmy", [])):
            request = WeatherRequest.model_validate({"locations": locations, "product": request_kind,
                                                     "years": kind_years})
            result = assess(WeatherAvailabilityQuery(request=request))
            catalog_loaded &= not any(issue.code == "CATALOG_UNAVAILABLE"
                                      for issue in getattr(result, "issues", ()))
            if not points:
                points = [assessment.requested_location.model_dump(mode="json")
                          for assessment in result.locations]
            for option in sorted(result.options, key=lambda item: item.rank or 10**6):
                status = option.eligibility.status
                if status == "excluded":
                    continue
                # Without a loaded catalog a provider with no bundled contract is a placeholder;
                # its products are offered as unverified instead of being dropped.
                products = (_unloaded_products(option, request_kind) if option.product.dataset == "unloaded"
                            else [product] if (product := _product_of(option)) else [])
                for product in products:
                    if product.actual != (request_kind == "historical"):
                        continue
                    found[product.id] = product
                    best = assessed.setdefault(product.id, {}).get(option.occurrence_index)
                    if best is None or (best["status"] == "unknown" and status == "supported"):
                        entry = {"status": status}
                        if product.layer in STATION_LAYERS and (station := _station(option)):
                            entry["station"] = station
                        assessed[product.id][option.occurrence_index] = entry
    catalogued = bool(assessed)
    products = [product for product in (*FIXED_PRODUCTS, *sorted(
        (item for item in found.values() if item.provider == "onebuilding"), key=lambda item: item.id))
        if (product.id in assessed or not catalogued) and _wanted(product, kind, provider)]
    if not products:                          # a typed type or provider with nothing here
        products = [product for product in FIXED_PRODUCTS
                    if _wanted(product, kind, provider)] or list(FIXED_PRODUCTS)
    count = len(points)
    options = []
    for product in products:
        per_location = assessed.get(product.id, {})
        supported = sum(entry["status"] == "supported" for entry in per_location.values())
        unverified = sum(entry["status"] == "unknown" for entry in per_location.values())
        if not catalogued:
            where = "availability is checked when planning"
        elif count == 1:
            entry = next(iter(per_location.values()), {"status": "unknown"})
            station = entry.get("station")
            where = ("listed in the catalog" if entry["status"] == "supported"
                     else "not verified in the catalog; checked when planning")
            if station:
                where = f"{station['name'] or 'station'}" + (
                    f" · {station['distance_km']:g} km" if station["distance_km"] is not None else "") + (
                    "" if entry["status"] == "supported" else " · not verified")
        else:
            where = ""                                   # counted in the dialog's availability column
        options.append({"id": product.id, "label": product.label,
                        "detail": f"{product.detail} · {where}" if where else product.detail,
                        "group": "actual" if product.actual else "typical",
                        "available": supported, "unverified": unverified, "sites": count,
                        # The WeatherRequest fields that choose exactly this product.
                        "request": {"product": product.product,
                                    "dataset_selections": [product.selection()]}})
    options.sort(key=lambda option: (option["group"] != "actual", _ORDER.get(option["id"], len(_ORDER)),
                                     option["id"]))
    tags = []
    for index, point in enumerate(points[:MAX_CALLOUT_LOCATIONS]):
        entries = []
        for product in products:
            best = assessed.get(product.id, {}).get(index)
            if best:
                entries.append({"option": product.id, "layer": product.layer, "tag": product.tag,
                                "status": best["status"], **({"station": best["station"]}
                                                              if "station" in best else {})})
        tags.append({"index": index, "lat": point["lat"], "lon": point["lon"], "name": point.get("name"),
                     "products": entries})
    return {"options": options, "availability": {
        "years": years, "years_assumed": years_assumed, "locations": tags,
        "omitted_locations": max(0, count - MAX_CALLOUT_LOCATIONS), "catalog_loaded": catalog_loaded}}


def point_availability(service, lat: float, lon: float, years: list[int] | None = None, *,
                       today: date | None = None) -> dict:
    """Every named product at one point: "supported" (listed in the catalog), "unknown"
    (checked when planning) or "none" (not available here), with the station for station products."""
    offers = product_offers(service, {"lat": lat, "lon": lon}, years=years or [], today=today)
    availability = offers["availability"]
    here = availability["locations"][0]["products"] if availability["locations"] else []
    tags = {tag["option"]: tag for tag in here}
    catalogued = bool(availability["locations"])
    rows = []
    for option in offers["options"]:
        tag = tags.get(option["id"])
        row = {"id": option["id"], "label": option["label"], "group": option["group"],
               "status": tag["status"] if tag else "unknown" if not catalogued else "none"}
        if tag and "station" in tag:
            row["station"] = tag["station"]
        rows.append(row)
    listed = {row["id"] for row in rows}
    rows += [{"id": product.id, "label": product.label, "group": "actual" if product.actual else "typical",
              "status": "none"} for product in FIXED_PRODUCTS if product.id not in listed]
    rows.sort(key=lambda row: (row["group"] != "actual", _ORDER.get(row["id"], len(_ORDER)), row["id"]))
    return {"lat": lat, "lon": lon, "years": availability["years"],
            "years_assumed": availability["years_assumed"], "products": rows}
