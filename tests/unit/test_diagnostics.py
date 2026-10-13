import logging

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from openepw.api.app import create_app
from openepw.chat.coordinator import OfflineParser
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def _client(tmp_path, **config):
    service = WeatherService(RuntimeConfig(data_root=tmp_path, **config))
    return TestClient(create_app(service, chat_parser=OfflineParser()))


def test_diagnostics_are_off_by_default(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/v1/diagnostics").status_code == 404


def test_debug_log_is_read_from_the_runtime_config(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENEPW_DEBUG_LOG", "true")
    assert RuntimeConfig.load(tmp_path / "missing.toml").debug_log is True
    monkeypatch.delenv("OPENEPW_DEBUG_LOG")
    (tmp_path / "local.toml").write_text("[runtime]\ndebug_log = true\n", encoding="utf-8")
    assert RuntimeConfig.load(tmp_path / "local.toml").debug_log is True
    assert RuntimeConfig.load(tmp_path / "missing.toml").debug_log is False


def test_diagnostics_return_recent_warnings_redacted(tmp_path):
    secret = "nlr-secret-value-123456"
    with _client(tmp_path, debug_log=True, nlr_api_key=secret) as client:
        log = logging.getLogger("openepw.test")
        log.info("routine detail is not kept")
        log.warning("provider said %s for tester@cornell.edu with Bearer abcdefghijklmnop", secret)
        try:
            raise RuntimeError("api_key=zzzzzzzzzzzz failed")
        except RuntimeError:
            log.exception("unhandled")
        body = client.get("/v1/diagnostics").json()
    text = str(body["server_log"])
    assert body["version"] and "server_time" in body
    assert "provider said [redacted] for [email] with Bearer [redacted]" in text
    assert "Traceback" in text and "api_key=[redacted]" in text
    assert secret not in text and "tester@cornell.edu" not in text and "zzzzzzzzzzzz" not in text
    assert "routine detail" not in text
