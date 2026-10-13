"""What availability assessment and the map read from a catalog, without holding all of it.

A catalog generation of 2026.10.13 has 73,403 products, 106,991 sites and 99,438 entries; as
validated records they took about 900 MB, most of it OneBuilding's published files and NOAA's
stations. An assessment reads only a few dozen of them per location (the 20 nearest published
files, the stations within 100 km), so for those two providers the server keeps positions,
ids and the map's points in compact form and reads full records from SQLite by id when they
are needed, through a small cache. Every other provider is held in full.

``CatalogIndex`` serves a catalog held in memory (synthetic tests, bundled contracts, a small
catalog); ``StoreCatalogIndex`` serves a stored generation. Both give the same answers.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from openepw.models import Location

from .models import (
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    FutureAvailabilityQuery,
    ProductRecord,
    ReviewAnnotation,
    SiteRecord,
)

LAZY_PROVIDERS = ("onebuilding", "noaa")
SITE = "https://climate.onebuilding.org/"                # every published OneBuilding file is here
BROAD = ("approximate_locality", "conflicted")      # positions too rough for a distance


def distance_km(a: Location, b: SiteRecord) -> float | None:
    if b.lat is None or b.lon is None:
        return None
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


def positioned(lat: float | None, lon: float | None, status: str | None) -> bool:
    return lat is not None and lon is not None and status not in BROAD


class SiteIndex:
    """Positioned sites as radian arrays, for a fast first pass before the exact distances;
    only the sites that pass are materialised."""

    def __init__(self, lat: Sequence[float], lon: Sequence[float],
                 load: Callable[[list[int]], list[SiteRecord]]):
        self.size = len(lat)
        self.lat = np.radians(np.asarray(lat, dtype=float))
        self.lon = np.radians(np.asarray(lon, dtype=float))
        self._load = load

    @classmethod
    def of(cls, sites: Iterable[SiteRecord]) -> SiteIndex:
        kept = [site for site in sites if positioned(site.lat, site.lon, site.position_status)]
        return cls([site.lat for site in kept], [site.lon for site in kept],   # type: ignore[misc]
                   lambda indices: [kept[index] for index in indices])

    def nearest(self, location: Location, *, count: int | None = None, radius: float | None = None,
                key=lambda site: site.id) -> list[tuple[float, SiteRecord]]:
        """The nearest sites by exact distance, ordered by (distance, key), as a full scan would.

        The vectorised haversine only chooses candidates, with a small margin; each candidate's
        distance is then recomputed with ``distance_km``, so values and order are unchanged.
        """
        if not self.size:
            return []
        lat1 = math.radians(location.lat)
        dlon = self.lon - math.radians(location.lon)
        h = np.sin((self.lat - lat1) / 2) ** 2 + math.cos(lat1) * np.cos(self.lat) * np.sin(dlon / 2) ** 2
        rough = 6371.0 * 2 * np.arcsin(np.minimum(1.0, np.sqrt(h)))
        limit = np.inf if radius is None else radius
        if count is not None and count < self.size:
            limit = min(limit, float(np.partition(rough, count - 1)[count - 1]))
        picked = self._load(np.flatnonzero(rough <= limit + 1e-6).tolist())
        exact = [(distance, site) for site in picked if (distance := distance_km(location, site)) is not None
                 and (radius is None or distance <= radius)]
        exact.sort(key=lambda item: (item[0], key(item[1])))
        return exact[:count] if count is not None else exact


class CatalogIndex:
    """Lookups over a catalog held in memory, built once per catalog."""

    def __init__(self, bundle: CatalogBundle):
        self.evidence: list[EvidenceRef] = bundle.evidence
        self.reviews: list[ReviewAnnotation] = bundle.reviews
        self._products = bundle.products
        self._product_by_id = {product.id: product for product in bundle.products}
        self._sites: dict[str, list[SiteRecord]] = {}
        self._site_by_id: dict[str, SiteRecord] = {}
        self._entries: dict[tuple[str, str | None], list[AvailabilityEntry]] = {}
        for site in bundle.sites:
            self._sites.setdefault(site.product_id, []).append(site)
            self._site_by_id[site.id] = site
        for entry in bundle.entries:
            self._entries.setdefault((entry.product_id, entry.site_id), []).append(entry)
        published = {product.id for product in bundle.products if product.provider == "onebuilding"}
        self.published = SiteIndex.of(site for site in bundle.sites if site.product_id in published)
        self._indexes: dict[str, SiteIndex] = {}
        self._bundle = bundle

    def products_for(self, query, selected_published: set[str] | None) -> list[ProductRecord]:
        """The products an assessment considers, in catalog order; published files only when
        selected (the nearest) or named."""
        return [product for product in self._products if product.provider != "onebuilding"
                or selected_published is None or product.id in selected_published]

    def product(self, product_id: str) -> ProductRecord | None:
        return self._product_by_id.get(product_id)

    def has_sites(self, product_id: str) -> bool:
        return bool(self._sites.get(product_id))

    def first_site(self, product_id: str) -> SiteRecord | None:
        sites = self._sites.get(product_id)
        return sites[0] if sites else None

    def site(self, site_id: str) -> SiteRecord | None:
        return self._site_by_id.get(site_id)

    def site_index(self, product_id: str) -> SiteIndex:
        if product_id not in self._indexes:
            self._indexes[product_id] = SiteIndex.of(self._sites.get(product_id, []))
        return self._indexes[product_id]

    def entries(self, product_id: str, site_id: str | None) -> list[AvailabilityEntry]:
        return self._entries.get((product_id, site_id), [])

    def scope_products(self) -> list[ProductRecord]:
        """Every product (the scope list keeps one row per footprint)."""
        return list(self._products)

    def providers(self) -> set[str]:
        return {product.provider for product in self._products}

    def map_parts(self) -> tuple[list[ProductRecord], list[SiteRecord], list[AvailabilityEntry], dict]:
        """Products, sites and entries the map draws in full, and the map's site points."""
        from .map_layers import site_points

        return (self._products, self._bundle.sites, self._bundle.entries,
                site_points(self._products, self._bundle.sites, self._bundle.entries))


