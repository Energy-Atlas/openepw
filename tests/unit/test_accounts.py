"""Cornell email accounts in front of the hosted app: sign-up by link, password, sessions."""

import json
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from test_batch import StationProvider

from openepw.api.accounts import COOKIE, AccountStore, check_password, hash_password
from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService

PUBLIC = "https://openepw.test"
GOOD = "a long enough passphrase"


class Mailbox:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, text):
        self.sent.append({"to": to, "subject": subject, "text": text})

    def token(self, to):
        mail = [m for m in self.sent if m["to"] == to][-1]
        return re.search(re.escape(PUBLIC) + r"/password#t=([A-Za-z0-9_-]+)", mail["text"]).group(1)


def _client(tmp_path, mailbox, **config):
    web = tmp_path / "web"
    web.mkdir(exist_ok=True)
    (web / "index.html").write_text("<!doctype html><title>OpenEPW</title>", encoding="utf-8")
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data", web_root=web, public_url=PUBLIC,
                                           **config), providers=[StationProvider()])
    return TestClient(create_app(service, remote=True, mailer=mailbox), follow_redirects=False)


def _account(client, mailbox, email="ada@cornell.edu", password=GOOD):
    assert client.post("/signup", data={"email": email}).status_code == 200
    done = client.post("/password", data={"token": mailbox.token(email.lower()), "password": password,
                                          "confirm": password})
    assert done.status_code == 303
    return done


def test_everything_but_health_and_the_account_pages_needs_a_session(tmp_path):
    with _client(tmp_path, Mailbox()) as client:
        assert client.get("/health").status_code == 200
        page = client.get("/")
        assert page.status_code == 303 and page.headers["location"] == "/login?next=/"
        assert client.get("/v1/catalog/map").status_code == 401
        assert client.post("/v1/chat/sessions").status_code == 401
        for path in ("/login", "/signup", "/reset", "/password"):
            assert client.get(path).status_code == 200, path
        assert 'type="password"' in client.get("/login").text


def test_only_cornell_addresses_can_sign_up_and_the_password_is_set_from_the_link(tmp_path):
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        refused = client.post("/signup", data={"email": "ada@gmail.com"})
        assert refused.status_code == 400 and "cornell.edu" in refused.text
        assert client.post("/signup", data={"email": "ada@med.cornell.edu"}).status_code == 400
        assert mailbox.sent == []
        sent = client.post("/signup", data={"email": " Ada@Cornell.EDU "})
        assert sent.status_code == 200 and "Check your email" in sent.text
        assert [m["to"] for m in mailbox.sent] == ["ada@cornell.edu"]
        assert "#t=" in mailbox.sent[0]["text"] and "?t=" not in mailbox.sent[0]["text"]  # never logged
        # Nothing works until the password is chosen on the linked page.
        assert client.post("/login", data={"email": "ada@cornell.edu", "password": GOOD}).status_code == 401
        token = mailbox.token("ada@cornell.edu")
        short = client.post("/password", data={"token": token, "password": "short", "confirm": "short"})
        assert short.status_code == 400 and "12" in short.text
        done = client.post("/password", data={"token": token, "password": GOOD, "confirm": GOOD},
                           headers={"x-forwarded-proto": "https"})
        assert done.status_code == 303 and done.headers["location"] == "/"
        cookie = done.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=lax" in cookie and "secure" in cookie
        assert "max-age=2592000" in cookie
        client.cookies.clear()
        client.cookies.set(COOKIE, done.cookies[COOKIE])                       # test client is plain http
        assert client.get("/").status_code == 200
        assert client.post("/v1/chat/sessions").status_code == 201
        again = client.post("/password", data={"token": token, "password": GOOD, "confirm": GOOD})
        assert again.status_code == 400                                          # single use


def test_signing_in_and_out(tmp_path):
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        _account(client, mailbox)
        client.cookies.clear()
        wrong = client.post("/login", data={"email": "ada@cornell.edu", "password": "not the password"})
        assert wrong.status_code == 401 and COOKIE not in wrong.cookies
        right = client.post("/login", data={"email": "ADA@cornell.edu", "password": GOOD, "next": "/?x=1"})
        assert right.status_code == 303 and right.headers["location"] == "/?x=1"
        value = right.cookies[COOKIE]
        assert client.post("/v1/chat/sessions").status_code == 201
        away = client.post("/login", data={"email": "ada@cornell.edu", "password": GOOD,
                                           "next": "//evil.example/x"})
        assert away.headers["location"] == "/"
        client.cookies.clear()
        client.cookies.set(COOKIE, value)
        assert client.get("/logout").status_code == 303
        client.cookies.clear()
        client.cookies.set(COOKIE, value)
        assert client.post("/v1/chat/sessions").status_code == 401                # ended on the server


