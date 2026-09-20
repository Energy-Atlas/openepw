import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")
import importlib.util
import json
from pathlib import Path

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def test_documentation_catalog_matches_public_functions_and_tools():
    spec = importlib.util.spec_from_file_location("catalog", "scripts/export_api_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert json.loads(Path("ui/public/api-catalog.json").read_text()) == module.catalog()


def test_rest_routes_declare_success_and_error_schemas(tmp_path):
    app = create_app(WeatherService(RuntimeConfig(data_root=tmp_path)))
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            responses = operation["responses"]
            if path != "/v1/artifacts/{artifact_id}":
                success = responses.get("200", responses.get("201", responses.get("202")))
                assert success["content"]["application/json"]["schema"], (path, method)
            assert "400" in responses and "401" in responses
    app.state.runner.close()