class _Cache(OrderedDict):
    def __init__(self, size: int):
        super().__init__()
        self.size = size

    def remember(self, key, value):
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.size:
            self.popitem(last=False)
        return value


class StoreCatalogIndex(CatalogIndex):
    """A stored generation: OneBuilding and NOAA records are read from SQLite when needed.

    Building the index streams the whole generation once (about 3 s for 2026.10.13). Its
    result is a plain JSON state, saved as ``index.json`` in ``derived`` when a folder is
    given, so a later start reads that file instead; the install step writes it in advance.
    """

    FORMAT = 1

    def __init__(self, database: Path, generation_id: str, derived: Path | None = None):
        self.database, self.generation_id = Path(database), generation_id
        self._cache: _Cache = _Cache(8192)
        path = derived / "index.json" if derived is not None else None
        state = _read_state(path, generation_id, self.FORMAT) if path is not None else None
        if state is None:
            state = self._build_state()
            if path is not None:
                _write_json(path, state)
        self._restore(state)

    def _build_state(self) -> dict:
        """Everything the index keeps, as plain JSON, from one pass over the generation."""
        from .map_layers import SitePoints
        from .store import _TABLES

        kinds = dict(_TABLES)
        state: dict[str, Any] = {"format": self.FORMAT, "generation_id": self.generation_id,
                                 "products": [], "sites": [], "entries": [], "lazy_order": [],
                                 "lazy_info": {}, "references": {}, "site_rows": {}}
        with self._connect() as db:
            def rows(table):
                return db.execute(f"SELECT body FROM {table} WHERE generation_id = ? ORDER BY id",
                                  (self.generation_id,))

            state["evidence"] = [json.loads(body) for (body,) in rows("evidence")]
            state["reviews"] = [json.loads(body) for (body,) in rows("reviews")]
            # Only what the index needs is kept from each lazy product while streaming.
            lazy_info, references = state["lazy_info"], state["references"]
            representatives: dict[tuple[str, str], dict] = {}
            evidence_ids: set[str] = set()
            for (body,) in rows("products"):
                data = json.loads(body)
                if data["provider"] in LAZY_PROVIDERS:
                    native = data.get("native_product_id")
                    lazy_info[data["id"]] = [data["provider"], data["dataset"], native]
                    representatives.setdefault((data["provider"], data["dataset"]), data)
                    if data["provider"] == "onebuilding":
                        evidence_ids.update(data.get("evidence_ids", []))
                        references.setdefault(data["id"], data["id"])
                        if native:
                            if not native.startswith(SITE):
                                raise ValueError(f"Published file outside {SITE}: {native}")
                            references.setdefault(native, data["id"])
                    if data["provider"] == "noaa":        # one product: kept, like the others
                        state["products"].append(data)
                    else:
                        state["lazy_order"].append(data["id"])
                else:
                    state["products"].append(data)
            state["representatives"] = list(representatives.values())
            state["lazy_evidence"] = sorted(evidence_ids)
            # Sites: in full for the other providers; positions and ids for the lazy ones.
            map_sites: dict[str, tuple] = {}             # id -> lat, lon, name, position status
            for (body,) in rows("sites"):
                data = json.loads(body)
                if data["product_id"] in lazy_info:
                    state["site_rows"].setdefault(data["product_id"], []).append(
                        [data["id"], data.get("lat"), data.get("lon"), data.get("position_status")])
                    map_sites[data["id"]] = (data.get("lat"), data.get("lon"), data.get("name"),
                                             data.get("position_status"))
                else:
                    state["sites"].append(data)
            # Entries: in full for the other providers; ids by (product, site) for the lazy ones.
            entry_ids: dict[tuple[str, str | None], list[str]] = {}
            points = SitePoints()
            for (body,) in rows("entries"):
                data = json.loads(body)
                product_id = data["product_id"]
                if product_id in lazy_info:
                    entry_ids.setdefault((product_id, data.get("site_id")), []).append(data["id"])
                    place = map_sites.get(data.get("site_id") or "")
                    if place is not None:
                        provider, _, native = lazy_info[product_id]
                        site = dict(zip(("lat", "lon", "name", "position_status"), place))
                        points.add(provider, kinds["entries"].model_validate(data), site, native,
                                   data.get("site_id"))
                else:
                    state["entries"].append(data)
            state["entry_ids"] = [[product_id, site_id, ids] for (product_id, site_id), ids in entry_ids.items()]
        state["points"] = points.result()
        return state

    def _restore(self, state: dict) -> None:
        from .store import _TABLES

        kinds = dict(_TABLES)
        self.evidence = [EvidenceRef.model_validate(item) for item in state["evidence"]]
        self.reviews = [ReviewAnnotation.model_validate(item) for item in state["reviews"]]
        self._products = [kinds["products"].model_validate(item) for item in state["products"]]
        self._product_by_id = {product.id: product for product in self._products}
        self._lazy_order: list[str] = state["lazy_order"]
        self._lazy_info: dict[str, tuple[str, str, str | None]] = {
            key: tuple(value) for key, value in state["lazy_info"].items()}   # type: ignore[misc]
        self._references: dict[str, str] = state["references"]
        self._representatives: dict[tuple[str, str], dict] = {
            (data["provider"], data["dataset"]): data for data in state["representatives"]}
        self._lazy_evidence: list[str] = state["lazy_evidence"]
        self._sites: dict[str, list[SiteRecord]] = {}
        self._site_by_id: dict[str, SiteRecord] = {}
        for item in state["sites"]:
            site = kinds["sites"].model_validate(item)
            self._sites.setdefault(site.product_id, []).append(site)
            self._site_by_id[site.id] = site
        self._site_rows: dict[str, list[tuple[str, float | None, float | None, str | None]]] = {
            key: [tuple(row) for row in rows] for key, rows in state["site_rows"].items()}  # type: ignore[misc]
        self._site_product: dict[str, str] = {row[0]: key for key, rows in self._site_rows.items()
                                              for row in rows}
        self._entries: dict[tuple[str, str | None], list[AvailabilityEntry]] = {}
        self._full_entries: list[AvailabilityEntry] = []
        for item in state["entries"]:
            entry = kinds["entries"].model_validate(item)
            self._entries.setdefault((entry.product_id, entry.site_id), []).append(entry)
            self._full_entries.append(entry)
        self._entry_ids: dict[tuple[str, str | None], list[str]] = {
            (product_id, site_id): ids for product_id, site_id, ids in state["entry_ids"]}
        self._points = state["points"]
        published = [row for pid in self._lazy_order for row in self._site_rows.get(pid, [])
                     if positioned(row[1], row[2], row[3])]
        self.published = SiteIndex([row[1] for row in published], [row[2] for row in published],  # type: ignore[misc]
                                   lambda indices: self._load_sites([published[i][0] for i in indices]))
        self._indexes = {}

    def _connect(self):
        db = sqlite3.connect(f"file:{self.database.as_posix()}?mode=ro", uri=True, timeout=10,
                             check_same_thread=False)
        db.execute("PRAGMA busy_timeout = 10000")
        return _Closing(db)

    def _load(self, table: str, ids: list[str]) -> dict[str, Any]:
        from .store import _TABLES

        kind = dict(_TABLES)[table]
        found = {key: self._cache[(table, key)] for key in ids if (table, key) in self._cache}
        missing = [key for key in ids if key not in found]
        if missing:
            with self._connect() as db:
                for start in range(0, len(missing), 500):
                    chunk = missing[start:start + 500]
                    marks = ",".join("?" * len(chunk))
                    for key, body in db.execute(
                            f"SELECT id, body FROM {table} WHERE generation_id = ? AND id IN ({marks})",
                            (self.generation_id, *chunk)):
                        found[key] = self._cache.remember((table, key), kind.model_validate_json(body))
        return found

    def _load_sites(self, ids: list[str]) -> list[SiteRecord]:
        found = self._load("sites", ids)
        return [found[key] for key in ids if key in found]

    def products_for(self, query, selected_published: set[str] | None) -> list[ProductRecord]:
        if isinstance(query, FutureAvailabilityQuery):
            chosen: list[str] = []                       # published files are not future windows
        elif query.request.product_id:
            # A file named by its URL, its path on the site or its id (as _relevant_product);
            # every published URL starts with the site's address (checked when building the index).
            reference = query.request.product_id
            found = (self._references.get(reference)
                     or self._references.get(SITE + reference))
            chosen = [found] if found else []
        else:
            chosen = sorted(selected_published or ())
        loaded = self._load("products", chosen)
        merged = self._products + [loaded[pid] for pid in chosen if pid in loaded]
        return sorted(merged, key=lambda product: product.id)

    def product(self, product_id: str) -> ProductRecord | None:
        if product_id in self._product_by_id:
            return self._product_by_id[product_id]
        return self._load("products", [product_id]).get(product_id) if product_id in self._lazy_info else None

    def has_sites(self, product_id: str) -> bool:
        return bool(self._sites.get(product_id) or self._site_rows.get(product_id))

    def first_site(self, product_id: str) -> SiteRecord | None:
        if product_id in self._sites:
            return self._sites[product_id][0]
        rows = self._site_rows.get(product_id)
        return self._load_sites([rows[0][0]])[0] if rows else None

    def site(self, site_id: str) -> SiteRecord | None:
        if site_id in self._site_by_id:
            return self._site_by_id[site_id]
        return self._load_sites([site_id])[0] if site_id in self._site_product else None

    def site_index(self, product_id: str) -> SiteIndex:
        if product_id not in self._indexes:
            if product_id in self._site_rows:
                rows = [row for row in self._site_rows[product_id] if positioned(row[1], row[2], row[3])]
                ids = [row[0] for row in rows]

                def load(indices: list[int], ids: list[str] = ids) -> list[SiteRecord]:
                    return self._load_sites([ids[i] for i in indices])

                self._indexes[product_id] = SiteIndex(
                    [row[1] for row in rows], [row[2] for row in rows], load)  # type: ignore[misc]
            else:
                self._indexes[product_id] = SiteIndex.of(self._sites.get(product_id, []))
        return self._indexes[product_id]

    def entries(self, product_id: str, site_id: str | None) -> list[AvailabilityEntry]:
        ids = self._entry_ids.get((product_id, site_id))
        if ids is None:
            return self._entries.get((product_id, site_id), [])
        found = self._load("entries", ids)
        return [found[key] for key in ids if key in found]

    def scope_products(self) -> list[ProductRecord]:
        from .store import _TABLES

        kind = dict(_TABLES)["products"]
        return sorted(self._products + [kind.model_validate(data) for data in self._representatives.values()
                                        if data["provider"] != "noaa"], key=lambda product: product.id)

    def providers(self) -> set[str]:
        return {product.provider for product in self._products} | {info[0] for info in self._lazy_info.values()}

    def map_parts(self) -> tuple[list[ProductRecord], list[SiteRecord], list[AvailabilityEntry], dict]:
        # One product stands for the published files; it carries all their evidence for the dates.
        products = [product.model_copy(update={"evidence_ids": self._lazy_evidence})
                    if product.provider == "onebuilding" else product for product in self.scope_products()]
        sites = [site for group in self._sites.values() for site in group]
        return products, sites, self._full_entries, self._points


class _Closing:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        self.db.close()


# Indexes of catalogs held in memory: the most recent two (a pinned or previous generation).
_INDEXES: list[tuple[CatalogBundle, CatalogIndex]] = []


def index_for(bundle: CatalogBundle) -> CatalogIndex:
    for cached, index in _INDEXES:
        if cached is bundle:
            return index
    index = CatalogIndex(bundle)
    _INDEXES[:] = [(bundle, index), *_INDEXES[:1]]
    return index


def _read_state(path: Path, generation_id: str, version: int) -> dict | None:
    """A saved index state, if it is for this generation and this format."""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("format") != version or state.get("generation_id") != generation_id:
        return None
    return state


def _write_json(path: Path, value: Any) -> None:
    """Atomic: a reader sees the old file or the complete new one; an unwritable folder only
    means the next start builds the index again."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass
