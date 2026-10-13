"""NSRDB datasets beyond GOES (2026-10-13 plan): Himawari-7, Meteosat, Meteosat IODC and their
typical years are downloaded like GOES; Himawari-8 (hourly labels at :00) is not."""

import pytest
from pydantic import SecretStr

from openepw.availability.importers.contracts import NSRDB_ADAPTED
from openepw.config import RuntimeConfig
from openepw.models import Location, OpenEPWError, WeatherRequest
from openepw.providers.nsrdb import DATASETS, NSRDBProvider, parse_nsrdb

QUERY = {"outputs": [
    {"name": "himawari", "availableYears": [2016, 2017, 2018, 2019, 2020]},
    {"name": "himawari7", "availableYears": [2011, 2012, 2013, 2014, 2015]},
    {"name": "himawari-tmy", "availableYears": ["tmy", "tmy-2020", "tdy-2020", "tgy-2020"]},
    {"name": "msg-iodc", "availableYears": [2017, 2018, 2019]},
]}


class Http:
    def __init__(self):
        self.config = RuntimeConfig(nlr_api_key=SecretStr("k" * 20), nlr_email=SecretStr("a@b.c"))

    def get_json(self, url, **kwargs):
        return QUERY


def _csv(minute: int, offset_hours: float = 0) -> bytes:
    rows = [f"2015,1,{1 + h // 24},{h % 24},{minute},25,20,80,1008,{max(0, 500 - abs(h % 24 - 4) * 100)},0,0,2,180"
            for h in range(48)]
    head = ("Source,Location ID,Latitude,Longitude,Time Zone,Elevation\n"
            f"NSRDB,647092,1.29,103.86,{offset_hours},12\n"
            "Year,Month,Day,Hour,Minute,Temperature,Dew Point,Relative Humidity,Pressure,GHI,DNI,DHI,Wind Speed,Wind Direction\n")
    return (head + "\n".join(rows)).encode()


def test_named_datasets_are_discovered_and_himawari_8_is_not():
    provider, location = NSRDBProvider(), Location(lat=1.29, lon=103.85)
    def found(dataset, product="historical", years=(2015,)):
        request = WeatherRequest(locations=location, product=product, years=list(years), dataset=dataset)
        return provider.discover(request, location, Http())
    assert [c.source.dataset for c in found("himawari7")] == ["himawari7"]
    assert [c.source.dataset for c in found("msg-iodc", years=(2018,))] == ["msg-iodc"]
    assert found("himawari7", years=(2018,)) == []                       # not a listed year
    assert found("himawari", years=(2018,)) == []                        # labels at :00: unsupported
    [typical] = found("himawari-tmy", product="tmy", years=())
    assert typical.product_id == "tmy-2020"
    assert found(None, years=(2015,)) == []                              # GOES stays the default


def test_hourly_labels_must_be_interval_centres():
    frame, location, _ = parse_nsrdb(_csv(30))
    assert str(frame.index[0]) == "2015-01-01 01:00:00+00:00"             # 00:30 centre -> 01:00 end
    assert location.lat == 1.29
    with pytest.raises(OpenEPWError, match="hourly CSV"):
        parse_nsrdb(_csv(0))


def test_the_catalog_and_the_adapter_agree_on_supported_datasets():
    assert NSRDB_ADAPTED == set(DATASETS)
    assert "himawari" not in DATASETS
