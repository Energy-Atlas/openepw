"""Named product choices and per-location availability from the offline catalog."""

from datetime import date
from types import SimpleNamespace

from openepw.chat.products import product_for, product_offers
from openepw.models import Location

ONEBUILDING = "https://climate.onebuilding.org/WMO_Region_4/USA_NY_Ithaca.Tompkins.Rgnl.AP.725155_{}.zip"


def _option(index, rank, provider, dataset, status, native=None, site=None, distance=None):
    return SimpleNamespace(occurrence_index=index, rank=rank, distance_km=distance, site=site,
                           product=SimpleNamespace(provider=provider, dataset=dataset, native_product_id=native),
                           eligibility=SimpleNamespace(status=status))


class Catalog:
    def __init__(self):
        self.queries = []

    def assess_availability(self, query):
        request = query.request
        self.queries.append((request.product, request.years))
        points = request.locations if isinstance(request.locations, list) else [request.locations]
        airport = SimpleNamespace(name="ITHACA TOMPKINS REGIONAL AIRPORT", lat=42.483, lon=-76.467)
        if request.product == "historical":
            options = [_option(0, 1, "openmeteo", "era5", "supported"),
                       _option(0, 2, "noaa", "ISD global-hourly", "supported", site=airport, distance=5.21),
                       _option(0, 3, "noaa", "ISD global-hourly", "supported",
                               site=SimpleNamespace(name="ITHACA 13 E", lat=42.44, lon=-76.246), distance=21),
                       _option(0, 7, "nsrdb", "nsrdb-GOES-aggregated-v4-0-0", "unknown"),
                       _option(0, 9, "cds", "reanalysis-era5-land", "excluded"),
                       _option(0, 14, "onebuilding", "OneBuilding published EPW", "excluded",
                               native=ONEBUILDING.format("TMYx"))]
            options += [_option(1, 1, "openmeteo", "era5", "supported")] if len(points) > 1 else []
        else:
            site = SimpleNamespace(name=None, lat=42.483, lon=-76.467)
            options = [_option(0, 1, "onebuilding", "OneBuilding published EPW", "supported",
                               native=ONEBUILDING.format(label), site=site, distance=5.2)
                       for label in ("TMYx", "TMYx.2009-2023")]
            options += [_option(0, 21, "nsrdb", "nsrdb-GOES-tmy-v4-0-0", "unknown"),
                        _option(0, 30, "openmeteo", "era5", "excluded")]
        return SimpleNamespace(options=options, locations=[
            SimpleNamespace(requested_location=Location.model_validate(point)) for point in points])


ITHACA = {"lat": 42.444, "lon": -76.5019, "name": "Ithaca, New York"}


def test_each_option_names_one_product_with_its_availability_here():
    catalog = Catalog()
    offers = product_offers(catalog, ITHACA, {}, today=date(2026, 9, 27))
    assert catalog.queries == [("historical", [2025]), ("tmy", [])]    # no years yet: last full year
    options = {option["id"]: option for option in offers["options"]}
    assert list(options) == ["era5-openmeteo", "nsrdb-actual", "noaa-isd", "nsrdb-tmy",
                             "onebuilding:TMYx", "onebuilding:TMYx.2009-2023"]
    assert options["noaa-isd"]["label"] == "NOAA ISD station observations"
    assert options["noaa-isd"]["detail"].endswith("ITHACA TOMPKINS REGIONAL AIRPORT · 5.2 km")
    assert options["nsrdb-actual"]["detail"].endswith("not verified in the catalog; checked when planning")
    assert options["onebuilding:TMYx.2009-2023"]["label"] == "OneBuilding TMYx.2009-2023"
    assert not any(" or " in option["label"] or "Other" in option["label"] for option in offers["options"])
    assert product_for("onebuilding:TMYx.2009-2023").selection() == {
        "provider": "onebuilding", "dataset": "OneBuilding published EPW", "product_id": None,
        "variant": "TMYx.2009-2023"}
    assert product_for("nsrdb-actual").selection()["dataset"] == "nsrdb-GOES-aggregated-v4-0-0"


def test_map_availability_lists_one_tag_per_product_with_the_nearest_station():
    offers = product_offers(Catalog(), ITHACA, {"years": [2018]})
    availability = offers["availability"]
    assert availability["years"] == [2018] and availability["years_assumed"] is False
    [place] = availability["locations"]
    tags = {tag["option"]: tag for tag in place["products"]}
    assert tags["noaa-isd"]["station"] == {"lat": 42.483, "lon": -76.467,
                                           "name": "ITHACA TOMPKINS REGIONAL AIRPORT", "distance_km": 5.2}
    assert tags["nsrdb-actual"]["status"] == "unknown" and "station" not in tags["nsrdb-actual"]
    assert tags["onebuilding:TMYx"]["station"]["name"] == "Ithaca Tompkins Rgnl AP"
    assert {tags[key]["layer"] for key in ("onebuilding:TMYx", "onebuilding:TMYx.2009-2023")} == {"onebuilding"}
    assert "era5land-cds" not in tags                                   # excluded here: no tag


def test_a_typed_type_or_provider_narrows_the_choices_and_lists_count_places():
    tmyx = product_offers(Catalog(), ITHACA, {"product": "tmyx"})
    assert [option["id"] for option in tmyx["options"]] == ["onebuilding:TMYx", "onebuilding:TMYx.2009-2023"]
    nsrdb = product_offers(Catalog(), ITHACA, {"product": "historical", "provider": "NSRDB"})
    assert [option["id"] for option in nsrdb["options"]] == ["nsrdb-actual"]
    two = product_offers(Catalog(), [ITHACA, {"lat": 40.0, "lon": -75.0}], {"product": "historical"})
    era5 = next(option for option in two["options"] if option["id"] == "era5-openmeteo")
    assert era5["detail"].endswith("listed at 2 of 2 places")


def test_without_a_catalog_every_named_product_is_offered_for_checking_when_planning():
    offers = product_offers(object(), ITHACA, {})
    assert len(offers["options"]) == 8
    assert all(option["detail"].endswith("availability is checked when planning") for option in offers["options"])
    assert offers["availability"]["locations"] == []
