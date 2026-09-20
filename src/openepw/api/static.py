"""Optional static UI; API routing never falls through to the SPA."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles


class UIStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix or ".." in Path(path).parts:
                raise
            response = await super().get_response("index.html", scope)
        # Windows registry MIME overrides can classify module workers as text/plain.
        # Module scripts reject that type even though the HTTP request succeeds.
        if Path(path).suffix.lower() == ".mjs":
            response.headers["content-type"] = "text/javascript"
        return response


def mount_ui(app, directory):
    root = Path(directory).resolve()
    if not (root / "index.html").is_file():
        raise ValueError(
            "UI build missing: run npm --prefix ui run build, then pass --ui-dir ui/dist"
        )
    async def home(request):
        return RedirectResponse("/ui/")

    async def favicon(request):
        return RedirectResponse("/ui/favicon.svg")

    app.add_route("/", home, methods=["GET"], include_in_schema=False)
    app.add_route("/favicon.ico", favicon, methods=["GET"], include_in_schema=False)
    app.mount("/ui", UIStaticFiles(directory=root, html=True), name="ui")
