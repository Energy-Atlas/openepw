"""The hosted catalog seed: pack the active catalog locally, install it on first start."""

import hashlib
import io
import sqlite3
import tarfile

import pytest
from test_availability_store import bundle

from openepw.availability.store import CatalogStore
from openepw.deploy import SeedError, install_seed, make_seed


def _local_catalog(root):
    store = CatalogStore(root / "catalog")
    old = store.stage(bundle())
    store.activate(old.generation_id)
    current = store.stage(bundle())
    store.activate(current.generation_id)
    (root / "footprints" / "nsrdb").mkdir(parents=True)
    (root / "footprints" / "nsrdb" / "manifest.json").write_text("{}", encoding="utf-8")
    (root / "jobs").mkdir()
    (root / "jobs" / "private.epw").write_text("not shipped", encoding="utf-8")
    return current.generation_id


def test_the_seed_holds_only_the_active_catalog_and_footprints(tmp_path):
    active = _local_catalog(tmp_path / "local")
    seed, digest = make_seed(tmp_path / "local", tmp_path / "seed.tar.gz")
    assert digest == hashlib.sha256(seed.read_bytes()).hexdigest()
    with tarfile.open(seed) as archive:
        names = set(archive.getnames())
    assert {"catalog/catalog.sqlite3", "footprints/nsrdb/manifest.json"} <= names
    assert not any(name.startswith("jobs") for name in names)
    target = tmp_path / "hosted"
    assert install_seed(seed.as_uri(), digest, target) is True
    with sqlite3.connect(target / "catalog" / "catalog.sqlite3") as db:
        assert [row[0] for row in db.execute("SELECT id FROM generations")] == [active]
    assert CatalogStore(target / "catalog").active().snapshot.generation_id == active
    assert install_seed(seed.as_uri(), digest, target) is False              # already installed: left alone


def test_a_wrong_checksum_or_unsafe_member_is_refused(tmp_path):
    _local_catalog(tmp_path / "local")
    seed, _ = make_seed(tmp_path / "local", tmp_path / "seed.tar.gz")
    with pytest.raises(SeedError, match="checksum"):
        install_seed(seed.as_uri(), "0" * 64, tmp_path / "hosted")
    assert not (tmp_path / "hosted" / "catalog").exists()
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as archive:
        data = b"x"
        info = tarfile.TarInfo("../outside.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(evil.read_bytes()).hexdigest()
    with pytest.raises(SeedError):
        install_seed(evil.as_uri(), digest, tmp_path / "hosted2")
    assert not (tmp_path / "outside.txt").exists()
