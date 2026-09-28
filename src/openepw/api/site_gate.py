"""One site password in front of the whole app, remembered by a signed 30-day cookie.

For a hosted deployment (Render) where the browser UI and the API share one origin. The
cookie holds only an expiry and an HMAC of it, keyed by the password, so changing the
password signs every browser out. Health and the login page stay open.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import threading
import time
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "openepw_site"
LIFETIME = 30 * 24 * 3600
ATTEMPTS = 10                  # wrong passwords per address and window before refusing
WINDOW = 600
OPEN_PATHS = {"/health", "/login", "/logout"}


def _key(password: str) -> bytes:
    return hashlib.sha256(("openepw-site-v1:" + password).encode()).digest()


def sign(password: str, expires: int) -> str:
    digest = hmac.new(_key(password), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{digest}"


def valid(password: str, value: str | None) -> bool:
    try:
        expires = int((value or "").split(".", 1)[0])
    except ValueError:
        return False
    return expires > time.time() and hmac.compare_digest(sign(password, expires), value or "")


def _safe_next(target: str | None) -> str:
    """Only a path on this site; anything else returns to the start page."""
    target = target or "/"
    return target if target.startswith("/") and not target.startswith(("//", "/\\")) else "/"


def _page(next_path: str, error: str = "") -> str:
    message = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenEPW · Sign in</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; background: #333333; color: #1f1f1f; }}
body {{ min-height: 100vh; margin: 0; display: grid; place-items: center; }}
form {{ display: grid; gap: .7rem; width: min(20rem, calc(100vw - 2rem)); padding: 1.4rem; border-radius: 14px;
  background: #f2f2f2; box-shadow: 0 8px 30px rgba(0, 0, 0, .35); }}
h1 {{ margin: 0; font-size: 1.1rem; }} p {{ margin: 0; color: #545454; font-size: .85rem; }}
input {{ padding: .6rem .7rem; border: 1px solid #c4c4c4; border-radius: 9px; font: inherit; }}
button {{ padding: .6rem; border: 0; border-radius: 999px; background: #1f1f1f; color: #f2f2f2; font: inherit; }}
.error {{ color: #1f1f1f; font-weight: 600; }}
</style></head>
<body><form method="post" action="/login">
<h1>OpenEPW</h1><p>Enter the site password. This browser will remember it for 30 days.</p>{message}
<input type="password" name="password" aria-label="Password" autocomplete="current-password" autofocus required>
<input type="hidden" name="next" value="{html.escape(next_path)}">
<button type="submit">Sign in</button>
</form></body></html>"""


class SiteGate:
    def __init__(self, password: str):
        self.password = password
        self.failures: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _client(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return forwarded or (request.client.host if request.client else "unknown")

    def _blocked(self, client: str) -> bool:
        now = time.time()
        with self.lock:
            recent = [at for at in self.failures.get(client, []) if now - at < WINDOW]
            self.failures[client] = recent
            return len(recent) >= ATTEMPTS

    def allowed(self, request: Request) -> bool:
        return request.url.path in OPEN_PATHS or valid(self.password, request.cookies.get(COOKIE))

    def install(self, app: FastAPI) -> None:
        @app.middleware("http")
        async def site_gate(request: Request, call_next):
            if self.allowed(request):
                request.state.site_ok = request.url.path not in OPEN_PATHS
                return await call_next(request)
            if request.method == "GET" and not request.url.path.startswith("/v1/"):
                target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse(f"/login?next={quote(target, safe='/?=&')}", status_code=303)
            return JSONResponse({"code": "AUTH_REQUIRED", "message": "Sign in to OpenEPW first"}, status_code=401)

        @app.get("/login", include_in_schema=False)
        def login_page(next: str = "/"):
            return HTMLResponse(_page(_safe_next(next)))

        @app.post("/login", include_in_schema=False)
        async def login(request: Request) -> Response:
            form = await request.form()
            next_path = _safe_next(str(form.get("next") or "/"))
            client = self._client(request)
            if self._blocked(client):
                return HTMLResponse(_page(next_path, "Too many attempts; try again in 10 minutes."),
                                    status_code=429)
            if not hmac.compare_digest(str(form.get("password") or "").encode(), self.password.encode()):
                with self.lock:
                    self.failures.setdefault(client, []).append(time.time())
                return HTMLResponse(_page(next_path, "That password is not right."), status_code=401)
            with self.lock:
                self.failures.pop(client, None)
            response = RedirectResponse(next_path, status_code=303)
            secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
            response.set_cookie(COOKIE, sign(self.password, int(time.time()) + LIFETIME), max_age=LIFETIME,
                                httponly=True, secure=secure, samesite="lax", path="/")
            return response

        @app.get("/logout", include_in_schema=False)
        def logout():
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE, path="/")
            return response
