"""Personal accounts for a hosted deployment: Cornell email, emailed link, password.

Sign-up asks only for an address; the password is chosen on the page an emailed one-time
link opens, so an account's password is set only by whoever reads that inbox. Reset uses
the same page. Link tokens travel in the URL fragment, which browsers never send, so they
stay out of access logs. Sessions are random tokens in an HttpOnly cookie, stored hashed.
See docs/decisions/0005-accounts.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "openepw_session"
SESSION_LIFETIME = 30 * 24 * 3600
SETUP_LIFETIME = 24 * 3600
RESET_LIFETIME = 3600
MIN_PASSWORD, MAX_PASSWORD = 12, 256
ATTEMPTS, WINDOW = 10, 600                  # failed sign-ins per address and per client
MAILS_PER_ADDRESS, MAILS_PER_HOUR = 3, 100
OPEN_PATHS = {"/health", "/login", "/logout", "/signup", "/reset", "/password"}
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_log = logging.getLogger("openepw.accounts")
if not _log.handlers:                          # visible in the server log (Render's Logs tab)
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("accounts: %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False
_EMAIL = re.compile(r"^[^@\s]+@([^@\s]+)$")


# -- passwords ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    encode = base64.urlsafe_b64encode
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${encode(salt).decode()}${encode(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        expected = base64.urlsafe_b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=int(n), r=int(r),
                                p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))      # keeps unknown-address timing alike


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def masked(email: str) -> str:
    """An address as the log shows it: first letter and domain."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


# -- storage -----------------------------------------------------------------------------

class AccountStore:
    """Users, one-time link tokens and sessions in one SQLite file."""

    def __init__(self, root: Path):
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "accounts.sqlite3"
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                    password_hash TEXT, verified_at REAL, disabled INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL
                    REFERENCES users(id), purpose TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL
                    REFERENCES users(id), expires REAL NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS mail_log (email TEXT NOT NULL, at REAL NOT NULL);
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA foreign_keys = ON")
        return closing(db)

    def _run(self, sql: str, args=()):
        with self._db() as db, db:
            return db.execute(sql, args).fetchall()

    def email(self, user_id: int | None) -> str | None:
        rows = self._run("SELECT email FROM users WHERE id = ?", (user_id,)) if user_id is not None else []
        return rows[0][0] if rows else None

    def user(self, email: str):
        rows = self._run("SELECT id, password_hash, verified_at, disabled FROM users WHERE email = ?",
                         (normalize_email(email),))
        return rows[0] if rows else None

    def create_pending(self, email: str) -> int:
        email = normalize_email(email)
        self._run("INSERT OR IGNORE INTO users (email, created_at) VALUES (?, ?)", (email, time.time()))
        return self._run("SELECT id FROM users WHERE email = ?", (email,))[0][0]

    def issue(self, user_id: int, purpose: str, ttl: float) -> str:
        token = secrets.token_urlsafe(32)
        self._run("INSERT INTO tokens (hash, user_id, purpose, expires) VALUES (?, ?, ?, ?)",
                  (_digest(token), user_id, purpose, time.time() + ttl))
        return token

    def redeem(self, token: str) -> tuple[int, str] | None:
        """Use a link token once; returns (user, purpose) or None when unknown, used or expired."""
        with self._db() as db, db:
            row = db.execute("SELECT user_id, purpose FROM tokens WHERE hash = ? AND used = 0 AND expires > ?",
                             (_digest(token), time.time())).fetchone()
            if row is None:
                return None
            db.execute("UPDATE tokens SET used = 1 WHERE hash = ?", (_digest(token),))
            return row[0], row[1]

    def set_password(self, user_id: int, password: str) -> None:
        """Set the password, mark the address verified and end every existing session."""
        with self._db() as db, db:
            db.execute("UPDATE users SET password_hash = ?, verified_at = COALESCE(verified_at, ?) WHERE id = ?",
                       (hash_password(password), time.time(), user_id))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            db.execute("UPDATE tokens SET used = 1 WHERE user_id = ?", (user_id,))

    def sign_in(self, email: str, password: str) -> int | None:
        row = self.user(email)
        if row is None or row[1] is None:
            check_password(password, _DUMMY_HASH)
            return None
        user_id, stored, verified, disabled = row
        if not check_password(password, stored) or verified is None or disabled:
            return None
        return user_id

    def open_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._run("INSERT INTO sessions (hash, user_id, expires, created) VALUES (?, ?, ?, ?)",
                  (_digest(token), user_id, now + SESSION_LIFETIME, now))
        return token

    def session_user(self, token: str | None) -> int | None:
        if not token:
            return None
        rows = self._run("SELECT s.user_id FROM sessions s JOIN users u ON u.id = s.user_id "
                         "WHERE s.hash = ? AND s.expires > ? AND u.disabled = 0", (_digest(token), time.time()))
        return rows[0][0] if rows else None

    def close_session(self, token: str | None) -> None:
        if token:
            self._run("DELETE FROM sessions WHERE hash = ?", (_digest(token),))

    def may_mail(self, email: str) -> bool:
        """Record an account email unless the address or the hour is over its limit."""
        now = time.time()
        with self._db() as db, db:
            db.execute("DELETE FROM mail_log WHERE at < ?", (now - 3600,))
            to_address = db.execute("SELECT COUNT(*) FROM mail_log WHERE email = ?", (email,)).fetchone()[0]
            total = db.execute("SELECT COUNT(*) FROM mail_log").fetchone()[0]
            if to_address >= MAILS_PER_ADDRESS or total >= MAILS_PER_HOUR:
                return False
            db.execute("INSERT INTO mail_log (email, at) VALUES (?, ?)", (email, now))
            return True

    def accounts(self) -> list[dict]:
        rows = self._run("SELECT email, verified_at, disabled, created_at FROM users ORDER BY email")
        return [{"email": email, "verified": verified is not None, "disabled": bool(disabled),
                 "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created))}
                for email, verified, disabled, created in rows]

    def set_disabled(self, email: str, disabled: bool) -> bool:
        row = self.user(email)
        if row is None:
            return False
        with self._db() as db, db:
            db.execute("UPDATE users SET disabled = ? WHERE id = ?", (int(disabled), row[0]))
            if disabled:
                db.execute("DELETE FROM sessions WHERE user_id = ?", (row[0],))
        return True


# -- mail --------------------------------------------------------------------------------

class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str) -> object: ...


