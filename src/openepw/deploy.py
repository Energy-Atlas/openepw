"""Catalog install for a hosted deployment.

The Stage 1 catalog is published as a CSV data package in the Energy-Atlas open-data
repository (see ``openepw.availability.package``). A hosted instance builds its catalog
from that package on start: ``install_catalog`` downloads ``datapackage.json``, checks it
against a pinned SHA-256, downloads every file it lists, checks each file's size and SHA-256
from the descriptor, then stages the catalog as a new generation, replaces the footprints
folder as a whole and activates the generation. The installed package's SHA-256 is recorded
(``catalog/package.json``); a start with the same pin does nothing, and a new pin upgrades
(owner decision 2026-10-13). Nothing is written until everything is verified, and a failed
upgrade leaves the previous catalog and footprints in place.

    python -m openepw.deploy install-catalog   # reads OPENEPW_CATALOG_URL and OPENEPW_CATALOG_SHA256
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urljoin

from .availability.package import PackageError, from_files, safe_path, verify
from .availability.store import CatalogImportError, CatalogStore

CATALOG = Path("catalog") / "catalog.sqlite3"
INSTALLED = Path("catalog") / "package.json"   # the SHA-256 and URL of the installed package
LIMIT = 64 * 1024 * 1024                        # largest single file accepted


class InstallError(RuntimeError):
    """The package could not be verified or installed; the data root has no new catalog."""


def has_catalog(data_root: Path) -> bool:
    database = Path(data_root) / CATALOG
    if not database.is_file():
        return False
    with closing(sqlite3.connect(database)) as db:
        try:
            return db.execute("SELECT 1 FROM active WHERE singleton = 1").fetchone() is not None
        except sqlite3.Error:
            return False


def _fetch(url: str, limit: int) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise InstallError(f"{url} is larger than expected")
    return data


def installed_package(data_root: Path) -> dict | None:
    try:
        return json.loads((Path(data_root) / INSTALLED).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def install_catalog(url: str, sha256: str, data_root: Path) -> bool:
    """Build or upgrade the catalog from a pinned data package; False when that package is
    already the installed one."""
    data_root = Path(data_root)
    if has_catalog(data_root) and (installed_package(data_root) or {}).get("sha256") == sha256.lower():
        return False
    if not url.startswith(("https://", "file:")):
        raise InstallError("The catalog URL must use https")
    if len(sha256) != 64:
        raise InstallError("OPENEPW_CATALOG_SHA256 must be the 64-character SHA-256 of datapackage.json")
    raw = _fetch(url, LIMIT)
    if hashlib.sha256(raw).hexdigest() != sha256.lower():
        raise InstallError("datapackage.json does not match OPENEPW_CATALOG_SHA256")
    try:
        descriptor = json.loads(raw.decode("utf-8"))
        files = {}
        for resource in descriptor.get("resources", []):
            path = safe_path(resource.get("path"))
            if not isinstance(resource.get("bytes"), int) or resource["bytes"] > LIMIT:
                raise PackageError(f"{path} has no acceptable size in the descriptor")
            data = _fetch(urljoin(url, path), resource["bytes"])
            verify(resource, data)
            files[path] = data
        package = from_files(descriptor, files)
    except (PackageError, ValueError) as error:
        raise InstallError(str(error)) from None
    data_root.mkdir(parents=True, exist_ok=True)
    store = CatalogStore(data_root / "catalog")
    try:
        generation = store.stage(package.bundle).generation_id
    except CatalogImportError as error:
        raise InstallError(f"The package catalog was refused: {error}") from None
    current, previous = data_root / "footprints", data_root / "footprints.previous"
    with tempfile.TemporaryDirectory(dir=data_root) as scratch:
        staged = Path(scratch, "footprints")
        staged.mkdir()
        for path, data in package.footprints.items():
            target = staged.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        # The whole folder is replaced, so a mask the new package dropped stops gating.
        shutil.rmtree(previous, ignore_errors=True)
        if current.exists():
            current.rename(previous)
        staged.rename(current)
    try:
        store.activate(generation)
    except Exception:
        shutil.rmtree(current, ignore_errors=True)
        if previous.exists():
            previous.rename(current)
        raise
    shutil.rmtree(previous, ignore_errors=True)
    (data_root / INSTALLED).write_text(json.dumps({"sha256": sha256.lower(), "url": url,
                                                   "generation_id": generation}), encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openepw.deploy")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-catalog", help="build or upgrade the catalog from the pinned open-data package")
    install.add_argument("--data-root", type=Path, default=Path(os.environ.get("OPENEPW_DATA_ROOT", ".local/openepw")))
    args = parser.parse_args(argv)
    url = os.environ.get("OPENEPW_CATALOG_URL", "")
    if not url:
        print("OPENEPW_CATALOG_URL is not set; starting without a Stage 1 catalog", file=sys.stderr)
        prepare_catalog(args.data_root)                 # a catalog imported by hand, if any
        return 0
    had_catalog = has_catalog(args.data_root)
    try:
        installed = install_catalog(url, os.environ.get("OPENEPW_CATALOG_SHA256", ""), args.data_root)
    except (InstallError, OSError) as error:
        # The server still starts: with the previous catalog, or with bundled contracts only.
        keeping = "keeping the installed catalog" if had_catalog else "starting without a Stage 1 catalog"
        print(f"Catalog install failed: {error}; {keeping}", file=sys.stderr)
        prepare_catalog(args.data_root)
        return 0
    print(("Catalog upgraded from the data package" if had_catalog else "Catalog installed from the data package")
          if installed else "Catalog already installed from this package; nothing to do")
    prepare_catalog(args.data_root)
    return 0


def prepare_catalog(data_root: Path) -> None:
    """Write the active generation's derived files (its index and the map) before the server
    starts, so no visitor waits for them; skipped quickly when they already exist."""
    started = time.monotonic()
    try:
        from .config import RuntimeConfig
        from .service import WeatherService

        WeatherService(RuntimeConfig(data_root=Path(data_root))).warm_catalog()
    except Exception as error:                         # the server builds them on first use
        print(f"Catalog preparation failed: {error}; the server builds it on first use", file=sys.stderr)
        return
    print(f"Catalog prepared in {time.monotonic() - started:.1f} s")


if __name__ == "__main__":
    raise SystemExit(main())
