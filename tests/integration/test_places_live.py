import pytest

from openepw.config import RuntimeConfig
from openepw.places.models import PlaceSetQuery
from openepw.service import WeatherService


@pytest.mark.live
def test_geonames_place_set_downloads_once_and_lists_texas_cities(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    query = PlaceSetQuery(kind="city", country="US", admin1="TX", min_population=500_000, limit=5)
    preview = service.place_set(query)
    assert preview.rows and all(row.population >= 500_000 for row in preview.rows)
    assert [row.population for row in preview.rows] == sorted((row.population for row in preview.rows), reverse=True)
    assert any("GeoNames" in item for item in preview.attribution)
    assert (tmp_path / "places" / "geonames" / "manifest.json").exists()
