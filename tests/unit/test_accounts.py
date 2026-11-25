"""Cornell email accounts in front of the hosted app: sign-up by link, password, sessions."""

import json
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")                # the agent chat routes
from fastapi import Request
from fastapi.testclient import TestClient
from test_batch import StationProvider

from openepw.api.accounts import (
    COOKIE,
    AccountStore,
    check_password,
    hash_password,
    new_tester_secret,
)
from openepw.api.accounts import tester_settings as read_tester  # not collected as a test
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


def test_visitors_get_the_landing_page_but_not_the_api(tmp_path):
    with _client(tmp_path, Mailbox()) as client:
        assert client.get("/health").status_code == 200
        page = client.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"   # the landing page
        assert client.get("/auth/session").json() == {"accounts": True, "signed_in": False, "email": None,
                                                      "domains": ["cornell.edu"]}
        assert client.get("/docs").status_code == 303 and client.get("/openapi.json").status_code == 303
        assert client.get("/v1/catalog/map").status_code == 401
        assert client.post("/v2/agent/sessions").status_code == 401
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
        assert client.post("/v2/agent/sessions").status_code == 201
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
        assert client.post("/v2/agent/sessions").status_code == 201
        away = client.post("/login", data={"email": "ada@cornell.edu", "password": GOOD,
                                           "next": "//evil.example/x"})
        assert away.headers["location"] == "/"
        client.cookies.clear()
        client.cookies.set(COOKIE, value)
        assert client.get("/logout").status_code == 303
        client.cookies.clear()
        client.cookies.set(COOKIE, value)
        assert client.post("/v2/agent/sessions").status_code == 401                # ended on the server


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
        assert client.post("/v2/agent/sessions").status_code == 401
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
        assert client.post("/v2/agent/sessions").status_code == 401
        assert client.post("/v2/agent/sessions",
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


def test_the_landing_window_signs_in_and_out_with_json(tmp_path):
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        refused = client.post("/auth/signup", json={"email": "ada@gmail.com"})
        assert refused.status_code == 400 and "@cornell.edu" in refused.json()["message"]
        sent = client.post("/auth/signup", json={"email": "ada@cornell.edu"})
        assert sent.status_code == 200 and sent.json()["ok"] and "link" in sent.json()["message"]
        assert client.post("/password", data={"token": mailbox.token("ada@cornell.edu"), "password": GOOD,
                                              "confirm": GOOD}).status_code == 303
        client.cookies.clear()
        assert client.post("/auth/login", json={"email": "ada@cornell.edu", "password": "wrong guess"}
                           ).status_code == 401
        assert client.post("/auth/login", data={"email": "ada@cornell.edu", "password": GOOD}
                           ).status_code == 401                                 # forms are not accepted here
        signed = client.post("/auth/login", json={"email": "Ada@cornell.edu", "password": GOOD})
        assert signed.status_code == 200 and COOKIE in signed.cookies
        assert client.get("/auth/session").json()["email"] == "ada@cornell.edu"
        assert client.post("/v2/agent/sessions").status_code == 201
        assert client.post("/auth/reset", json={"email": "nobody@cornell.edu"}).status_code == 200
        assert client.post("/auth/logout").status_code == 200
        assert client.get("/auth/session").json()["signed_in"] is False
        assert client.post("/v2/agent/sessions").status_code == 401


def test_without_the_built_ui_visitors_go_to_the_sign_in_page(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data", public_url=PUBLIC),
                             providers=[StationProvider()])
    with TestClient(create_app(service, remote=True, mailer=Mailbox()), follow_redirects=False) as client:
        page = client.get("/")
        assert page.status_code == 303 and page.headers["location"] == "/login?next=/"


class Refusing:
    def send(self, to, subject, text):
        from openepw.api.accounts import MailError

        raise MailError("Resend refused the message: HTTP 403 You can only send testing emails to your own address")


def _log_lines():
    import logging

    lines = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logging.getLogger("openepw.accounts").addHandler(Keep())
    return lines


def test_resend_refusals_are_explained_in_the_window_and_the_log(tmp_path):
    lines = _log_lines()
    with _client(tmp_path, Refusing()) as client:
        refused = client.post("/auth/signup", json={"email": "ada@cornell.edu"})
        assert refused.status_code == 503 and "not answering" in refused.json()["message"]
    assert any("a***@cornell.edu" in line and "HTTP 403" in line and "own address" in line for line in lines)
    assert not any("ada@cornell.edu" in line for line in lines)                  # addresses are masked


def test_sent_and_throttled_mail_is_logged(tmp_path):
    lines = _log_lines()
    mailbox = Mailbox()
    with _client(tmp_path, mailbox) as client:
        for _ in range(4):
            client.post("/auth/signup", json={"email": "ada@cornell.edu"})
    assert sum(line.startswith("sent to a***@cornell.edu") for line in lines) == 3
    assert any("hourly email limit" in line for line in lines)


def test_resend_errors_carry_resends_reason(monkeypatch):
    import io
    import urllib.error

    from openepw.api.accounts import MailError, ResendMailer

    def refuse(request, timeout):
        assert request.get_header("Authorization") == "Bearer re_test"
        raise urllib.error.HTTPError(request.full_url, 422, "Unprocessable", {},
                                     io.BytesIO(b'{"message": "Invalid `from` field."}'))
    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(MailError, match=r"HTTP 422 Invalid `from` field\."):
        ResendMailer("re_test", '"OpenEPW <onboarding@resend.dev>"').send("ada@cornell.edu", "s", "t")


def test_the_test_mail_command_reports_resends_answer(tmp_path, monkeypatch, capsys):
    from openepw.api.accounts import MailError, ResendMailer
    from openepw.cli.main import main

    monkeypatch.setenv("OPENEPW_RESEND_API_KEY", "re_test")
    monkeypatch.setenv("OPENEPW_MAIL_FROM", "OpenEPW <onboarding@resend.dev>")
    monkeypatch.setattr(ResendMailer, "send", lambda self, to, subject, text: "msg-1")
    assert main(["--data-root", str(tmp_path), "accounts", "test-mail", "ada@cornell.edu"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["sent"] and out["id"] == "msg-1" and "re_test" not in json.dumps(out)

    def refuse(self, to, subject, text):
        raise MailError("Resend refused the message: HTTP 403 domain is not verified")
    monkeypatch.setattr(ResendMailer, "send", refuse)
    assert main(["--data-root", str(tmp_path), "accounts", "test-mail", "ada@cornell.edu"]) == 2
    printed = capsys.readouterr().out
    assert "domain is not verified" in printed and "onboarding@resend.dev" in printed and "re_test" not in printed


def test_refused_sends_do_not_use_up_the_hourly_limit(tmp_path):
    class Flaky(Mailbox):
        def __init__(self):
            super().__init__()
            self.refuse = True

        def send(self, to, subject, text):
            if self.refuse:
                from openepw.api.accounts import MailError

                raise MailError("Resend refused the message: HTTP 403 test sender")
            super().send(to, subject, text)

    mailbox = Flaky()
    with _client(tmp_path, mailbox) as client:
        for _ in range(3):                                          # e.g. before the sender was fixed
            assert client.post("/auth/signup", json={"email": "ada@cornell.edu"}).status_code == 503
        mailbox.refuse = False
        assert client.post("/auth/signup", json={"email": "ada@cornell.edu"}).status_code == 200
        assert [m["to"] for m in mailbox.sent] == ["ada@cornell.edu"]


# -- the tester account (testing deployments only) ---------------------------------------

TESTER_PASSWORD = "a random tester secret of some length"


def _tester_client(tmp_path, mailbox, *, debug_log=True, password=TESTER_PASSWORD, name="tester"):
    service = WeatherService(RuntimeConfig(data_root=tmp_path / "data", public_url=PUBLIC, debug_log=debug_log,
                                           tester_name=name, tester_password_hash=hash_password(password)),
                             providers=[StationProvider()])
    app = create_app(service, remote=True, mailer=mailbox)

    @app.get("/whoami")
    def whoami(request: Request):
        return {"tester": getattr(request.state, "tester_name", None)}
    return TestClient(app, follow_redirects=False)


def test_the_tester_signs_in_by_name_and_is_marked(tmp_path):
    with _tester_client(tmp_path, Mailbox()) as client:
        assert client.post("/auth/login", json={"email": "tester", "password": "wrong"}).status_code == 401
        assert client.post("/auth/login", json={"email": "Tester", "password": TESTER_PASSWORD}).status_code == 200
        assert client.get("/whoami").json() == {"tester": "tester"}
        assert client.get("/auth/session").json()["email"] == "tester"


def test_a_real_account_is_not_marked_as_the_tester(tmp_path):
    mailbox = Mailbox()
    with _tester_client(tmp_path, mailbox) as client:
        _account(client, mailbox)
        assert client.get("/whoami").json() == {"tester": None}


def test_the_tester_cannot_sign_up_or_reset_by_email(tmp_path):
    mailbox = Mailbox()
    with _tester_client(tmp_path, mailbox) as client:
        assert client.post("/auth/signup", json={"email": "tester"}).status_code == 400
        assert client.post("/auth/reset", json={"email": "tester"}).status_code == 200
        assert mailbox.sent == []


def test_no_tester_outside_a_testing_deployment(tmp_path):
    with _tester_client(tmp_path, Mailbox(), debug_log=False) as client:
        assert client.post("/auth/login", json={"email": "tester", "password": TESTER_PASSWORD}).status_code == 401


def test_a_new_secret_ends_the_tester_sessions_and_removing_it_disables_the_tester(tmp_path):
    with _tester_client(tmp_path, Mailbox()) as client:
        assert client.post("/auth/login", json={"email": "tester", "password": TESTER_PASSWORD}).status_code == 200
        cookie = client.cookies.get(COOKIE)
    with _tester_client(tmp_path, Mailbox(), password="the next tester secret") as client:
        client.cookies.set(COOKIE, cookie)
        assert client.get("/whoami").status_code == 303           # the old session ended: sign in again
        assert client.post("/auth/login", json={"email": "tester",
                                                "password": "the next tester secret"}).status_code == 200
    store = AccountStore(tmp_path / "data" / "accounts")
    assert store.sync_tester(None, None) is None
    assert [row["disabled"] for row in store.accounts() if row["email"] == "tester"] == [True]


def test_tester_settings_are_checked(tmp_path):
    good = hash_password(TESTER_PASSWORD)
    assert read_tester(None, None, True) is None
    assert read_tester("Tester", good, True) == ("tester", good)
    assert read_tester("tester", good, False) is None
    for name, digest in (("tester", None), ("a@b.c", good), ("tester", "plain")):
        with pytest.raises(ValueError):
            read_tester(name, digest, True)


def test_the_tester_secret_goes_to_the_env_file_and_only_its_hash_is_shown(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nOPENEPW_STAGING_TESTER_PASSWORD=old\n", encoding="utf-8")
    result = new_tester_secret("tester", env)
    written = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines())
    assert written["OTHER"] == "1" and written["OPENEPW_STAGING_TESTER_NAME"] == "tester"
    password = written["OPENEPW_STAGING_TESTER_PASSWORD"]
    assert password != "old" and len(password) >= 40 and password not in json.dumps(result)
    assert check_password(password, result["set_on_the_testing_server"]["OPENEPW_TESTER_PASSWORD_HASH"])
    with pytest.raises(ValueError):
        new_tester_secret("tester", tmp_path / "secrets.txt")
