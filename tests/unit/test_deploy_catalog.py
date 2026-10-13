"""The hosted catalog: built from a pinned, checksummed data package, and upgraded when the pin changes."""

import hashlib
import json

import pytest
from test_catalog_package import canonical, footprints, full_bundle

from openepw.availability.package import export_package
from openepw.availability.store import CatalogStore
from openepw.deploy import InstallError, install_catalog, main


def _package(tmp_path):
    descriptor = export_package(full_bundle(), tmp_path / "package", footprints(tmp_path / "fp"),
                                name="catalog", version="1")
    return descriptor, hashlib.sha256(descriptor.read_bytes()).hexdigest()


def test_the_catalog_and_footprints_are_installed_once_per_package(tmp_path):
    descriptor, digest = _package(tmp_path)
    target = tmp_path / "hosted"
    assert install_catalog(descriptor.as_uri(), digest, target) is True
    view = CatalogStore(target / "catalog").active()
    assert canonical(view.bundle) == canonical(full_bundle())
    assert (target / "footprints/nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/mask.json").read_text() == '{"rects": [[0, 0, 1, 1]]}'
    assert install_catalog(descriptor.as_uri(), digest, target) is False     # this package is installed
    assert CatalogStore(target / "catalog").active().snapshot.generation_id == view.snapshot.generation_id


def test_a_wrong_descriptor_checksum_is_refused(tmp_path):
    descriptor, _ = _package(tmp_path)
    with pytest.raises(InstallError, match="OPENEPW_CATALOG_SHA256"):
        install_catalog(descriptor.as_uri(), "0" * 64, tmp_path / "hosted")
    assert not (tmp_path / "hosted").exists()


def test_a_changed_file_is_refused_before_anything_is_written(tmp_path):
    descriptor, digest = _package(tmp_path)
    entries = descriptor.parent / "data/noaa/entries.csv"
    entries.write_bytes(entries.read_bytes() + b"\n")
    with pytest.raises(InstallError, match="entries.csv"):
        install_catalog(descriptor.as_uri(), digest, tmp_path / "hosted")
    assert not (tmp_path / "hosted").exists()


@pytest.mark.parametrize("path", ["../outside.csv", "/etc/passwd", "C:/x.csv", "data\\x.csv", "data/./x.csv"])
def test_a_path_outside_the_package_is_refused(tmp_path, path):
    descriptor, _ = _package(tmp_path)
    body = json.loads(descriptor.read_text(encoding="utf-8"))
    body["resources"][0]["path"] = path
    descriptor.write_text(json.dumps(body), encoding="utf-8")
    digest = hashlib.sha256(descriptor.read_bytes()).hexdigest()
    with pytest.raises(InstallError, match="path"):
        install_catalog(descriptor.as_uri(), digest, tmp_path / "hosted")


def test_plain_http_is_refused_and_an_unset_url_starts_without_a_catalog(tmp_path, monkeypatch, capsys):
    with pytest.raises(InstallError, match="https"):
        install_catalog("http://example.org/datapackage.json", "0" * 64, tmp_path / "hosted")
    monkeypatch.delenv("OPENEPW_CATALOG_URL", raising=False)
    assert main(["install-catalog", "--data-root", str(tmp_path / "hosted")]) == 0
    assert "without a Stage 1 catalog" in capsys.readouterr().err


def _second_package(tmp_path):
    """A newer release: one more source, and a different mask in place of the old one."""
    bundle = full_bundle()
    bundle.evidence.append(bundle.evidence[0].model_copy(update={"id": "newer-source"}))
    roots = tmp_path / "fp2"
    mask = roots / "era5land" / "reanalysis-era5-land" / "lsm"
    mask.mkdir(parents=True)
    (mask / "manifest.json").write_text('{"cells": 1}', encoding="utf-8")
    descriptor = export_package(bundle, tmp_path / "package2", roots, name="catalog", version="2")
    return descriptor, hashlib.sha256(descriptor.read_bytes()).hexdigest()


def test_a_new_pin_upgrades_the_catalog_and_replaces_the_footprints(tmp_path, capsys, monkeypatch):
    target = tmp_path / "hosted"
    first, first_digest = _package(tmp_path)
    install_catalog(first.as_uri(), first_digest, target)
    before = CatalogStore(target / "catalog").active().snapshot.generation_id
    second, second_digest = _second_package(tmp_path)
    monkeypatch.setenv("OPENEPW_CATALOG_URL", second.as_uri())
    monkeypatch.setenv("OPENEPW_CATALOG_SHA256", second_digest)
    assert main(["install-catalog", "--data-root", str(target)]) == 0
    assert "Catalog upgraded" in capsys.readouterr().out
    view = CatalogStore(target / "catalog").active()
    assert view.snapshot.generation_id != before
    assert "newer-source" in {item.id for item in view.bundle.evidence}
    assert not (target / "footprints/nsrdb").exists()                      # dropped mask no longer gates
    assert (target / "footprints/era5land/reanalysis-era5-land/lsm/manifest.json").is_file()
    assert json.loads((target / "catalog/package.json").read_text())["sha256"] == second_digest
    assert main(["install-catalog", "--data-root", str(target)]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_a_failed_upgrade_keeps_the_previous_catalog_and_still_starts(tmp_path, capsys, monkeypatch):
    target = tmp_path / "hosted"
    first, first_digest = _package(tmp_path)
    install_catalog(first.as_uri(), first_digest, target)
    before = CatalogStore(target / "catalog").active().snapshot.generation_id
    second, _ = _second_package(tmp_path)
    monkeypatch.setenv("OPENEPW_CATALOG_URL", second.as_uri())
    monkeypatch.setenv("OPENEPW_CATALOG_SHA256", "0" * 64)                   # a wrong pin
    assert main(["install-catalog", "--data-root", str(target)]) == 0
    assert "keeping the installed catalog" in capsys.readouterr().err
    assert CatalogStore(target / "catalog").active().snapshot.generation_id == before
    assert (target / "footprints/nsrdb/nsrdb-GOES-tmy-v4-0-0/tdy-2023/mask.json").is_file()
    assert json.loads((target / "catalog/package.json").read_text())["sha256"] == first_digest


def test_a_failed_first_install_starts_without_a_catalog(tmp_path, capsys, monkeypatch):
    first, _ = _package(tmp_path)
    monkeypatch.setenv("OPENEPW_CATALOG_URL", first.as_uri())
    monkeypatch.setenv("OPENEPW_CATALOG_SHA256", "0" * 64)
    assert main(["install-catalog", "--data-root", str(tmp_path / "hosted")]) == 0
    assert "starting without a Stage 1 catalog" in capsys.readouterr().err
