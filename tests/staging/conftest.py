"""Staging tests: signed in as the tester account against a deployed testing service (ADR 0006).

Skipped unless the tester settings are present, in the environment or the git-ignored ``.env``
that `openepw accounts tester-secret` writes:

    OPENEPW_STAGING_URL             e.g. https://openepw-staging.onrender.com
    OPENEPW_STAGING_TESTER_NAME
    OPENEPW_STAGING_TESTER_PASSWORD

Default runs are free: stub sessions (eval stub providers) and real sessions that stop before a
retrieval. ``OPENEPW_STAGING_REAL=1`` adds one small real retrieval (Open-Meteo, one point, one
year); ``OPENEPW_STAGING_AGENT=1`` adds agent-mode turns on the real model, capped by the
tester's spend limits (about $1 per run). The password is read here and sent only to staging;
it is never printed or put in a URL.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")


@dataclass(frozen=True)
class Staging:
    url: str
    name: str
    password: str = ""

    def __repr__(self) -> str:                    # failures and logs never show the password
        return f"Staging(url={self.url!r}, name={self.name!r})"


def _settings() -> Staging | None:
    values: dict[str, str] = {}
    env_file = Path(os.environ.get("OPENEPW_STAGING_ENV_FILE", ".env"))
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    values.update({key: value for key, value in os.environ.items() if key.startswith("OPENEPW_STAGING_")})
    url, name = values.get("OPENEPW_STAGING_URL"), values.get("OPENEPW_STAGING_TESTER_NAME")
    password = values.get("OPENEPW_STAGING_TESTER_PASSWORD")
    if not (url and name and password):
        return None
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise pytest.UsageError("OPENEPW_STAGING_URL must be https (or a local http://127.0.0.1 server)")
    return Staging(url.rstrip("/"), name, password)


def flag(name: str) -> bool:
    return os.environ.get(name, "") in ("1", "true", "yes")


def pytest_collection_modifyitems(config, items):
    settings = _settings()
    for item in items:
        if "tests/staging" not in item.nodeid.replace("\\", "/"):
            continue
        item.add_marker(pytest.mark.staging)
        if settings is None:
            item.add_marker(pytest.mark.skip(reason="Set OPENEPW_STAGING_URL and the tester name and password"))
        elif item.get_closest_marker("real") and not flag("OPENEPW_STAGING_REAL"):
            item.add_marker(pytest.mark.skip(reason="Set OPENEPW_STAGING_REAL=1 for a real retrieval"))
        elif item.get_closest_marker("agent") and not flag("OPENEPW_STAGING_AGENT"):
            item.add_marker(pytest.mark.skip(reason="Set OPENEPW_STAGING_AGENT=1 for real-model turns"))


@pytest.fixture(scope="session")
def staging() -> Staging:
    settings = _settings()
    assert settings is not None
    return settings


@pytest.fixture(scope="session")
def cookies(staging: Staging) -> httpx.Cookies:
    """One sign-in for the whole run, through the same endpoint as the landing page."""
    with httpx.Client(base_url=staging.url, timeout=60, follow_redirects=False) as client:
        health = client.get("/health")
        assert health.status_code == 200, "staging is not answering /health"
        signed = client.post("/auth/login", json={"email": staging.name, "password": staging.password})
        assert signed.status_code == 200, f"tester sign-in refused ({signed.status_code}): {signed.text[:200]}"
        return client.cookies


@pytest.fixture
def api(staging: Staging, cookies: httpx.Cookies):
    with httpx.Client(base_url=staging.url, cookies=cookies, timeout=60) as client:
        yield client


class Chat:
    """One /v2 agent session driven over HTTP, as the web chat drives it."""

    def __init__(self, client: httpx.Client, stub: dict | None = None):
        self.client = client
        response = client.post("/v2/agent/sessions", json={"stub": stub} if stub is not None else None)
        assert response.status_code == 201, response.text[:300]
        self.id = response.json()["id"]
        self.state = self.idle()

    def idle(self, timeout: float = 120.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            state = self.client.get(f"/v2/agent/sessions/{self.id}").json()
            if not state["busy"]:
                return state
            assert time.monotonic() < deadline, "the session stayed busy"
            time.sleep(0.5)

    def send(self, body: dict) -> dict:
        response = self.client.post(f"/v2/agent/sessions/{self.id}/inputs", json=body)
        assert response.status_code == 202, response.text[:300]
        self.state = self.idle()
        return self.state

    def say(self, text: str) -> dict:
        return self.send({"type": "text", "text": text})

    def answer(self, **fields) -> dict:
        form = self.state["form"]
        assert form is not None, "no form is open"
        return self.send({"type": "answer", "answer": {"interaction_id": form["id"],
                                                       "revision": form["revision"], **fields}})

    @property
    def gate(self) -> str | None:
        return (self.state.get("form") or {}).get("gate")

    def events(self) -> list[dict]:
        return self.client.get(f"/v2/agent/sessions/{self.id}/events",
                               params={"poll": 1, "after": 0}).json()["events"]

    def wait_jobs(self, timeout: float = 600.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            state = self.idle()
            if state["job_ids"] and set(state["job_ids"]) <= set(state["finished_job_ids"]):
                return state
            assert time.monotonic() < deadline, "the jobs did not finish"
            time.sleep(2)


@pytest.fixture
def chat(api):
    return lambda stub=None: Chat(api, stub)
