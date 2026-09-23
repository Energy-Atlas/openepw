import pytest
from pydantic import ValidationError

from openepw.config import RuntimeConfig
from openepw.generation.cmip6 import CMIP6Backend
from openepw.models import FetchTask, Location, OpenEPWError, SourceRef, WeatherPlan, WeatherRequest
from openepw.service import WeatherService


@pytest.mark.parametrize("key", ["../escape", "C:/outside", "/tmp/outside"])
def test_fetch_cache_key_cannot_escape_storage(key):
    with pytest.raises(ValidationError):
        FetchTask(
            id="safe", source=SourceRef(provider="p", dataset="d"), parameters={}, cache_key=key
        )


def test_empty_plan_is_not_reported_as_success(tmp_path):
    s = WeatherService(RuntimeConfig(data_root=tmp_path))
    with pytest.raises(OpenEPWError):
        s.execute(
            WeatherPlan(request=WeatherRequest(locations=Location(lat=0, lon=0), years=[2024]))
        )


def test_cmip_source_cannot_be_arbitrary_url(tmp_path):
    from openepw.models import FutureRequest

    s = WeatherService(RuntimeConfig(data_root=tmp_path))
    r = FutureRequest(
        baseline="fake", reference_period=(1985, 2014), target_year=2050, climate_scenario="ssp245"
    )
    pairs = [
        {
            "model": "M",
            "member": "r1",
            "rows": [{"variable_id": "tas", "zstore": "http://127.0.0.1/private"}],
        }
    ]
    with pytest.raises(OpenEPWError) as exc:
        CMIP6Backend(s.http).signals(pairs, r, Location(lat=0, lon=0))
    assert exc.value.issue.code == "INVALID_REQUEST"


def test_cds_polling_metadata_is_never_cached(tmp_path):
    class Http:
        config = RuntimeConfig(data_root=tmp_path)

        def get_json(self, *a, **kw):
            return {"href": "https://object-store.example/file?secret=temporary"}

        def get(self, *a, **kw):
            return b'{"href":"signed-secret"}'

    class Provider:
        def fetch(self, t, h):
            return h.get_json("https://cds.climate.copernicus.eu/api/jobs/1/results")

    s = WeatherService(Http.config, http=Http())
    t = FetchTask(
        id="test",
        cache_key="a" * 64,
        source=SourceRef(provider="cds", dataset="test"),
        parameters={},
    )
    s._cached_fetch(Provider(), t)
    assert not list(tmp_path.rglob("*.bin"))


@pytest.mark.parametrize("name", ["D:payload", "weather:stream", "CON", "nul.epw", "com1.txt"])
def test_artifact_write_rejects_windows_special_names(tmp_path, name):
    from openepw.artifacts.store import ArtifactStore

    with pytest.raises(OpenEPWError):
        ArtifactStore(tmp_path).write("a" * 32, name, b"test", "test")


def test_artifact_write_with_long_semantic_name_uses_short_temporary_path(tmp_path):
    from openepw.artifacts.store import ArtifactStore

    store = ArtifactStore(tmp_path)
    name = "a" * 90 + ".epw"
    ref = store.write("b" * 32, name, b"weather", "weather")

    assert store.resolve(ref.id)[1].name == name


def test_http_logging_redacts_runtime_credentials(tmp_path, caplog):
    import logging

    import httpx

    from openepw.providers.http import HttpClient

    config = RuntimeConfig(data_root=tmp_path, nlr_api_key="logging-secret-key")
    http = HttpClient(
        config, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ok"))
    )
    with caplog.at_level(logging.INFO, logger="httpx"):
        http.get("https://example.org/data", params={"api_key": "logging-secret-key"})
    assert "logging-secret-key" not in caplog.text