class MailError(RuntimeError):
    """The message could not be handed to the mail service."""


class ResendMailer:
    URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender: str, timeout: float = 20):
        self.api_key, self.sender, self.timeout = api_key, sender, timeout

    def send(self, to: str, subject: str, text: str) -> str:
        """Hand the message to Resend; returns Resend's message id."""
        body = json.dumps({"from": self.sender, "to": [to], "subject": subject, "text": text}).encode()
        request = urllib.request.Request(self.URL, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
            "User-Agent": "openepw", "Idempotency-Key": secrets.token_hex(16)})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return str(json.loads(response.read() or b"{}").get("id", ""))
        except urllib.error.HTTPError as error:
            # Resend explains a refusal (unverified domain, test sender to another address, bad key).
            try:
                reason = json.loads(error.read() or b"{}").get("message", "")
            except ValueError:
                reason = ""
            raise MailError(f"Resend refused the message: HTTP {error.code} {reason}".strip()) from None
        except (urllib.error.URLError, OSError) as error:
            raise MailError(f"Resend could not be reached: {type(error).__name__}") from None


class ConsoleMailer:
    """Local development only: prints the message, links included, to the server console."""

    def send(self, to: str, subject: str, text: str) -> None:
        print(f"--- account email to {to}: {subject}\n{text}\n---", flush=True)


# -- pages -------------------------------------------------------------------------------

_STYLE = """
:root { color-scheme: light; font-family: system-ui, sans-serif; background: #333333; color: #1f1f1f; }
body { min-height: 100vh; margin: 0; display: grid; place-items: center; }
form, .card { display: grid; gap: .7rem; width: min(21rem, calc(100vw - 2rem)); padding: 1.4rem;
  border-radius: 14px; background: #f2f2f2; box-shadow: 0 8px 30px rgba(0, 0, 0, .35); }
h1 { margin: 0; font-size: 1.1rem; } p { margin: 0; color: #545454; font-size: .85rem; }
input { padding: .6rem .7rem; border: 1px solid #c4c4c4; border-radius: 9px; font: inherit; }
button { padding: .6rem; border: 0; border-radius: 999px; background: #1f1f1f; color: #f2f2f2; font: inherit; }
a { color: #1f1f1f; } .links { display: flex; justify-content: space-between; font-size: .85rem; }
.error { color: #1f1f1f; font-weight: 600; }
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>OpenEPW · {html.escape(title)}</title><style>{_STYLE}</style>
</head><body>{body}</body></html>""", status_code=status)


