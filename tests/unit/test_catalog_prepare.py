"""The catalog's index and map are computed once per generation, saved beside it, served as
stored gzip with an ETag, and prepared by the install step before the server starts."""

import gzip
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from test_catalog_index import QUERIES, _bundle, _dump

from openepw.api.app import create_app
from openepw.availability.catalog_index import StoreCatalogIndex
from openepw.availability.evaluate import evaluate
from openepw.availability.store import CatalogStore, CatalogView
from openepw.chat.coordinator import OfflineParser
from openepw.config import RuntimeConfig
from openepw.deploy import prepare_catalog
from openepw.service import WeatherService


def _service(tmp_path):
    store = CatalogStore(tmp_path / "catalog")
    snapshot = store.stage(_bundle())
    store.activate(snapshot.generation_id)
    return WeatherService(RuntimeConfig(data_root=tmp_path), catalog_store=store), snapshot.generation_id


def test_the_index_is_saved_once_and_read_back_with_the_same_answers(tmp_path, monkeypatch):
    service, generation = _service(tmp_path)
    store = service.catalog_store
    built = store.active()
    saved = store.derived(generation) / "index.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["generation_id"] == generation
    monkeypatch.setattr(StoreCatalogIndex, "_build_state", lambda self: pytest.fail("rebuilt"))
    read = StoreCatalogIndex(store.database, generation, store.derived(generation))
    for query in QUERIES:
        assert _dump(evaluate(query, CatalogView(built.snapshot, index=read))) == _dump(evaluate(query, built))


@pytest.mark.parametrize("damage", ["{not json", '{"format": 1, "generation_id": "another"}', '{"format": 99}'])
def test_a_damaged_or_foreign_index_file_is_rebuilt(tmp_path, damage):
    service, generation = _service(tmp_path)
    path = service.catalog_store.derived(generation) / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(damage, encoding="utf-8")
    index = StoreCatalogIndex(service.catalog_store.database, generation, path.parent)
    assert index.providers() and json.loads(path.read_text(encoding="utf-8"))["generation_id"] == generation


def test_the_map_is_served_gzipped_with_an_etag_and_revalidated(tmp_path):
    service, generation = _service(tmp_path)
    with TestClient(create_app(service, chat_parser=OfflineParser())) as client:
        assert list(service.catalog_store.derived(generation).glob("map-*.json.gz"))     # warmed at start
        response = client.get("/v1/catalog/map")
        assert response.headers["content-encoding"] == "gzip" and response.headers["cache-control"] == "no-cache"
        assert response.json() == json.loads(json.dumps(service.catalog_map()))
        etag = response.headers["etag"]
        assert client.get("/v1/catalog/map", headers={"If-None-Match": etag}).status_code == 304
        plain = client.get("/v1/catalog/map", headers={"Accept-Encoding": "identity"})
        assert "content-encoding" not in plain.headers and plain.json() == response.json()
        assert plain.headers["etag"] == etag
        scopes = client.get("/v1/catalog/scopes", headers={"Accept-Encoding": "gzip"})
        assert scopes.status_code == 200
        if len(scopes.content) >= 1000:                  # every larger response is compressed
            assert scopes.headers.get("content-encoding") == "gzip"


def test_the_stored_map_is_reused_across_restarts(tmp_path, monkeypatch):
    service, generation = _service(tmp_path)
    first = service.catalog_map_payload()
    again = WeatherService(RuntimeConfig(data_root=tmp_path), catalog_store=CatalogStore(tmp_path / "catalog"))
    monkeypatch.setattr(WeatherService, "catalog_map", lambda self: pytest.fail("rebuilt"))
    assert again.catalog_map_payload() == first
    assert gzip.decompress(first[2]) == first[1]


def test_the_install_step_prepares_the_catalog_and_drops_old_generations(tmp_path, capsys):
    service, generation = _service(tmp_path)
    stale = service.catalog_store.derived("an-old-generation")
    stale.mkdir(parents=True)
    prepare_catalog(tmp_path)
    assert "Catalog prepared" in capsys.readouterr().out
    folder = service.catalog_store.derived(generation)
    assert (folder / "index.json").is_file() and list(folder.glob("map-*.json.gz"))
    assert not stale.exists()
    prepare_catalog(tmp_path / "nothing-here")               # no catalog: nothing to prepare, no error
    assert "Catalog prepared" in capsys.readouterr().out
