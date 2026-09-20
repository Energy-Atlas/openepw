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
