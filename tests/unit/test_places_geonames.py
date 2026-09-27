"""GeoNames place sets from a synthetic fixture; no network is used."""

import io
import json
import zipfile

import pytest

from openepw.models import OpenEPWError
from openepw.places.geonames import GeoNamesStore
from openepw.places.models import PlaceSetQuery

COUNTRY_INFO = "\n".join([
    "# ISO\tISO3\tISO-Numeric\tfips\tCountry\tCapital",
    "US\tUSA\t840\tUS\tUnited States\tWashington",
    "GE\tGEO\t268\tGG\tGeorgia\tTbilisi",
    "CA\tCAN\t124\tCA\tCanada\tOttawa",
]) + "\n"
ADMIN1 = "US.TX\tTexas\tTexas\t4736286\nUS.GA\tGeorgia\tGeorgia\t4197000\nUS.CA\tCalifornia\tCalifornia\t5332921\n"


def _row(geoname_id, name, lat, lon, code, country, admin1, population):
    return "\t".join([str(geoname_id), name, name, "", str(lat), str(lon), "P", code, country, "",
                      admin1, "", "", "", str(population), "", "0", "America/Chicago", "2026-01-01"])


CITIES = [
    _row(1, "Houston", 29.76, -95.36, "PPL", "US", "TX", 2_300_000),
    _row(2, "Austin", 30.27, -97.74, "PPLA", "US", "TX", 960_000),
    _row(3, "Dallas", 32.78, -96.80, "PPL", "US", "TX", 1_300_000),
    _row(4, "Marfa", 30.31, -104.02, "PPL", "US", "TX", 1_800),
    _row(5, "Sacramento", 38.58, -121.49, "PPLA", "US", "CA", 520_000),
    _row(6, "Atlanta", 33.75, -84.39, "PPLA", "US", "GA", 500_000),
    _row(7, "Tbilisi", 41.69, 44.83, "PPLC", "GE", "04", 1_100_000),
]


def _zip(name, rows):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name.replace(".zip", ".txt"), "\n".join(rows) + "\n")
    return buffer.getvalue()


class FakeHttp:
    def __init__(self):
        self.calls = []
        big = [row for row in CITIES if int(row.split("\t")[14]) > 15000]
        self.files = {
            "countryInfo.txt": COUNTRY_INFO.encode(), "admin1CodesASCII.txt": ADMIN1.encode(),
            "cities15000.zip": _zip("cities15000.zip", big),
            "cities5000.zip": _zip("cities5000.zip", big),
            "cities1000.zip": _zip("cities1000.zip", CITIES),
        }

    def get(self, url, **kwargs):
        name = url.rsplit("/", 1)[-1]
        self.calls.append(name)
        return self.files[name]


def test_downloads_once_with_checksums_and_reuses_cache(tmp_path):
    http = FakeHttp()
    store = GeoNamesStore(tmp_path, http)
    store.query(PlaceSetQuery(kind="city", country="US", admin1="TX", min_population=100_000, limit=5))
    assert sorted(http.calls) == ["admin1CodesASCII.txt", "cities15000.zip", "countryInfo.txt"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert set(manifest["files"]) == {"admin1CodesASCII.txt", "cities15000.zip", "countryInfo.txt"}
    assert all(len(item["sha256"]) == 64 for item in manifest["files"].values())
    again = GeoNamesStore(tmp_path, FakeHttp())
    again.query(PlaceSetQuery(kind="city", country="US", min_population=100_000, limit=5))
    assert again.http.calls == []


def test_tampered_cache_is_rejected(tmp_path):
    GeoNamesStore(tmp_path, FakeHttp()).resolve_region("Texas")
    (tmp_path / "admin1CodesASCII.txt").write_text("US.TX\tNot Texas\tNot Texas\t1\n")
    with pytest.raises(OpenEPWError) as error:
        GeoNamesStore(tmp_path, FakeHttp()).resolve_region("Texas")
    assert error.value.issue.code == "SNAPSHOT_CHECKSUM"


@pytest.mark.parametrize("text, expected", [
    ("Texas", [("US", "TX", "Texas, United States")]),
    ("the United States", [("US", None, "United States")]),
    ("USA", [("US", None, "United States")]),
    ("Georgia", [("GE", None, "Georgia"), ("US", "GA", "Georgia, United States")]),
    ("Atlantis", []),
])
def test_region_names_resolve_with_visible_ambiguity(tmp_path, text, expected):
    matches = GeoNamesStore(tmp_path, FakeHttp()).resolve_region(text)
    assert [(item.country, item.admin1, item.label) for item in matches] == expected


def test_cities_are_ordered_by_population_and_limited(tmp_path):
    result = GeoNamesStore(tmp_path, FakeHttp()).query(
        PlaceSetQuery(kind="city", country="US", admin1="TX", min_population=100_000, limit=2))
    assert [row.name for row in result.rows] == ["Houston", "Dallas"]
    assert result.total_matching == 3 and result.truncated
    assert result.source_file == "cities15000.zip"
    assert "GeoNames" in result.attribution and "CC BY 4.0" in result.attribution


def test_capitals_use_first_level_seats_and_small_thresholds_use_larger_files(tmp_path):
    store = GeoNamesStore(tmp_path, FakeHttp())
    capitals = store.query(PlaceSetQuery(kind="capital", country="US", limit=50))
    assert [row.name for row in capitals.rows] == ["Austin", "Sacramento", "Atlanta"]
    small = store.query(PlaceSetQuery(kind="city", country="US", admin1="TX", min_population=1_000, limit=10))
    assert small.source_file == "cities1000.zip" and "Marfa" in [row.name for row in small.rows]


@pytest.mark.parametrize("fields", [
    {"kind": "city", "country": "US", "min_population": 500, "limit": 10},
    {"kind": "city", "country": "US", "limit": 10},
    {"kind": "city", "country": "US", "min_population": 5000, "limit": 1001},
    {"kind": "city", "country": "USA", "min_population": 5000, "limit": 10},
])
def test_place_set_queries_must_be_fully_specified_and_bounded(fields):
    with pytest.raises(ValueError):
        PlaceSetQuery(**fields)
