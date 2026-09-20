import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def test_optional_ui_keeps_api_routes_and_auth(tmp_path):
    folder = tmp_path / "dist"
    folder.mkdir()
    (folder / "index.html").write_text("<html>OpenEPW</html>")
    (folder / "app.js").write_text('console.log("app")')
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data", bearer_token="test-only"))
    with TestClient(create_app(service, ui_dir=folder)) as client:
        assert client.get("/ui/").text == "<html>OpenEPW</html>"
        assert client.get("/ui/results").status_code == 200
        assert client.get("/ui/missing.js").status_code == 404
        assert client.get("/v1/nonexistent").status_code == 404
        assert client.get("/v1/jobs").status_code == 401
        assert (
            client.get("/v1/jobs", headers={"Authorization": "Bearer test-only"}).status_code == 200
        )
        assert client.get("/ui/%2e%2e/%2e%2e/secrets.txt").status_code != 200
