"""Owner decisions of 2026-10-12: aged evidence keeps durable facts, the NSRDB coverage map
gates NSRDB GOES products, and published station files have a 100 km reach."""

import hashlib
import json
from datetime import datetime, timezone

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    CatalogSnapshotRef,
    EvidenceRef,
    ProductRecord,
    SiteRecord,
    TMYReferenceScope,
    WeatherAvailabilityQuery,
)
from openepw.availability.coverage import GridCoverage, nsrdb_coverage
from openepw.availability.evaluate import evaluate
from openepw.availability.store import CatalogView
from openepw.models import Location, WeatherRequest

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def _view(bundle, stale=()):
    snapshot = CatalogSnapshotRef(generation_id="synthetic", created_at=NOW)
    snapshot.stale_sources = list(stale)
    return CatalogView(snapshot, bundle)


def _noaa(years):
    return CatalogBundle(
        evidence=[EvidenceRef(id="noaa-counts", sha256="a" * 64, retrieved_at=NOW, basis="inventory")],
        products=[ProductRecord(id="noaa:isd", provider="noaa", dataset="isd", spatial_kind="station",
                                temporal_kind="actual", evidence_ids=["noaa-counts"])],
        sites=[SiteRecord(id="S1", product_id="noaa:isd", lat=42, lon=-76, position_status="published",
                          station_identity_status="verified", evidence_ids=["noaa-counts"])],
        entries=[AvailabilityEntry(id="years", product_id="noaa:isd", site_id="S1",
                                   scope=ActualScope(years=years), evidence_basis="inventory",
                                   evidence_ids=["noaa-counts"])])


def _decision(bundle, years, stale=(), coverage=None, lat=42.0, lon=-76.0, product="historical"):
    request = WeatherRequest(locations=Location(lat=lat, lon=lon), years=years, product=product)
    kind = "actual" if product == "historical" else "tmy_reference"
    [option] = [option for option in evaluate(WeatherAvailabilityQuery(request=request),
                                              _view(bundle, stale), coverage).options
                if option.product.temporal_kind == kind]
    return option.eligibility


def test_an_aged_inventory_keeps_closed_years_but_not_the_newest():
    closed = _decision(_noaa([2022, 2023, 2024]), [2022], stale=["noaa-counts"])
    assert closed.status == "supported" and "SOURCE_CHECK_DUE" in closed.reasons and closed.stale
    newest = _decision(_noaa([2022, 2023, 2024]), [2024], stale=["noaa-counts"])
    assert newest.status == "unknown" and "STALE_SOURCE_EVIDENCE" in newest.unknowns
    fresh = _decision(_noaa([2022, 2023, 2024]), [2024])
    assert fresh.status == "supported" and "SOURCE_CHECK_DUE" not in fresh.reasons


def _nsrdb():
    probe = Location(lat=42.44, lon=-76.5)
    return CatalogBundle(
        evidence=[EvidenceRef(id="nsrdb-ithaca", sha256="b" * 64, retrieved_at=NOW, basis="targeted_probe")],
        products=[ProductRecord(id="nsrdb:aggregate:v4", provider="nsrdb", dataset="nsrdb-GOES-aggregated-v4-0-0",
                                temporal_kind="actual", evidence_ids=["nsrdb-ithaca"]),
                  ProductRecord(id="nsrdb:tmy:v4", provider="nsrdb", dataset="nsrdb-GOES-tmy-v4-0-0",
                                temporal_kind="tmy_reference", evidence_ids=["nsrdb-ithaca"])],
        entries=[AvailabilityEntry(id="actual", product_id="nsrdb:aggregate:v4",
                                   scope=ActualScope(years=list(range(1998, 2026))),
                                   evidence_basis="targeted_probe", evidence_ids=["nsrdb-ithaca"],
                                   probe_location=probe),
                 AvailabilityEntry(id="tdy", product_id="nsrdb:tmy:v4",
                                   scope=TMYReferenceScope(product_label="tdy-2023"),
                                   evidence_basis="targeted_probe", evidence_ids=["nsrdb-ithaca"],
                                   probe_location=probe)])


