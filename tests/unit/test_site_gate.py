"""A site password in front of the whole app, remembered by a signed cookie."""

import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.api.site_gate import COOKIE, sign
from openepw.config import RuntimeConfig
from openepw.service import WeatherService


def _client(tmp_path, **config):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>OpenEPW</title>", encoding="utf-8")
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data", site_password="correct horse",
                                           web_root=web, **config), providers=[StationProvider()])
    return TestClient(create_app(service, remote=True), follow_redirects=False)


def test_everything_but_health_and_login_needs_the_password(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/health").status_code == 200                     # Render's health check
        page = client.get("/", headers={"accept": "text/html"})
        assert page.status_code == 303 and page.headers["location"] == "/login?next=/"
        assert client.get("/v1/catalog/map").status_code == 401
        assert client.post("/v1/chat/sessions").status_code == 401
        login = client.get("/login")
        assert login.status_code == 200 and 'type="password"' in login.text


def test_the_right_password_is_remembered_for_thirty_days(tmp_path):
    with _client(tmp_path) as client:
        wrong = client.post("/login", data={"password": "nope", "next": "/"})
        assert wrong.status_code == 401 and COOKIE not in wrong.cookies
        right = client.post("/login", data={"password": "correct horse", "next": "/?x=1"},
                            headers={"x-forwarded-proto": "https"})
        assert right.status_code == 303 and right.headers["location"] == "/?x=1"
        cookie = right.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie
        assert "max-age=2592000" in cookie
        value = right.cookies[COOKIE]
        client.cookies.clear()
        client.cookies.set(COOKIE, value)
        assert client.get("/").status_code == 200                             # the built UI
        assert client.post("/v1/chat/sessions").status_code == 201            # and the API
        client.cookies.clear()
        client.cookies.set(COOKIE, value[:-2] + ("00" if not value.endswith("00") else "11"))
        assert client.post("/v1/chat/sessions").status_code == 401            # tampered


def test_expired_cookies_and_changed_passwords_are_refused(tmp_path):
    with _client(tmp_path) as client:
        client.cookies.set(COOKIE, sign("correct horse", int(time.time()) - 5))
        assert client.post("/v1/chat/sessions").status_code == 401
        client.cookies.clear()
        client.cookies.set(COOKIE, sign("an older password", int(time.time()) + 3600))
        assert client.post("/v1/chat/sessions").status_code == 401


def test_login_only_returns_to_this_site_and_throttles_guessing(tmp_path):
    with _client(tmp_path) as client:
        away = client.post("/login", data={"password": "correct horse", "next": "//evil.example/x"})
        assert away.headers["location"] == "/"
        for _ in range(10):
            assert client.post("/login", data={"password": "guess", "next": "/"}).status_code == 401
        assert client.post("/login", data={"password": "correct horse", "next": "/"}).status_code == 429


def test_remote_mode_accepts_a_site_password_instead_of_a_bearer_token(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data"), providers=[StationProvider()])
    with pytest.raises(ValueError):
        create_app(service, remote=True)                                     # neither: refused