def _error(message: str) -> str:
    return f'<p class="error" role="alert">{html.escape(message)}</p>' if message else ""


def _safe_next(target: str | None) -> str:
    """Only a path on this site; anything else returns to the start page."""
    target = target or "/"
    return target if target.startswith("/") and not target.startswith(("//", "/\\")) else "/"


def _login_page(next_path: str, error: str = "", status: int = 200) -> HTMLResponse:
    return _page("Sign in", f"""<form method="post" action="/login">
<h1>OpenEPW</h1><p>Sign in with your Cornell email.</p>{_error(error)}
<input type="email" name="email" aria-label="Email" autocomplete="username" required autofocus>
<input type="password" name="password" aria-label="Password" autocomplete="current-password" required>
<input type="hidden" name="next" value="{html.escape(next_path)}">
<button type="submit">Sign in</button>
<div class="links"><a href="/signup">Create an account</a><a href="/reset">Forgot password</a></div>
</form>""", status)


def _email_page(action: str, title: str, intro: str, error: str = "", status: int = 200) -> HTMLResponse:
    return _page(title, f"""<form method="post" action="{action}">
<h1>{html.escape(title)}</h1><p>{html.escape(intro)}</p>{_error(error)}
<input type="email" name="email" aria-label="Cornell email" autocomplete="email" required autofocus>
<button type="submit">Send the link</button>
<div class="links"><a href="/login">Sign in</a></div>
</form>""", status)


def _password_page(error: str = "", token: str = "", status: int = 200) -> HTMLResponse:
    # The token arrives in the fragment (#t=...), which never reaches the server; move it into the form.
    return _page("Choose a password", f"""<form method="post" action="/password" id="set">
<h1>Choose a password</h1><p>At least {MIN_PASSWORD} characters. Setting it signs out your other browsers.</p>
{_error(error)}
<input type="password" name="password" aria-label="New password" autocomplete="new-password" required autofocus>
<input type="password" name="confirm" aria-label="Repeat password" autocomplete="new-password" required>
<input type="hidden" name="token" id="token" value="{html.escape(token)}">
<button type="submit">Save and sign in</button>
</form>
<script>
const found = new URLSearchParams(location.hash.slice(1)).get("t");
if (found) {{ document.getElementById("token").value = found; history.replaceState(null, "", location.pathname); }}
</script>""", status)


def _sent_page() -> HTMLResponse:
    return _page("Check your email", """<div class="card"><h1>Check your email</h1>
<p>If that address can use OpenEPW, a link is on its way. It works once; check spam if it does not arrive.</p>
<div class="links"><a href="/login">Sign in</a></div></div>""")


# -- the gate ----------------------------------------------------------------------------