# Occupied 1-degree cells around (40..45 N, 80..70 W), as (row, column) from (-90, -180).
COVERAGE = GridCoverage(1.0, frozenset((row, column) for row in range(130, 135) for column in range(100, 110)),
                        ("nsrdb-GOES-tmy-v4-0-0/tdy-2023",))


def test_the_coverage_map_gates_nsrdb():
    inside = _decision(_nsrdb(), [2018], coverage=COVERAGE, lat=43.1, lon=-75.2)       # not the probe point
    assert inside.status == "supported" and "INSIDE_SOURCE_COVERAGE" in inside.reasons
    outside = _decision(_nsrdb(), [2018], coverage=COVERAGE, lat=1.29, lon=103.85)     # Singapore
    assert outside.status == "excluded" and "OUTSIDE_SOURCE_COVERAGE" in outside.reasons
    edge = _decision(_nsrdb(), [2018], coverage=COVERAGE, lat=45.5, lon=-75.2)         # next to the last row
    assert edge.status == "unknown" and "NEAR_SOURCE_COVERAGE_EDGE" in edge.unknowns
    unlisted = _decision(_nsrdb(), [2030], coverage=COVERAGE, lat=43.1, lon=-75.2)
    assert unlisted.status == "unknown"                                               # years still apply
    typical = _decision(_nsrdb(), [], coverage=COVERAGE, lat=1.29, lon=103.85, product="tmy")
    assert typical.status == "excluded"
    without_map = _decision(_nsrdb(), [2018], lat=43.1, lon=-75.2)
    assert without_map.status == "unknown" and "TARGETED_PROBE_ONLY" in without_map.unknowns


def test_published_station_files_reach_100_km():
    bundle = CatalogBundle(
        evidence=[EvidenceRef(id="ob", sha256="c" * 64, retrieved_at=NOW, basis="inventory")],
        products=[ProductRecord(id="onebuilding:x", provider="onebuilding", dataset="OneBuilding published EPW",
                                spatial_kind="station", temporal_kind="tmy_reference", evidence_ids=["ob"])],
        sites=[SiteRecord(id="far", product_id="onebuilding:x", lat=-12.19, lon=96.83, evidence_ids=["ob"])],
        entries=[AvailabilityEntry(id="tmyx", product_id="onebuilding:x", site_id="far",
                                   scope=TMYReferenceScope(product_label="TMYx"), evidence_basis="inventory",
                                   evidence_ids=["ob"])])
    far = _decision(bundle, [], lat=1.29, lon=103.85, product="tmy")
    assert far.status == "excluded" and "BEYOND_PROVIDER_SEARCH_RADIUS" in far.reasons
    near = _decision(bundle, [], lat=-12.5, lon=96.9, product="tmy")
    assert near.status == "supported"


def test_only_masks_matching_their_manifest_checksum_are_used(tmp_path):
    folder = tmp_path / "nsrdb" / "nsrdb-GOES-tmy-v4-0-0" / "tdy-2023"
    folder.mkdir(parents=True)
    raw = json.dumps({"step_degrees": 0.25, "cells": [[528, 413]]}).encode()      # 42.0 N, 76.75 W
    (folder / "mask.json").write_bytes(raw)
    entry = {"product_id": "nsrdb-GOES-tmy-v4-0-0", "selector": "tdy-2023", "selector_kind": "published_name",
             "mask_path": "mask.json", "mask_sha256": hashlib.sha256(raw).hexdigest(), "step_degrees": 0.25}
    (folder / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    coverage = nsrdb_coverage(tmp_path)
    assert coverage and coverage.where(42.1, -76.6) == "inside" and coverage.where(1.29, 103.85) == "outside"
    entry["mask_sha256"] = "0" * 64
    (folder / "manifest.json").write_text(json.dumps({"entries": [entry]}), encoding="utf-8")
    assert nsrdb_coverage(tmp_path) is None
