"""Catalog generations activate atomically and retain a usable snapshot."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest

from openepw.availability import (
    ActualScope,
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    ProductRecord,
    SiteRecord,
    WeatherAvailabilityQuery,
)
from openepw.availability.store import CatalogImportError, CatalogStore
from openepw.config import RuntimeConfig
from openepw.models import Location, WeatherRequest
from openepw.providers.http import HttpClient


def bundle():
    return CatalogBundle(
        evidence=[EvidenceRef(id="inventory", sha256="a" * 64,
                              retrieved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
                              basis="inventory")],
        products=[ProductRecord(id="noaa:isd", provider="noaa", dataset="isd",
                                spatial_kind="station", temporal_kind="actual",
                                adapter_variables=["dry_bulb"], evidence_ids=["inventory"])],
        sites=[SiteRecord(id="A00002-00001", product_id="noaa:isd", lat=42, lon=-76,
                          evidence_ids=["inventory"])],
        entries=[AvailabilityEntry(id="year-2024", product_id="noaa:isd",
                                   site_id="A00002-00001", scope=ActualScope(years=[2024]),
                                   evidence_basis="inventory", evidence_ids=["inventory"])],
    )


def test_failed_stage_keeps_previous_generation(tmp_path):
    store = CatalogStore(tmp_path)
    first = store.stage(bundle())
    store.activate(first.generation_id)
    bad = bundle().model_copy(deep=True)
    bad.entries.append(bad.entries[0])
    with pytest.raises(CatalogImportError):
        store.stage(bad)
    assert store.active().snapshot.generation_id == first.generation_id
    assert len(store.active().bundle.entries) == 1


def test_pinned_view_survives_later_activation(tmp_path):
    store = CatalogStore(tmp_path)
    first = store.stage(bundle())
    store.activate(first.generation_id)
    pinned = store.active()
    revised = bundle().model_copy(deep=True)
    revised.entries[0].scope = ActualScope(years=[2025])
    second = store.stage(revised)
    store.activate(second.generation_id)
    assert pinned.bundle.entries[0].scope.years == [2024]
    assert store.active().bundle.entries[0].scope.years == [2025]


def test_refresh_never_does_not_call_http(tmp_path):
    from openepw.availability.refresh import refresh_if_relevant

    class ForbiddenHttp:
        def request(self, *args, **kwargs):
            raise AssertionError("network called")

    store = CatalogStore(tmp_path)
    snapshot = store.stage(bundle())
    store.activate(snapshot.generation_id)
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2024]))
    assert refresh_if_relevant(query, store, ForbiddenHttp(), {"inventory"},
                               lambda *args: bundle()) == []
    assert store.active().snapshot.generation_id == snapshot.generation_id


def test_conditional_metadata_request_accepts_not_modified(tmp_path):
    http = HttpClient(RuntimeConfig(data_root=tmp_path), transport=httpx.MockTransport(
        lambda request: httpx.Response(304, headers={"ETag": '"same"'})))
    body, headers, status = http.request("GET", "https://example.org/inventory",
                                         allow_not_modified=True, max_retries=0)
    assert (body, status) == (b"", 304)
    assert headers["etag"] == '"same"'


def test_if_needed_skips_fresh_metadata(tmp_path):
    from openepw.availability.refresh import refresh_if_relevant

    class ForbiddenHttp:
        def request(self, *args, **kwargs):
            raise AssertionError("fresh metadata triggered network")

    current = bundle()
    current.evidence[0].retrieved_at = datetime.now(timezone.utc)
    current.evidence[0].source_url = "https://example.org/inventory"
    store = CatalogStore(tmp_path)
    staged = store.stage(current)
    store.activate(staged.generation_id)
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2024]), refresh="if_needed")
    assert refresh_if_relevant(query, store, ForbiddenHttp(), {"inventory"},
                               lambda *args: bundle()) == []


def test_refresh_one_source_retains_unrelated_catalog_records(tmp_path):
    from openepw.availability.refresh import refresh_if_relevant

    existing = bundle()
    existing.evidence[0].retrieved_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    existing.evidence[0].source_url = "https://example.org/inventory"
    existing.evidence.append(EvidenceRef(id="other", sha256="b" * 64,
                                         retrieved_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                                         basis="documentation"))
    existing.products.append(ProductRecord(id="other:product", provider="other",
                                           dataset="product", temporal_kind="actual",
                                           evidence_ids=["other"]))
    store = CatalogStore(tmp_path)
    staged = store.stage(existing)
    store.activate(staged.generation_id)

    class ChangedHttp:
        def request(self, *args, **kwargs):
            return b"new inventory", {"ETag": '"new"'}, 200

    def normalize(source_id, body, evidence):
        updated = bundle()
        updated.entries[0].scope = ActualScope(years=[2025])
        return updated

    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2025]), refresh="if_needed")
    assert refresh_if_relevant(query, store, ChangedHttp(), {"inventory"}, normalize) == []
    active = store.active()
    assert {p.id for p in active.bundle.products} == {"noaa:isd", "other:product"}
    assert active.bundle.entries[0].scope.years == [2025]


def test_concurrent_refresh_calls_share_one_source_check(tmp_path):
    from openepw.availability.refresh import refresh_if_relevant

    existing = bundle()
    existing.evidence[0].retrieved_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    existing.evidence[0].source_url = "https://example.org/inventory"
    store = CatalogStore(tmp_path)
    staged = store.stage(existing)
    store.activate(staged.generation_id)
    query = WeatherAvailabilityQuery(request=WeatherRequest(
        locations=Location(lat=42, lon=-76), years=[2025]), refresh="if_needed")

    class CountingHttp:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()

        def request(self, *args, **kwargs):
            with self.lock:
                self.calls += 1
            time.sleep(0.05)
            return b"new inventory", {}, 200

    http = CountingHttp()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(refresh_if_relevant, query, store, http, {"inventory"},
                            lambda *args: bundle()) for _ in range(2)]
        assert [job.result() for job in jobs] == [[], []]
    assert http.calls == 1
