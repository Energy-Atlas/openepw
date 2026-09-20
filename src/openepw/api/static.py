"""Optional static UI; API routing never falls through to the SPA."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class UIStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or Path(path).suffix or ".." in Path(path).parts:
                raise
            return await super().get_response("index.html", scope)


def mount_ui(app, directory):
    root = Path(directory).resolve()
    if not (root / "index.html").is_file():
        raise ValueError(
            "UI build missing: run npm --prefix ui run build, then pass --ui-dir ui/dist"
        )
    app.mount("/ui", UIStaticFiles(directory=root, html=True), name="ui")
