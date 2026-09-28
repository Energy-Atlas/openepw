"""Catalog seed for a hosted deployment.

The Stage 1 catalog is built from research files that are not in the repository, so a
hosted instance starts from a copy of a local catalog: ``make_seed`` packs the active
catalog generation and the NSRDB footprints into a .tar.gz with its SHA-256, and
``install_seed`` downloads it on first start, verifies the checksum and unpacks it into
an empty data root. Nothing else from the local data root (jobs, chat, credentials) is
included.

    python -m openepw.deploy make-seed --data-root .local/openepw --out openepw-seed.tar.gz
    python -m openepw.deploy install-seed   # reads OPENEPW_SEED_URL and OPENEPW_SEED_SHA256
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import urllib.request
from contextlib import closing
from pathlib import Path

from .availability.store import _TABLES

CATALOG = Path("catalog") / "catalog.sqlite3"


class SeedError(RuntimeError):
    """The seed could not be verified or installed; the data root is left unchanged."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def make_seed(data_root: Path, out: Path) -> tuple[Path, str]:
    """Pack the active catalog generation and the footprints; returns the file and SHA-256."""
    data_root, out = Path(data_root), Path(out)
    source = data_root / CATALOG
    if not source.is_file():
        raise SeedError(f"No catalog at {source}")
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "catalog.sqlite3"
        with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(copy)) as target:
            live.backup(target)                                    # a consistent snapshot
        with closing(sqlite3.connect(copy)) as db:
            row = db.execute("SELECT generation_id FROM active WHERE singleton = 1").fetchone()
            if row is None:
                raise SeedError("The local catalog has no active generation")
            for name, _ in _TABLES:
                db.execute(f"DELETE FROM {name} WHERE generation_id != ?", row)
            db.execute("DELETE FROM generations WHERE id != ?", row)
            db.execute("DELETE FROM stale_sources")
            db.commit()
        with closing(sqlite3.connect(copy)) as db:
            db.execute("VACUUM")
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, "w:gz") as archive:
            archive.add(copy, arcname=CATALOG.as_posix())
            footprints = data_root / "footprints"
            if footprints.is_dir():
                archive.add(footprints, arcname="footprints")
    return out, _sha256(out)


def install_seed(url: str, sha256: str, data_root: Path) -> bool:
    """Install the seed into a data root without a catalog; False if one is already there."""
    data_root = Path(data_root)
    if (data_root / CATALOG).is_file():
        return False
    if not url.startswith(("https://", "file:")):
        raise SeedError("The seed URL must use https")
    if len(sha256) != 64:
        raise SeedError("OPENEPW_SEED_SHA256 must be the seed's 64-character SHA-256")
    data_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_root) as scratch:
        download = Path(scratch) / "seed.tar.gz"
        with urllib.request.urlopen(url, timeout=300) as response, download.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        if _sha256(download) != sha256.lower():
            raise SeedError("The seed checksum does not match OPENEPW_SEED_SHA256")
        unpacked = Path(scratch) / "unpacked"
        try:
            with tarfile.open(download) as archive:
                archive.extractall(unpacked, filter="data")         # refuses paths outside, links, devices
        except (tarfile.TarError, OSError) as error:
            raise SeedError(f"The seed could not be unpacked safely: {error}") from None
        if not (unpacked / CATALOG).is_file():
            raise SeedError("The seed has no catalog")
        for name in ("catalog", "footprints"):
            if (unpacked / name).exists():
                shutil.copytree(unpacked / name, data_root / name, dirs_exist_ok=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m openepw.deploy")
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("make-seed", help="pack the local catalog for a hosted instance")
    make.add_argument("--data-root", type=Path, default=Path(".local/openepw"))
    make.add_argument("--out", type=Path, default=Path("openepw-seed.tar.gz"))
    install = commands.add_parser("install-seed", help="install the seed on first start")
    install.add_argument("--data-root", type=Path, default=Path(os.environ.get("OPENEPW_DATA_ROOT", ".local/openepw")))
    args = parser.parse_args(argv)
    try:
        if args.command == "make-seed":
            out, digest = make_seed(args.data_root, args.out)
            print(f"{out}  {out.stat().st_size / 1e6:.1f} MB\nOPENEPW_SEED_SHA256={digest}")
            return 0
        url = os.environ.get("OPENEPW_SEED_URL", "")
        if not url:
            print("OPENEPW_SEED_URL is not set; starting without a Stage 1 catalog", file=sys.stderr)
            return 0
        installed = install_seed(url, os.environ.get("OPENEPW_SEED_SHA256", ""), args.data_root)
        print("Catalog seed installed" if installed else "Catalog already present; seed skipped")
        return 0
    except SeedError as error:
        print(f"Seed failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