def test_sign_up_and_reset_do_not_reveal_accounts(tmp_path):
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        _account(client, mailbox)
        before = len(mailbox.sent)
        repeat = client.post("/signup", data={"email": "ada@cornell.edu"})
        stranger = client.post("/signup", data={"email": "grace@cornell.edu"})
        assert repeat.status_code == stranger.status_code == 200 and repeat.text == stranger.text
        existing = mailbox.sent[before]
        assert existing["to"] == "ada@cornell.edu" and "already has an account" in existing["text"]
        unknown = client.post("/reset", data={"email": "nobody@cornell.edu"})
        known = client.post("/reset", data={"email": "ada@cornell.edu"})
        assert unknown.status_code == known.status_code == 200 and unknown.text == known.text
        assert not any(m["to"] == "nobody@cornell.edu" for m in mailbox.sent)


def test_a_reset_changes_the_password_and_ends_other_sessions(tmp_path):
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        old_session = _account(client, mailbox).cookies[COOKIE]
        client.cookies.clear()
        assert client.post("/reset", data={"email": "ada@cornell.edu"}).status_code == 200
        new = "another long passphrase"
        assert client.post("/password", data={"token": mailbox.token("ada@cornell.edu"), "password": new,
                                              "confirm": "different confirmation"}).status_code == 400
        done = client.post("/password", data={"token": mailbox.token("ada@cornell.edu"), "password": new,
                                              "confirm": new})
        assert done.status_code == 303
        client.cookies.clear()
        client.cookies.set(COOKIE, old_session)
        assert client.post("/v1/chat/sessions").status_code == 401
        client.cookies.clear()
        assert client.post("/login", data={"email": "ada@cornell.edu", "password": GOOD}).status_code == 401
        assert client.post("/login", data={"email": "ada@cornell.edu", "password": new}).status_code == 303


def test_guessing_and_mail_floods_are_throttled(tmp_path):
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        _account(client, mailbox)
        client.cookies.clear()
        for _ in range(10):
            client.post("/login", data={"email": "ada@cornell.edu", "password": "a wrong guess"})
        blocked = client.post("/login", data={"email": "ada@cornell.edu", "password": GOOD})
        assert blocked.status_code == 429
        before = len(mailbox.sent)
        for _ in range(5):
            assert client.post("/reset", data={"email": "ada@cornell.edu"}).status_code == 200
        assert len(mailbox.sent) - before == 2          # three per address per hour, sign-up included


def test_expired_links_and_disabled_accounts_are_refused(tmp_path):
    store = AccountStore(tmp_path / "accounts")
    user = store.create_pending("ada@cornell.edu")
    token = store.issue(user, "setup", ttl=-1)
    assert store.redeem(token) is None
    good = store.issue(user, "setup", ttl=3600)
    assert store.redeem(good) == (user, "setup")
    store.set_password(user, GOOD)
    session = store.open_session(user)
    assert store.session_user(session) == user
    store.set_disabled("ada@cornell.edu", True)
    assert store.session_user(session) is None
    assert store.sign_in("ada@cornell.edu", GOOD) is None
    store.set_disabled("ada@cornell.edu", False)
    assert store.sign_in("ada@cornell.edu", GOOD) == user


def test_passwords_are_salted_scrypt_hashes():
    first, second = hash_password(GOOD), hash_password(GOOD)
    assert first != second and first.startswith("scrypt$") and GOOD not in first
    assert check_password(GOOD, first) and not check_password(GOOD + "!", first)
    assert not check_password(GOOD, "not a hash")


def test_bearer_scripts_keep_working_and_remote_mode_needs_a_way_in(tmp_path, monkeypatch):
    with _client(tmp_path, Mailbox(), bearer_token="script-token") as client:
        assert client.post("/v1/chat/sessions").status_code == 401
        assert client.post("/v1/chat/sessions",
                           headers={"authorization": "Bearer script-token"}).status_code == 201
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "d2"), providers=[StationProvider()])
    with pytest.raises(ValueError, match="OPENEPW_RESEND_API_KEY"):
        create_app(service, remote=True)
    dev = WeatherService(RuntimeConfig(data_root=tmp_path / "d3", accounts_dev_mail=True),
                         providers=[StationProvider()])
    with pytest.raises(ValueError, match="development"):
        create_app(dev, remote=True)                                            # links never printed on a server
    local = TestClient(create_app(dev), follow_redirects=False)
    with local:
        assert local.get("/v1/catalog/map").status_code == 401                  # accounts also guard local use
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://openepw-staging.onrender.com")
    assert RuntimeConfig.load(path="missing.toml").public_url == "https://openepw-staging.onrender.com"


def test_accounts_cli_lists_and_disables(tmp_path, capsys):
    from openepw.cli.main import main

    store = AccountStore(tmp_path / "accounts")
    user = store.create_pending("ada@cornell.edu")
    store.set_password(user, GOOD)
    assert main(["--data-root", str(tmp_path), "accounts", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["accounts"][0]["email"] == "ada@cornell.edu" and listed["accounts"][0]["verified"]
    assert "password_hash" not in json.dumps(listed)
    assert main(["--data-root", str(tmp_path), "accounts", "disable", "ada@cornell.edu"]) == 0
    capsys.readouterr()
    assert store.sign_in("ada@cornell.edu", GOOD) is None
    assert main(["--data-root", str(tmp_path), "accounts", "disable", "nobody@cornell.edu"]) == 2
