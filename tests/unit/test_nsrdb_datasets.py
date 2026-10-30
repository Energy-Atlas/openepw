"""NSRDB datasets beyond GOES (2026-10-13 plan): Himawari-7, Meteosat, Meteosat IODC and their
typical years are downloaded like GOES. Himawari-8 (hourly samples at :00) is downloaded with its
irradiance re-binned to EPW hours (2026-10-27 follow-ups, item 2)."""

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


def test_named_datasets_are_discovered():
    provider, location = NSRDBProvider(), Location(lat=1.29, lon=103.85)
    def found(dataset, product="historical", years=(2015,)):
        request = WeatherRequest(locations=location, product=product, years=list(years), dataset=dataset)
        return provider.discover(request, location, Http())
    assert [c.source.dataset for c in found("himawari7")] == ["himawari7"]
    assert [c.source.dataset for c in found("msg-iodc", years=(2018,))] == ["msg-iodc"]
    assert found("himawari7", years=(2018,)) == []                       # not a listed year
    [himawari8] = found("himawari", years=(2018,))
    assert "re-binned" in himawari8.warnings[0]
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
    assert "himawari" in DATASETS


def test_himawari_8_samples_keep_their_instants_and_irradiance_is_re_binned():
    import pandas as pd

    from openepw.providers.nsrdb import rebin_instants

    frame, _, _ = parse_nsrdb(_csv(0), instants=True)
    assert str(frame.index[1]) == "2015-01-01 01:00:00+00:00"            # the 01:00 sample ends hour 1
    with pytest.raises(OpenEPWError, match="hourly CSV"):
        parse_nsrdb(_csv(30), instants=True)
    rebinned = rebin_instants(frame)
    hour = pd.Timestamp("2015-01-01 04:00", tz="UTC")
    previous = hour - pd.Timedelta(hours=1)
    assert rebinned.loc[hour, "ghi"] == 0.5 * (frame.loc[previous, "ghi"] + frame.loc[hour, "ghi"])
    assert rebinned.loc[hour, "dry_bulb"] == frame.loc[hour, "dry_bulb"]          # instants unchanged
    assert pd.isna(rebinned["ghi"].iloc[0])                              # no starting sample: never filled
    # Totals are kept: the re-binned sum differs from the samples' sum only by half the end samples.
    inner = rebinned["ghi"].iloc[1:].sum()
    assert inner == pytest.approx(frame["ghi"].sum() - 0.5 * (frame["ghi"].iloc[0] + frame["ghi"].iloc[-1]))


def test_installed_himawari_7_mask_also_gates_himawari_8(tmp_path):
    import json

    from scripts.mcp_availability_map.sync_gates import sync

    folder = tmp_path / "nsrdb" / "himawari7" / "2015"
    folder.mkdir(parents=True)
    entry = {"product_id": "himawari7", "selector_kind": "actual_year", "selector": "2015",
             "gates": ["nsrdb:himawari7", "nsrdb:himawari-tmy"], "mask_sha256": "x"}
    (folder / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    assert sync(tmp_path) and not sync(tmp_path)                         # once, then nothing to do
    written = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["entries"][0]
    assert written["gates"] == ["nsrdb:himawari7", "nsrdb:himawari-tmy", "nsrdb:himawari"]
    assert written["mask_sha256"] == "x"