class Accounts:
    def __init__(self, store: AccountStore, mailer: Mailer, public_url: str | None, domains: list[str],
                 bearer_token: str | None = None, public_ui: bool = False):
        self.store, self.mailer, self.domains = store, mailer, [d.lower() for d in domains]
        self.bearer_token = bearer_token
        self.public_ui = public_ui                  # the built UI is served to visitors as a landing page
        self.public_url = (public_url or "").rstrip("/")
        self.failures: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    # throttling of failed sign-ins, by address and by client
    def _client(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or (request.client.host if request.client else "unknown")

    def _blocked(self, *keys: str) -> bool:
        now = time.time()
        with self.lock:
            for key in keys:
                self.failures[key] = [at for at in self.failures.get(key, []) if now - at < WINDOW]
            return any(len(self.failures[key]) >= ATTEMPTS for key in keys)

    def _fail(self, *keys: str) -> None:
        with self.lock:
            for key in keys:
                self.failures.setdefault(key, []).append(time.time())

    def allowed_email(self, email: str) -> bool:
        match = _EMAIL.match(email)
        return match is not None and match.group(1) in self.domains

    def _link(self, request: Request, token: str) -> str:
        base = self.public_url or str(request.base_url).rstrip("/")
        return f"{base}/password#t={token}"

    def _mail(self, email: str, subject: str, text: str) -> None:
        if not self.store.may_mail(email):
            _log.warning("not sent to %s (%s): hourly email limit reached", masked(email), subject)
            return
        try:
            sent = self.mailer.send(email, subject, text)
        except MailError as error:
            _log.error("not sent to %s (%s): %s", masked(email), subject, error)
            raise
        _log.info("sent to %s (%s)%s", masked(email), subject, f", id {sent}" if isinstance(sent, str) and sent else "")

    def _cookie(self, request: Request, response: Response, user_id: int) -> Response:
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(COOKIE, self.store.open_session(user_id), max_age=SESSION_LIFETIME,
                            httponly=True, secure=secure, samesite="lax", path="/")
        return response

    # the account operations, shared by the HTML pages and the JSON endpoints of the landing page

    def _sign_in(self, request: Request, email: str, password: str) -> tuple[int, int | None, str]:
        """(status, user, message) for a sign-in attempt."""
        email = normalize_email(email)
        keys = ("client:" + self._client(request), "email:" + email)
        if self._blocked(*keys):
            return 429, None, "Too many attempts; try again in 10 minutes."
        user = self.store.sign_in(email, password[:MAX_PASSWORD])
        if user is None:
            self._fail(*keys)
            return 401, None, "That email and password do not match an account."
        return 200, user, ""

    def _sign_up(self, request: Request, email: str) -> tuple[int, str]:
        email = normalize_email(email)
        if not self.allowed_email(email):
            return 400, f"Only {self.domain_text} addresses can sign up."
        row = self.store.user(email)
        try:
            if row is not None and row[2] is not None:
                token = self.store.issue(row[0], "reset", RESET_LIFETIME)
                self._mail(email, "Your OpenEPW account", (
                    "Someone asked to create an OpenEPW account for this address, which already has an "
                    "account.\n\nSign in, or set a new password with this link (valid for 1 hour):\n"
                    f"{self._link(request, token)}\n\nIf this was not you, ignore this email."))
            else:
                user = self.store.create_pending(email)
                token = self.store.issue(user, "setup", SETUP_LIFETIME)
                self._mail(email, "Finish creating your OpenEPW account", (
                    "Choose your password with this link (valid for 24 hours, once):\n"
                    f"{self._link(request, token)}\n\nIf you did not ask for an OpenEPW account, "
                    "ignore this email."))
        except MailError:
            return 503, "The email service is not answering; try again later."
        return 200, ""

    def _reset(self, request: Request, email: str) -> tuple[int, str]:
        email = normalize_email(email)
        row = self.store.user(email) if self.allowed_email(email) else None
        if row is not None and row[2] is not None and not row[3]:
            token = self.store.issue(row[0], "reset", RESET_LIFETIME)
            try:
                self._mail(email, "Reset your OpenEPW password", (
                    "Choose a new password with this link (valid for 1 hour, once):\n"
                    f"{self._link(request, token)}\n\nIf you did not ask for this, ignore this email; "
                    "your password stays the same."))
            except MailError:
                return 503, "The email service is not answering; try again later."
        return 200, ""

    @property
    def domain_text(self) -> str:
        return " or ".join("@" + domain for domain in self.domains)

    def install(self, app: FastAPI) -> None:
        domains = self.domain_text
        sent = ("If that address can use OpenEPW, a link is on its way. It works once; "
                "check spam if it does not arrive.")

        def open_path(path: str) -> bool:
            return path in OPEN_PATHS or path.startswith("/auth/")

        @app.middleware("http")
        async def account_gate(request: Request, call_next):
            if open_path(request.url.path):
                return await call_next(request)
            user = self.store.session_user(request.cookies.get(COOKIE))
            if user is not None:
                request.state.signed_in = True
                request.state.user_id = user
                return await call_next(request)
            if self.bearer_token and hmac.compare_digest(request.headers.get("authorization", ""),
                                                         "Bearer " + self.bearer_token):
                request.state.signed_in = True           # a script with the bearer token
                return await call_next(request)
            if request.method == "GET" and not request.url.path.startswith("/v1/"):
                if self.public_ui and not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
                    return await call_next(request)      # the built UI shows its landing page and sign-in
                target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse(f"/login?next={quote(target, safe='/?=&')}", status_code=303)
            return JSONResponse({"code": "AUTH_REQUIRED", "message": "Sign in to OpenEPW first"}, status_code=401)

        # JSON endpoints for the landing page's sign-in window. A JSON body cannot be sent
        # cross-site without a CORS preflight, which this app never grants.
        async def json_body(request: Request) -> dict:
            try:
                body = await request.json()
            except ValueError:
                body = None
            return body if isinstance(body, dict) else {}

        def answer(status: int, message: str = "") -> JSONResponse:
            return JSONResponse({"ok": status == 200, "message": message}, status_code=status)

        @app.get("/auth/session", include_in_schema=False)
        def auth_session(request: Request):
            user = self.store.session_user(request.cookies.get(COOKIE))
            return {"accounts": True, "signed_in": user is not None, "email": self.store.email(user),
                    "domains": self.domains}

        @app.post("/auth/login", include_in_schema=False)
        async def auth_login(request: Request) -> Response:
            body = await json_body(request)
            status, user, message = self._sign_in(request, str(body.get("email") or ""),
                                                  str(body.get("password") or ""))
            if user is None:
                return answer(status, message)
            return self._cookie(request, answer(200), user)

        @app.post("/auth/signup", include_in_schema=False)
        async def auth_signup(request: Request) -> Response:
            status, message = self._sign_up(request, str((await json_body(request)).get("email") or ""))
            return answer(status, message or sent)

        @app.post("/auth/reset", include_in_schema=False)
        async def auth_reset(request: Request) -> Response:
            status, message = self._reset(request, str((await json_body(request)).get("email") or ""))
            return answer(status, message or sent)

        @app.post("/auth/logout", include_in_schema=False)
        def auth_logout(request: Request) -> Response:
            self.store.close_session(request.cookies.get(COOKIE))
            response = answer(200)
            response.delete_cookie(COOKIE, path="/")
            return response

        # HTML pages: the emailed link's password page, and sign-in without the built UI.

        @app.get("/login", include_in_schema=False)
        def login_page(next: str = "/"):
            return _login_page(_safe_next(next))

        @app.post("/login", include_in_schema=False)
        async def login(request: Request) -> Response:
            form = await request.form()
            next_path = _safe_next(str(form.get("next") or "/"))
            status, user, message = self._sign_in(request, str(form.get("email") or ""),
                                                  str(form.get("password") or ""))
            if user is None:
                return _login_page(next_path, message, status)
            return self._cookie(request, RedirectResponse(next_path, status_code=303), user)

        @app.get("/logout", include_in_schema=False)
        def logout(request: Request):
            self.store.close_session(request.cookies.get(COOKIE))
            response = RedirectResponse("/" if self.public_ui else "/login", status_code=303)
            response.delete_cookie(COOKIE, path="/")
            return response

        @app.get("/signup", include_in_schema=False)
        def signup_page():
            return _email_page("/signup", "Create an account",
                               f"Use your {domains} address. We will email a link to choose your password.")

        @app.post("/signup", include_in_schema=False)
        async def signup(request: Request) -> Response:
            status, message = self._sign_up(request, str((await request.form()).get("email") or ""))
            if status != 200:
                return _email_page("/signup", "Create an account", f"Use your {domains} address.",
                                   message, status)
            return _sent_page()

        @app.get("/reset", include_in_schema=False)
        def reset_page():
            return _email_page("/reset", "Reset your password",
                               "Enter your account's email; we will send a link to choose a new password.")

        @app.post("/reset", include_in_schema=False)
        async def reset(request: Request) -> Response:
            status, message = self._reset(request, str((await request.form()).get("email") or ""))
            if status != 200:
                return _email_page("/reset", "Reset your password", "The email could not be sent.",
                                   message, status)
            return _sent_page()

        @app.get("/password", include_in_schema=False)
        def password_page():
            return _password_page()

        @app.post("/password", include_in_schema=False)
        async def set_password(request: Request) -> Response:
            form = await request.form()
            token = str(form.get("token") or "")
            password, confirm = str(form.get("password") or ""), str(form.get("confirm") or "")
            if not (MIN_PASSWORD <= len(password) <= MAX_PASSWORD):
                return _password_page(f"Use {MIN_PASSWORD} to {MAX_PASSWORD} characters.", token, 400)
            if password != confirm:
                return _password_page("The two passwords are different.", token, 400)
            redeemed = self.store.redeem(token) if token else None
            if redeemed is None:
                return _password_page("This link has expired or was already used; ask for a new one.",
                                      status=400)
            user, _ = redeemed
            self.store.set_password(user, password)
            return self._cookie(request, RedirectResponse("/", status_code=303), user)
