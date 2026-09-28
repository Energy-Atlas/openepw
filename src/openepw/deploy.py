"""Catalog install for a hosted deployment.

The Stage 1 catalog is published as a CSV data package in the Energy-Atlas open-data
repository (see ``openepw.availability.package``). A hosted instance builds its catalog
from that package on first start: ``install_catalog`` downloads ``datapackage.json``,
checks it against a pinned SHA-256, downloads every file it lists, checks each file's size
and SHA-256 from the descriptor, then imports the catalog and writes the footprints. A data
root that already has an active catalog is left alone.

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
import urllib.request
from contextlib import closing
from pathlib import Path
from urllib.parse import urljoin

from .availability.package import PackageError, from_files, safe_path, verify
from .availability.store import CatalogImportError, CatalogStore

CATALOG = Path("catalog") / "catalog.sqlite3"
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


def install_catalog(url: str, sha256: str, data_root: Path) -> bool:
    """Build the catalog from a pinned data package; False if a catalog is already active."""
    data_root = Path(data_root)
    if has_catalog(data_root):
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
    with tempfile.TemporaryDirectory(dir=data_root) as scratch:
        for path, data in package.footprints.items():
            target = Path(scratch, *path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        shutil.copytree(scratch, data_root / "footprints", dirs_exist_ok=True)
    try:
        store = CatalogStore(data_root / "catalog")
        store.activate(store.stage(package.bundle).generation_id)       # activation marks it installed
    except CatalogImportError as error:
        raise InstallError(f"The package catalog was refused: {error}") from None
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openepw.deploy")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("install-catalog", help="build the catalog from the open-data package on first start")
    install.add_argument("--data-root", type=Path, default=Path(os.environ.get("OPENEPW_DATA_ROOT", ".local/openepw")))
    args = parser.parse_args(argv)
    url = os.environ.get("OPENEPW_CATALOG_URL", "")
    if not url:
        print("OPENEPW_CATALOG_URL is not set; starting without a Stage 1 catalog", file=sys.stderr)
        return 0
    try:
        installed = install_catalog(url, os.environ.get("OPENEPW_CATALOG_SHA256", ""), args.data_root)
    except (InstallError, OSError) as error:
        print(f"Catalog install failed: {error}", file=sys.stderr)
        return 1
    print("Catalog installed from the data package" if installed else "Catalog already present; install skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
