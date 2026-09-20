import pytest

from openepw.config import RuntimeConfig
from openepw.epw import read_epw
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


@pytest.mark.live
@pytest.mark.parametrize(
    "provider,location,options,rows",
    [
        (
            "openmeteo",
            Location(lat=42.44, lon=-76.5, standard_offset_minutes=-300),
            {"years": [2024]},
            8784,
        ),
        ("pvgis", Location(lat=45, lon=8), {"product": "tmy"}, 8760),
        (
            "onebuilding",
            Location(lat=42.44, lon=-76.5),
            {
                "product": "tmyx",
                "product_id": "WMO_Region_4_North_and_Central_America/USA_United_States_of_America/NY_New_York/USA_NY_Ithaca.Tompkins.Rgnl.AP.725155_TMYx.2011-2025.zip",
            },
            8760,
        ),
    ],
)
def test_live_provider(provider, location, options, rows):
    config = RuntimeConfig.load(env_file=".env", data_root=".local/live-acceptance")
    service = WeatherService(config)
    bundle = service.fetch(WeatherRequest(locations=location, providers=[provider], **options))
    assert bundle.weather, [(i.code, i.message) for i in bundle.issues if i.severity == "error"]
    frame = read_epw(config.data_root / bundle.weather[0].path).data
    assert len(frame) == rows
    assert frame.dry_bulb.notna().all()


@pytest.mark.live
@pytest.mark.parametrize(
    "provider,options,rows",
    [
        ("nsrdb", {"years": [2024]}, 8784),
        ("noaa", {"start": "2024-01-01", "end": "2024-01-02", "product_id": "72515004725"}, 48),
    ],
)
def test_live_observations(provider, options, rows):
    config = RuntimeConfig.load(env_file=".env", data_root=".local/live-acceptance")
    service = WeatherService(config)
    bundle = service.fetch(
        WeatherRequest(locations=Location(lat=42.44, lon=-76.5), providers=[provider], **options)
    )
    assert bundle.weather, [(i.code, i.message) for i in bundle.issues if i.severity == "error"]
    frame = read_epw(config.data_root / bundle.weather[0].path).data
    assert len(frame) == rows
    assert frame.dry_bulb.notna().sum() > rows * 0.9


@pytest.mark.live
def test_nsrdb_published_tmy():
    config = RuntimeConfig.load(env_file=".env", data_root=".local/live-acceptance")
    service = WeatherService(config)
    bundle = service.fetch(
        WeatherRequest(
            locations=Location(lat=42.44, lon=-76.5),
            providers=["nsrdb"],
            product="tmy",
            product_id="tmy-2024",
        )
    )
    assert len(bundle.weather) == 1, [(i.code, i.message) for i in bundle.issues]
    data = read_epw(config.data_root / bundle.weather[0].path)
    assert len(data.data) == 8760
    assert len(set(data.source_years)) > 1
    assert data.location.standard_offset_minutes == -300
