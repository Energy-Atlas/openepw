"""The indexed nearest-site search picks exactly what the full scan picked."""

import random
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
from openepw.availability.evaluate import _distance, evaluate
from openepw.availability.store import CatalogView
from openepw.models import Location, WeatherRequest


def _bundle(seed: int) -> CatalogBundle:
    rng = random.Random(seed)
    evidence = [EvidenceRef(id="inventory", sha256="a" * 64, basis="inventory",
                            retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc))]
    products = [ProductRecord(id="noaa:isd", provider="noaa", dataset="ISD global-hourly", spatial_kind="station",
                              temporal_kind="actual", adapter_variables=["dry_bulb"], evidence_ids=["inventory"])]
    sites, entries = [], []
    for index in range(900):                     # clustered stations plus a few far ones and poles
        lat = max(-89.9, min(89.9, rng.gauss(40, 12) if index % 9 else rng.uniform(-89.9, 89.9)))
        lon = ((rng.gauss(-90, 25) if index % 7 else rng.uniform(-180, 180)) + 180) % 360 - 180
        status = "approximate_locality" if index % 23 == 0 else "published"
        sites.append(SiteRecord(id=f"S{index:04d}", product_id="noaa:isd", lat=round(lat, 2), lon=round(lon, 2),
                                position_status=status, evidence_ids=["inventory"]))
        years = [2018] if index % 3 else [2017]
        entries.append(AvailabilityEntry(id=f"e{index}", product_id="noaa:isd", site_id=f"S{index:04d}",
                                         scope=ActualScope(years=years), evidence_basis="inventory",
                                         evidence_ids=["inventory"]))
    for index in range(400):                     # one-site OneBuilding products
        product_id = f"ob:{index:04d}"
        products.append(ProductRecord(id=product_id, provider="onebuilding", dataset="OneBuilding published EPW",
                                      native_product_id=f"https://climate.onebuilding.org/X_{index}_TMYx.zip",
                                      spatial_kind="station", temporal_kind="tmy_reference",
                                      adapter_variables=["dry_bulb"], evidence_ids=["inventory"]))
        lat, lon = rng.uniform(-60, 70), rng.uniform(-180, 180)
        sites.append(SiteRecord(id=f"O{index:04d}", product_id=product_id, lat=round(lat, 2), lon=round(lon, 2),
                                position_status="conflicted" if index % 31 == 0 else "published",
                                evidence_ids=["inventory"]))
        entries.append(AvailabilityEntry(id=f"o{index}", product_id=product_id, site_id=f"O{index:04d}",
                                         scope=TMYReferenceScope(product_label="TMYx"), evidence_basis="inventory",
                                         evidence_ids=["inventory"]))
    return CatalogBundle(evidence=evidence, products=products, sites=sites, entries=entries)


def _reference_noaa(location, sites, entries_by_site, years):
    """The previous full scan in _candidate_sites for NOAA."""
    known = [(d, s) for s in sites if (d := _distance(location, s)) is not None
             and s.position_status not in ("approximate_locality", "conflicted")]
    known.sort(key=lambda item: (item[0], item[1].id))
    nearby = [(d, s) for d, s in known if d <= 100]
    listed = [(d, s) for d, s in nearby if any(set(years) <= set(e.scope.years)
                                               for e in entries_by_site.get(("noaa:isd", s.id), []))]
    supported = {s.id for _, s in listed[:5]}
    chosen = [s for _, s in listed[:5]] + [s for _, s in nearby if s.id not in supported][:3]
    return [s.id for s in chosen] if chosen else [s.id for _, s in known[:5]]


def _reference_onebuilding(location, bundle):
    nearby = [(d, s.product_id) for s in bundle.sites if s.product_id.startswith("ob:")
              and (d := _distance(location, s)) is not None
              and s.position_status not in ("approximate_locality", "conflicted")]
    nearby.sort()
    return {product_id for _, product_id in nearby[:20]}


def test_indexed_candidates_match_the_full_scan():
    rng = random.Random(7)
    points = [Location(lat=40, lon=-90), Location(lat=89.5, lon=10), Location(lat=-89.5, lon=-170),
              Location(lat=10, lon=179.9), Location(lat=10, lon=-179.9), Location(lat=-45, lon=60)]
    points += [Location(lat=round(rng.uniform(-80, 80), 3), lon=round(rng.uniform(-180, 180), 3)) for _ in range(30)]
    for seed in (1, 2):
        bundle = _bundle(seed)
        view = CatalogView(CatalogSnapshotRef(generation_id=f"g{seed}", created_at=datetime.now(timezone.utc)), bundle)
        entries_by_site = {}
        for entry in bundle.entries:
            entries_by_site.setdefault((entry.product_id, entry.site_id), []).append(entry)
        noaa_sites = [s for s in bundle.sites if s.product_id == "noaa:isd"]
        for point in points:
            historical = evaluate(WeatherAvailabilityQuery(request=WeatherRequest(locations=point, years=[2018])), view)
            got = [option.site.id for option in historical.options if option.product.provider == "noaa"]
            assert got == _reference_noaa(point, noaa_sites, entries_by_site, [2018]), point
            typical = evaluate(WeatherAvailabilityQuery(request=WeatherRequest(locations=point, product="tmy")), view)
            chosen = {option.product.id for option in typical.options if option.product.provider == "onebuilding"}
            assert chosen == _reference_onebuilding(point, bundle), point
            for option in historical.options:
                if option.site is not None:
                    assert option.distance_km == _distance(point, option.site)       # same distances
