# MCP agent chat — P1 service moves and MCP contract — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the openepw MCP server fit for a tool-calling agent: product offers and location review live in the service and have MCP tools, tools publish real schemas, errors name fields, results split into a short model summary and full structured data, submission needs a person's confirmation through MCP elicitation, and one job runner serves each data root.

**Architecture:** Product-offer and standard-time logic move from `openepw.chat` into `openepw.availability.products` and `openepw.planning.offsets`, exposed as `WeatherService` methods. The FastMCP server in `openepw.mcp.server` is rewritten around four small support modules (`schemas`, `summaries`, `descriptions`, `approval`) and accepts a shared `JobRunner`. The existing web coordinator and console harness keep working on the moved functions until P5 retires them.

**Tech Stack:** Python 3.11/3.13, pydantic v2, MCP Python SDK 1.30 (`FastMCP`, `Context.elicit`, in-memory transport), FastAPI, pytest, ruff, mypy.

**Spec:** [unified MCP agent chat design](../specs/2026-10-05-mcp-agent-chat-design.md), sections 3 (server-side approval) and 5. [ADR 0005](../../decisions/0005-mcp-agent-chat.md).

## Global Constraints

- Branch `feature/mcp-agent-chat`. Do not modify `deploy/staging`, `feature/account-login` or `feature/chat-ui`.
- Commit messages: `fix(topic): concise description`, normal configured human authorship, **no** agent or model co-author trailers (AGENTS.md).
- Python must run on 3.11 and 3.13 (CI matrix); no 3.12-only syntax.
- The scientific/data core (`openepw.models`, `openepw.availability`, `openepw.planning`, `openepw.service`) must not import FastAPI, MCP or xarray.
- `mcp>=1.30,<2` in both the `mcp` and `harness` extras (elicitation and `CallToolResult` passthrough were verified on 1.30.0).
- Tool error payload: `{code, message, retryable}` plus optional `details: [{loc, msg}]` (validation) or `correlation_id` (internal). Never include secrets, local paths or raw input values.
- Supported/listed means eligible to try retrieval; never claim `simulation_ready=true`. Future weather stays suspended.
- Windows commands use `.venv/Scripts/python.exe`; they also work from Git Bash.
- Deferred from spec §5 to P4: mounting streamable HTTP at `/mcp` (only needed for external clients; the agent uses the in-memory transport).

## File structure

| File | Responsibility |
| --- | --- |
| `src/openepw/availability/products.py` (create) | Named downloadable products and their catalog availability (moved from `chat/products.py`) |
| `src/openepw/chat/products.py` (modify) | Compatibility re-export until P5 |
| `src/openepw/planning/offsets.py` (create) | Fixed standard-time offsets, request points, standard-time note, location key |
| `src/openepw/service.py` (modify) | `review_locations`, `product_offers`, `point_availability`; `locations` delegates |
| `src/openepw/chat/coordinator.py` (modify) | Use moved functions; record `approved_via="chat"` |
| `src/openepw/api/app.py` (modify) | Point availability via service; `approved_via="api"`; shared MCP server on `app.state` |
| `src/openepw/mcp/schemas.py` (create) | Inlined JSON schemas for dict-typed tool parameters |
| `src/openepw/mcp/summaries.py` (create) | Short model-facing text summary per tool |
| `src/openepw/mcp/descriptions.py` (create) | Tool descriptions and server instructions |
| `src/openepw/mcp/approval.py` (create) | Submit confirmation (server) and approval callback (client) |
| `src/openepw/mcp/access.py` (create) | Which tools a model may call, which the host calls, which are legacy |
| `src/openepw/mcp/server.py` (rewrite, then modify) | Tool registration over the service and shared runner |
| `src/openepw/jobs/lock.py` (create) | One job runner per data root across processes |
| `src/openepw/jobs/worker.py`, `jobs/store.py`, `models/__init__.py` (modify) | `approved_via` on jobs; lock in `recover`/`close` |
| `src/openepw/harness/{mcp_client,trace,agent}.py` (modify) | Legacy console keeps submitting by answering the confirmation |
| `tests/unit/mcp_memory.py` (create) | In-memory MCP session helper for tests |

---

### Task 1: Product offers move into the availability layer and service

**Files:**
- Create: `src/openepw/availability/products.py`
- Modify: `src/openepw/chat/products.py` (becomes a re-export)
- Modify: `src/openepw/chat/coordinator.py:24` and `:567`
- Modify: `src/openepw/service.py` (add two methods)
- Modify: `src/openepw/api/app.py:189-208`
- Move: `tests/unit/test_chat_products.py` → `tests/unit/test_availability_products.py`
- Modify: `tests/unit/test_api.py:290-299`

**Interfaces:**
- Produces: `openepw.availability.products.product_offers(service, locations, *, kind=None, provider=None, years=None, today=None) -> dict`; `point_availability(service, lat, lon, years=None, *, today=None) -> dict`; `product_for(choice_id) -> Product | None`; `WeatherService.product_offers(locations, *, product=None, provider=None, years=None) -> dict`; `WeatherService.point_availability(lat, lon, years=None) -> dict`.

- [ ] **Step 1: Move the test file and switch it to the new signature**

```bash
git mv tests/unit/test_chat_products.py tests/unit/test_availability_products.py
```

Apply these exact replacements in `tests/unit/test_availability_products.py`:

| Old | New |
| --- | --- |
| `from openepw.chat.products import product_for, product_offers` | `from openepw.availability.products import point_availability, product_for, product_offers` |
| `offers = product_offers(catalog, ITHACA, {}, today=date(2026, 9, 27))` | `offers = product_offers(catalog, ITHACA, today=date(2026, 9, 27))` |
| `offers = product_offers(Catalog(), ITHACA, {"years": [2018]})` | `offers = product_offers(Catalog(), ITHACA, years=[2018])` |
| `tmyx = product_offers(Catalog(), ITHACA, {"product": "tmyx"})` | `tmyx = product_offers(Catalog(), ITHACA, kind="tmyx")` |
| `nsrdb = product_offers(Catalog(), ITHACA, {"product": "historical", "provider": "NSRDB"})` | `nsrdb = product_offers(Catalog(), ITHACA, kind="historical", provider="NSRDB")` |
| `two = product_offers(Catalog(), [ITHACA, {"lat": 40.0, "lon": -75.0}], {"product": "historical"})` | `two = product_offers(Catalog(), [ITHACA, {"lat": 40.0, "lon": -75.0}], kind="historical")` |
| `offers = product_offers(object(), ITHACA, {})` | `offers = product_offers(object(), ITHACA)` |
| `    from openepw.chat.products import point_availability` (inside the last test) | delete this line |

Append these tests to the same file:

```python
def test_service_offers_delegate_with_named_filters(tmp_path):
    from openepw.config import RuntimeConfig
    from openepw.service import WeatherService

    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    offers = service.product_offers(ITHACA, product="historical", provider="NSRDB", years=[2018])
    assert [option["id"] for option in offers["options"]] == ["nsrdb-actual"]
    point = service.point_availability(42.444, -76.5019, [2018])
    assert point["years"] == [2018] and {row["id"] for row in point["products"]} >= {"nsrdb-actual"}


def test_chat_module_still_reexports_the_moved_functions():
    from openepw.availability import products as moved
    from openepw.chat import products as legacy

    assert legacy.product_offers is moved.product_offers
    assert legacy.product_for is moved.product_for
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_availability_products.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.availability.products'`.

- [ ] **Step 3: Create `src/openepw/availability/products.py`**

```python
"""Named weather products and where each is available for the chosen locations.

Each choice names one downloadable product (provider, dataset and, for published files, the
file family). Availability comes from the offline catalog assessment only: a product is
"supported" or "unknown" at a location, excluded products are left out, and nothing is
inferred beyond what the catalog records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..models import DatasetSelection, WeatherRequest, published_variant
from .map_layers import onebuilding_station_name
from .models import WeatherAvailabilityQuery

# Map callouts are drawn for at most this many locations; the options still cover all.
MAX_CALLOUT_LOCATIONS = 25


@dataclass(frozen=True)
class Product:
    id: str
    product: str            # WeatherRequest.product
    provider: str
    dataset: str
    label: str              # the option label: names exactly what is downloaded
    tag: str                # the short map tag
    layer: str              # the catalog map layer that shows its coverage
    detail: str
    variant: str | None = None

    @property
    def actual(self) -> bool:
        return self.product == "historical"

    def selection(self) -> dict:
        return DatasetSelection(provider=self.provider, dataset=self.dataset,
                                variant=self.variant).model_dump(mode="json")


FIXED_PRODUCTS = (
    Product("era5-openmeteo", "historical", "openmeteo", "era5", "ERA5 actual year · Open-Meteo",
            "ERA5 · Open-Meteo", "era5", "25 km reanalysis grid, all EPW weather fields"),
    Product("era5-cds", "historical", "cds", "reanalysis-era5-single-levels",
            "ERA5 actual year · Copernicus CDS", "ERA5 · CDS", "era5",
            "Reanalysis grid from Copernicus; needs CDS terms; no DNI or DHI; requests queue at "
            "Copernicus one month at a time, so several years can take hours"),
    Product("era5land-openmeteo", "historical", "openmeteo", "era5_land",
            "ERA5-Land actual year · Open-Meteo", "ERA5-Land · Open-Meteo", "era5-land",
            "11 km land grid; temperature, humidity and pressure only"),
    Product("era5land-cds", "historical", "cds", "reanalysis-era5-land",
            "ERA5-Land actual year · Copernicus CDS", "ERA5-Land · CDS", "era5-land",
            "Land grid from Copernicus; needs CDS terms; no DNI or DHI; requests queue at Copernicus "
            "one month at a time, so several years can take hours"),
    Product("nsrdb-actual", "historical", "nsrdb", "nsrdb-GOES-aggregated-v4-0-0",
            "NSRDB actual year · GOES v4", "NSRDB actual year", "nsrdb",
            "4 km satellite solar grid, hourly; needs an NLR key"),
    Product("noaa-isd", "historical", "noaa", "ISD global-hourly", "NOAA ISD station observations",
            "NOAA ISD", "noaa", "Nearest reporting station; no solar radiation"),
    Product("nsrdb-tmy", "tmy", "nsrdb", "nsrdb-GOES-tmy-v4-0-0", "NSRDB TMY · latest release",
            "NSRDB TMY", "nsrdb", "4 km satellite typical year; needs an NLR key"),
    Product("pvgis-tmy", "tmy", "pvgis", "PVGIS TMY", "PVGIS TMY 5.3 · SARAH3", "PVGIS TMY", "pvgis",
            "Typical year from the PVGIS point service"),
)
STATION_LAYERS = {"noaa", "onebuilding"}
_ORDER = {product.id: index for index, product in enumerate(FIXED_PRODUCTS)}


def onebuilding_product(variant: str) -> Product:
    tmyx = variant.startswith("TMYx")
    return Product(f"onebuilding:{variant}", "tmyx" if tmyx else "published", "onebuilding",
                   "OneBuilding published EPW", f"OneBuilding {variant}", variant, "onebuilding",
                   "Published EPW file from the nearest listed station", variant)


def product_for(choice_id: str) -> Product | None:
    if choice_id.startswith("onebuilding:"):
        return onebuilding_product(choice_id.split(":", 1)[1])
    return next((product for product in FIXED_PRODUCTS if product.id == choice_id), None)


def _product_of(option) -> Product | None:
    record = option.product
    if record.provider == "onebuilding":
        variant = published_variant(record.native_product_id)
        return onebuilding_product(variant) if variant else None
    return next((product for product in FIXED_PRODUCTS if (product.provider, product.dataset)
                 == (record.provider, record.dataset)), None)


def _station(option) -> dict | None:
    site = option.site
    if site is None or site.lat is None or site.lon is None:
        return None
    name = site.name or onebuilding_station_name(option.product.native_product_id)
    return {"lat": site.lat, "lon": site.lon, "name": name,
            "distance_km": round(option.distance_km, 1) if option.distance_km is not None else None}


def _wanted(product: Product, kind: str | None, provider: str | None) -> bool:
    if provider and product.provider != str(provider).lower():
        return False
    if kind in ("historical", "amy"):
        return product.actual
    if kind == "tmyx":
        return product.provider == "onebuilding" and (product.variant or "").startswith("TMYx")
    if kind in ("tmy", "published"):
        return not product.actual
    return True


def product_offers(service, locations: Any, *, kind: str | None = None, provider: str | None = None,
                   years: list[int] | None = None, today: date | None = None) -> dict:
    """Options for the product choice plus per-location availability for the map."""
    years = list(years or [])
    years_assumed = not years
    if years_assumed:
        years = [(today or date.today()).year - 1]
    assessed: dict[str, dict[int, dict]] = {}     # product id -> occurrence -> best entry
    found: dict[str, Product] = {}
    assess = getattr(service, "assess_availability", None)
    points: list[dict] = []
    if assess is not None:
        for request_kind, kind_years in (("historical", years), ("tmy", [])):
            request = WeatherRequest.model_validate({"locations": locations, "product": request_kind,
                                                     "years": kind_years})
            result = assess(WeatherAvailabilityQuery(request=request))
            if not points:
                points = [assessment.requested_location.model_dump(mode="json")
                          for assessment in result.locations]
            for option in sorted(result.options, key=lambda item: item.rank or 10**6):
                status = option.eligibility.status
                product = _product_of(option)
                if status == "excluded" or product is None or product.actual != (request_kind == "historical"):
                    continue
                found[product.id] = product
                best = assessed.setdefault(product.id, {}).get(option.occurrence_index)
                if best is None or (best["status"] == "unknown" and status == "supported"):
                    entry = {"status": status}
                    if product.layer in STATION_LAYERS and (station := _station(option)):
                        entry["station"] = station
                    assessed[product.id][option.occurrence_index] = entry
    catalogued = bool(assessed)
    products = [product for product in (*FIXED_PRODUCTS, *sorted(
        (item for item in found.values() if item.provider == "onebuilding"), key=lambda item: item.id))
        if (product.id in assessed or not catalogued) and _wanted(product, kind, provider)]
    if not products:                          # a typed type or provider with nothing here
        products = [product for product in FIXED_PRODUCTS
                    if _wanted(product, kind, provider)] or list(FIXED_PRODUCTS)
    count = len(points)
    options = []
    for product in products:
        per_location = assessed.get(product.id, {})
        supported = sum(entry["status"] == "supported" for entry in per_location.values())
        unverified = sum(entry["status"] == "unknown" for entry in per_location.values())
        if not catalogued:
            where = "availability is checked when planning"
        elif count == 1:
            entry = next(iter(per_location.values()), {"status": "unknown"})
            station = entry.get("station")
            where = ("listed in the catalog" if entry["status"] == "supported"
                     else "not verified in the catalog; checked when planning")
            if station:
                where = f"{station['name'] or 'station'}" + (
                    f" · {station['distance_km']:g} km" if station["distance_km"] is not None else "") + (
                    "" if entry["status"] == "supported" else " · not verified")
        else:
            where = ""                                   # counted in the dialog's availability column
        options.append({"id": product.id, "label": product.label,
                        "detail": f"{product.detail} · {where}" if where else product.detail,
                        "group": "actual" if product.actual else "typical",
                        "available": supported, "unverified": unverified, "sites": count})
    options.sort(key=lambda option: (option["group"] != "actual", _ORDER.get(option["id"], len(_ORDER)),
                                     option["id"]))
    tags = []
    for index, point in enumerate(points[:MAX_CALLOUT_LOCATIONS]):
        entries = []
        for product in products:
            best = assessed.get(product.id, {}).get(index)
            if best:
                entries.append({"option": product.id, "layer": product.layer, "tag": product.tag,
                                "status": best["status"], **({"station": best["station"]}
                                                              if "station" in best else {})})
        tags.append({"index": index, "lat": point["lat"], "lon": point["lon"], "name": point.get("name"),
                     "products": entries})
    return {"options": options, "availability": {
        "years": years, "years_assumed": years_assumed, "locations": tags,
        "omitted_locations": max(0, count - MAX_CALLOUT_LOCATIONS)}}


def point_availability(service, lat: float, lon: float, years: list[int] | None = None, *,
                       today: date | None = None) -> dict:
    """Every named product at one point: "supported" (listed in the catalog), "unknown"
    (checked when planning) or "none" (not available here), with the station for station products."""
    offers = product_offers(service, {"lat": lat, "lon": lon}, years=years or [], today=today)
    availability = offers["availability"]
    here = availability["locations"][0]["products"] if availability["locations"] else []
    tags = {tag["option"]: tag for tag in here}
    catalogued = bool(availability["locations"])
    rows = []
    for option in offers["options"]:
        tag = tags.get(option["id"])
        row = {"id": option["id"], "label": option["label"], "group": option["group"],
               "status": tag["status"] if tag else "unknown" if not catalogued else "none"}
        if tag and "station" in tag:
            row["station"] = tag["station"]
        rows.append(row)
    listed = {row["id"] for row in rows}
    rows += [{"id": product.id, "label": product.label, "group": "actual" if product.actual else "typical",
              "status": "none"} for product in FIXED_PRODUCTS if product.id not in listed]
    rows.sort(key=lambda row: (row["group"] != "actual", _ORDER.get(row["id"], len(_ORDER)), row["id"]))
    return {"lat": lat, "lon": lon, "years": availability["years"],
            "years_assumed": availability["years_assumed"], "products": rows}
```

- [ ] **Step 4: Replace `src/openepw/chat/products.py` with a re-export**

```python
"""Compatibility re-export until the chat coordinator is retired (P5).

The product catalogue now lives in ``openepw.availability.products``.
"""

from ..availability.products import (
    FIXED_PRODUCTS,
    MAX_CALLOUT_LOCATIONS,
    STATION_LAYERS,
    Product,
    onebuilding_product,
    point_availability,
    product_for,
    product_offers,
)

__all__ = ["FIXED_PRODUCTS", "MAX_CALLOUT_LOCATIONS", "STATION_LAYERS", "Product",
           "onebuilding_product", "point_availability", "product_for", "product_offers"]
```

- [ ] **Step 5: Add the service methods**

In `src/openepw/service.py`, add these methods to `WeatherService` directly after `locations()`:

```python
    def product_offers(self, locations: Any, *, product: str | None = None,
                       provider: str | None = None, years: list[int] | None = None) -> dict:
        """Named downloadable products with catalog availability per location."""
        from .availability.products import product_offers

        return product_offers(self, locations, kind=product, provider=provider, years=years)

    def point_availability(self, lat: float, lon: float, years: list[int] | None = None) -> dict:
        """Every named product's catalog status at one point."""
        from .availability.products import point_availability

        return point_availability(self, lat, lon, years)
```

- [ ] **Step 6: Point the coordinator and API at the moved code**

In `src/openepw/chat/coordinator.py` replace line 24
`from .products import product_for, product_offers` with
`from ..availability.products import product_for, product_offers`, and replace line 567

```python
            offers = product_offers(self.service, request_location(facts), facts)
```

with

```python
            offers = product_offers(self.service, request_location(facts), kind=facts.get("product"),
                                    provider=facts.get("provider"), years=facts.get("years"))
```

In `src/openepw/api/app.py` inside `catalog_point`, delete the line `from ..chat import products` and replace
`point_cache[key] = products.point_availability(service, key[0], key[1], wanted)` with
`point_cache[key] = service.point_availability(key[0], key[1], wanted)`.

In `tests/unit/test_api.py` (`test_catalog_point_answers_repeat_places_from_a_cache`) replace

```python
    import openepw.chat.products as products

    calls = []
    real = products.point_availability

    def counted(*args, **kwargs):
        calls.append(args[1:3])
        return real(*args, **kwargs)

    monkeypatch.setattr(products, "point_availability", counted)
```

with

```python
    calls = []
    real = WeatherService.point_availability

    def counted(self, *args, **kwargs):
        calls.append(args[0:2])
        return real(self, *args, **kwargs)

    monkeypatch.setattr(WeatherService, "point_availability", counted)
```

- [ ] **Step 7: Run the product, API and chat tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_availability_products.py tests/unit/test_api.py tests/unit/test_chat_sessions.py tests/unit/test_chat_navigation.py -q`
Expected: all PASS.

- [ ] **Step 8: Lint and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: `All checks passed!`

```bash
git add src/openepw/availability/products.py src/openepw/chat/products.py src/openepw/chat/coordinator.py src/openepw/service.py src/openepw/api/app.py tests/unit/test_availability_products.py tests/unit/test_api.py
git commit -m "fix(availability): move named product offers into the service layer"
```

---

### Task 2: Location offset review moves into the planning layer and service

**Files:**
- Create: `src/openepw/planning/offsets.py`
- Modify: `src/openepw/chat/coordinator.py:115-150`
- Modify: `src/openepw/service.py` (`locations`, new `review_locations`)
- Test: `tests/unit/test_location_review.py`

**Interfaces:**
- Produces: `estimate_offsets(value) -> tuple[Any, dict | None, bool]`; `request_points(request: WeatherRequest) -> list[Location]`; `standard_time_note(points: list[Location], estimated: bool) -> str`; `location_key(value) -> str`; `WeatherService.review_locations(geography) -> dict` with keys `geography, sampling, offset_estimated, point_count, points, standard_time, key`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_location_review.py`

```python
"""Fixed standard-time offsets and the location review shown before planning."""

from openepw.config import RuntimeConfig
from openepw.models import BoundingBox, Location
from openepw.planning.offsets import estimate_offsets, location_key, standard_time_note
from openepw.service import WeatherService

AREA = BoundingBox(west=-76.6, east=-76.4, south=42.3, north=42.5).model_dump()


def test_missing_offsets_are_estimated_and_explicit_ones_kept():
    points, sampling, estimated = estimate_offsets([
        {"lat": 42.44, "lon": -76.5},
        {"lat": 42.44, "lon": -76.5, "standard_offset_minutes": 0},
    ])
    assert [point["standard_offset_minutes"] for point in points] == [-300, 0]
    assert sampling is None and estimated is True
    point, _, estimated = estimate_offsets({"lat": 1, "lon": 2, "standard_offset_minutes": 60})
    assert point["standard_offset_minutes"] == 60 and estimated is False


def test_an_area_samples_with_longitude_offsets():
    value, sampling, estimated = estimate_offsets(AREA)
    assert value == AREA and sampling == {"standard_offset": "longitude"} and estimated is True


def test_standard_time_note_names_offsets_and_estimation():
    note = standard_time_note([Location(lat=0, lon=-76.5, standard_offset_minutes=-300)], True)
    assert "UTC-05:00" in note and "no daylight-saving shift" in note
    assert "estimated from longitude" in note
    assert "estimated" not in standard_time_note([Location(lat=0, lon=0)], False)


def test_location_key_changes_when_the_geography_changes():
    assert location_key({"lat": 1, "lon": 2}) == location_key({"lon": 2, "lat": 1})
    assert location_key({"lat": 1, "lon": 2}) != location_key({"lat": 1, "lon": 3})


def test_service_review_returns_points_note_and_stable_key(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    first = service.review_locations({"lat": 42.44, "lon": -76.5, "name": "Ithaca"})
    assert first["points"][0]["standard_offset_minutes"] == -300
    assert first["offset_estimated"] is True and first["point_count"] == 1
    assert "UTC-05:00" in first["standard_time"] and first["sampling"] is None
    assert service.review_locations({"lat": 42.44, "lon": -76.5, "name": "Ithaca"})["key"] == first["key"]
    area = service.review_locations(AREA)
    assert area["sampling"]["standard_offset"] == "longitude" and area["point_count"] >= 1
    assert {point["standard_offset_minutes"] for point in area["points"]} == {-300}
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_location_review.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.planning.offsets'`.

- [ ] **Step 3: Create `src/openepw/planning/offsets.py`**

```python
"""Fixed standard-time offsets for requested points and the note shown before an actual-year run."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..models import Location, WeatherRequest, nominal_offset_minutes


def estimate_offsets(value: Any) -> tuple[Any, dict | None, bool]:
    """Choose a fixed offset for points that lack one; preserve supplied offsets.

    Returns the geography, the sampling override for an area (or None) and whether any
    offset was estimated from longitude.
    """
    if isinstance(value, list):
        points = [estimate_offsets(point) for point in value]
        return [point for point, _, _ in points], None, any(estimated for _, _, estimated in points)
    if isinstance(value, dict) and ("west" in value or value.get("type") == "Polygon"):
        return value, {"standard_offset": "longitude"}, True
    point = Location.model_validate(value)
    if "standard_offset_minutes" not in point.model_fields_set:
        local = point.model_copy(update={"standard_offset_minutes": nominal_offset_minutes(point.lon)})
        return local.model_dump(mode="json"), None, True
    return point.model_dump(mode="json"), None, False


def request_points(request: WeatherRequest) -> list[Location]:
    """The points a request resolves to: one location, a list, or a sampled area."""
    if isinstance(request.locations, Location):
        return [request.locations]
    if isinstance(request.locations, list):
        return request.locations
    from .spatial import sample

    return sample(request.locations, request.sampling)


def standard_time_note(points: list[Location], estimated: bool) -> str:
    """Show the clock convention before the person runs an actual-year plan."""
    offsets = sorted({point.standard_offset_minutes for point in points})
    labels = [f"UTC{'+' if minutes >= 0 else '-'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
              for minutes in offsets]
    note = "Fixed standard time: " + ", ".join(labels) + "; no daylight-saving shift."
    if estimated:
        note += " Some offsets were estimated from longitude and may differ from local civil standard time."
    return note


def location_key(value: Any) -> str:
    """Identifies a reviewed geography, so a changed one needs approval again."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]
```

- [ ] **Step 4: Add `review_locations` and delegate `locations`**

In `src/openepw/service.py` replace the body of `locations()` with:

```python
    def locations(self, request):
        from .planning.offsets import request_points

        return request_points(request)
```

and add directly after it:

```python
    def review_locations(self, geography: Any) -> dict:
        """Points, fixed standard-time offsets and a key for the person to approve before planning."""
        from .places.models import MAX_PLACES
        from .planning.offsets import estimate_offsets, location_key, standard_time_note

        normalized, sampling, estimated = estimate_offsets(geography)
        request = WeatherRequest.model_validate(
            {"locations": normalized, "sampling": sampling or {}, "years": [2000]})
        points = self.locations(request)
        if len(points) > MAX_PLACES:
            raise OpenEPWError("RESOURCE_LIMIT", f"Review at most {MAX_PLACES} points; narrow the area")
        canonical = request.model_dump(mode="json")["locations"]
        return {
            "geography": canonical,
            "sampling": request.sampling.model_dump(mode="json") if sampling else None,
            "offset_estimated": estimated,
            "point_count": len(points),
            "points": [point.model_dump(mode="json") for point in points[:50]],
            "standard_time": standard_time_note(points, estimated),
            "key": location_key(canonical),
        }
```

If ruff reports `WeatherRequest` or `OpenEPWError` undefined in `service.py`, add them to the existing `from .models import (...)` block.

- [ ] **Step 5: Use the moved functions in the coordinator**

In `src/openepw/chat/coordinator.py`:

1. In the import block, change `from ..models import Location, OpenEPWError, WeatherRequest, nominal_offset_minutes` to `from ..models import Location, OpenEPWError, WeatherRequest`, and add after `from ..places.parse import ...`:

```python
from ..planning.offsets import estimate_offsets as chat_geography
from ..planning.offsets import location_key, request_points, standard_time_note
```

2. Delete the definitions of `location_key`, `chat_geography` and `standard_time_summary` (lines 115–150) and put this in their place:

```python
def standard_time_summary(request: WeatherRequest, estimated: bool) -> str:
    """Show the clock convention before the user runs an actual-year plan."""
    return standard_time_note(request_points(request), estimated)
```

Keep `import hashlib` (line 1057 still uses it). If ruff reports `Location` unused, remove it from the models import.

- [ ] **Step 6: Run the affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_location_review.py tests/unit/test_chat_sessions.py tests/unit/test_spatial.py tests/unit/test_service.py -q`
Expected: all PASS.

- [ ] **Step 7: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add src/openepw/planning/offsets.py src/openepw/service.py src/openepw/chat/coordinator.py tests/unit/test_location_review.py
git commit -m "fix(planning): review location offsets in the service layer"
```

---

### Task 3: MCP support modules — schemas, summaries, descriptions

**Files:**
- Create: `src/openepw/mcp/schemas.py`, `src/openepw/mcp/summaries.py`, `src/openepw/mcp/descriptions.py`
- Test: `tests/unit/test_mcp_support.py`

**Interfaces:**
- Produces: `inline_schema(model) -> dict`; `WeatherRequestArg`, `AvailabilityQueryArg`, `PlaceSetQueryArg`, `VisualizationRequestArg`, `GeographyArg` (annotated parameter types); `summarize(tool: str, data: dict) -> str` (≤ 1,500 characters); `DESCRIPTIONS: dict[str, str]` covering all 24 tool names (22 existing plus the two added in Task 5); `INSTRUCTIONS: str`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_mcp_support.py`

```python
import json

from openepw.mcp.descriptions import DESCRIPTIONS, INSTRUCTIONS
from openepw.mcp.schemas import inline_schema
from openepw.mcp.summaries import LIMIT, summarize
from openepw.models import WeatherRequest

TOOLS = {
    "weather_geocode", "weather_places_interpret", "weather_places_preview", "weather_place_set",
    "weather_locations_review", "weather_product_offers", "weather_assess", "weather_discover",
    "weather_plan", "plan_inspect", "epw_upload", "epw_register_path", "weather_submit",
    "job_inspect", "job_cancel", "job_retry_failed", "artifact_inspect",
    "weather_visualization_capabilities", "weather_data_describe", "weather_visualize",
    "weather_data_page", "weather_export_compact", "weather_fetch", "weather_inspect",
}


def test_inline_schema_has_fields_and_no_references():
    schema = inline_schema(WeatherRequest)
    assert "locations" in schema["properties"]
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema


def test_plan_summary_names_the_hash_and_estimates_not_the_rows():
    data = {"plan_hash": "a" * 64, "kind": "weather", "output_count": 3, "batch_row_count": 4,
            "estimated_calls": 2, "warnings": ["w"], "issues": [{"code": "NO_SOURCE"}],
            "outputs": [{"id": "x" * 40}], "truncated": False}
    text = summarize("weather_plan", data)
    assert "a" * 64 in text and "3 outputs" in text and "2 estimated source calls" in text
    assert "NO_SOURCE" in text and "x" * 40 not in text


def test_view_summary_keeps_rows_out_of_model_context():
    data = {"view_id": "v1", "total_rows": 12, "rows": [{"value": 123456.789}],
            "request": {"family": "monthly_series", "variable": "dry_bulb"},
            "specs": [{"family": "monthly_series", "summary": "12 monthly_series points."}],
            "warnings": []}
    text = summarize("weather_visualize", data)
    assert "v1" in text and "12 monthly_series points." in text and "123456" not in text


def test_unknown_tools_and_broken_summaries_fall_back_to_clipped_json():
    assert summarize("not_a_tool", {"a": 1}) == '{"a": 1}'
    assert len(summarize("not_a_tool", {"a": "x" * 5000})) == LIMIT
    assert summarize("weather_plan", {"issues": "not-a-list"}).startswith("{")


def test_every_tool_has_a_description_with_use_and_limits():
    assert set(DESCRIPTIONS) == TOOLS
    for name, text in DESCRIPTIONS.items():
        assert len(text) >= 100 and "Use " in text and "Do not" in text, name
    assert "weather_locations_review" in INSTRUCTIONS and "simulation" in INSTRUCTIONS
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_support.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.mcp.descriptions'`.

- [ ] **Step 3: Create `src/openepw/mcp/schemas.py`**

```python
"""Publish inlined JSON schemas for dict-typed MCP parameters so clients see real fields.

Parameters stay plain dicts at runtime so the server validates them itself and can return
field-level errors; only the published input schema changes.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, WithJsonSchema

from ..availability import WeatherAvailabilityQuery
from ..models import WeatherRequest
from ..places.models import PlaceSetQuery
from ..visualization import VisualizationRequest


def inline_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema with every ``$ref`` replaced by its definition."""
    root = model.model_json_schema()
    definitions = root.pop("$defs", {})

    def resolve(node: Any, seen: tuple[str, ...] = ()) -> Any:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str):
                name = reference.rsplit("/", 1)[-1]
                if name in seen:                       # a recursive model stops here
                    return {"type": "object"}
                merged = {**definitions[name], **{key: value for key, value in node.items()
                                                  if key != "$ref"}}
                return resolve(merged, seen + (name,))
            return {key: resolve(value, seen) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        return node

    return resolve(root)


WeatherRequestArg = Annotated[dict[str, Any], WithJsonSchema(inline_schema(WeatherRequest))]
AvailabilityQueryArg = Annotated[dict[str, Any],
                                 WithJsonSchema(inline_schema(WeatherAvailabilityQuery))]
PlaceSetQueryArg = Annotated[dict[str, Any], WithJsonSchema(inline_schema(PlaceSetQuery))]
VisualizationRequestArg = Annotated[dict[str, Any],
                                    WithJsonSchema(inline_schema(VisualizationRequest))]
GeographyArg = Annotated[Any, WithJsonSchema(inline_schema(WeatherRequest)["properties"]["locations"])]
```

- [ ] **Step 4: Create `src/openepw/mcp/summaries.py`**

```python
"""Short text summaries of MCP tool results for model context.

Full data stays in ``structuredContent`` for renderers; the text names what a model needs
to continue (identifiers, counts, statuses) and never repeats data rows.
"""

from __future__ import annotations

import json
from typing import Any, Callable

LIMIT = 1500
ROWS = 10


def _clip(text: str) -> str:
    return text if len(text) <= LIMIT else text[:LIMIT - 1] + "…"


def _point(row: dict) -> str:
    name = row.get("name") or row.get("input") or "point"
    lat, lon = row.get("lat"), row.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"{name} ({lat:.4f}, {lon:.4f})"
    return str(name)


def _codes(items: list[dict]) -> str:
    codes = sorted({item["code"] for item in items if item.get("code")})
    return ", ".join(codes) if codes else "none"


def _geocode(data: dict) -> str:
    candidates = data.get("candidates", [])
    lines = [f"{len(candidates)} location candidates for '{data.get('query', '')}'"
             + ("; ambiguous, the person must choose one." if len(candidates) > 1 else ".")]
    lines += [f"{index}. {_point(item)} id={item.get('id')}"
              for index, item in enumerate(candidates[:ROWS], start=1)]
    return "\n".join(lines)


def _interpret(data: dict) -> str:
    kind = data.get("kind")
    if data.get("questions"):
        prompts = "; ".join(str(question.get("prompt", "")) for question in data["questions"])
        return (f"Place text is {kind}; ask the person: {prompts}. "
                "Pass the returned draft back with their reply.")
    if kind == "list":
        items = data.get("items", [])
        return f"Place text is a list of {len(items)} places: " + "; ".join(map(str, items[:ROWS]))
    if kind == "coordinates":
        return f"Place text is {len(data.get('points', []))} coordinate points."
    if kind == "invalid":
        return "Place text is invalid: " + str((data.get("issue") or {}).get("message", ""))
    return f"Place text is {kind}."


def _preview(data: dict) -> str:
    rows = data.get("rows", [])
    ambiguous = sum(bool(row.get("ambiguous")) for row in rows)
    unresolved = sum(row.get("status") != "resolved" for row in rows)
    lines = [f"Previewed {data.get('resolved', 0)} of {data.get('count', len(rows))} places "
             f"(digest {str(data.get('digest', ''))[:12]}); {ambiguous} ambiguous, {unresolved} unresolved."]
    lines += [f"{row.get('index')}. {_point(row)} [{row.get('status')}]" for row in rows[:ROWS]]
    if len(rows) > ROWS:
        lines.append(f"... {len(rows) - ROWS} more rows in the structured data.")
    return "\n".join(lines)


def _review(data: dict) -> str:
    points = "; ".join(_point(point) for point in data.get("points", [])[:ROWS])
    return (f"{data.get('point_count')} point(s): {points}. {data.get('standard_time')} "
            f"Location key {data.get('key')}. Ask the person to approve these locations before planning.")


def _offers(data: dict) -> str:
    options = data.get("options", [])
    years = (data.get("availability") or {}).get("years")
    lines = [f"{len(options)} product offers (catalog years {years}):"]
    lines += [f"- {option['id']}: {option['label']} · {option.get('available', 0)}/{option.get('sites', 0)} "
              f"listed, {option.get('unverified', 0)} unverified" for option in options[:2 * ROWS]]
    lines.append("Listed means eligible to try retrieval, not quality assured. The person chooses.")
    return "\n".join(lines)


def _assess(data: dict) -> str:
    options = data.get("options", [])
    lines = [f"{len(options)} catalog options; issue codes {_codes(data.get('issues', []))}."]
    for option in options[:ROWS]:
        product, eligibility = option.get("product") or {}, option.get("eligibility") or {}
        lines.append(f"- {product.get('provider')}/{product.get('dataset')} at location "
                     f"{option.get('occurrence_index')}: {eligibility.get('status')}"
                     + (", stale evidence" if eligibility.get("stale") else ""))
    return "\n".join(lines)


def _discover(data: dict) -> str:
    candidates = data.get("candidates", [])
    names = ", ".join(f"{(item.get('source') or {}).get('provider')}/{(item.get('source') or {}).get('dataset')}"
                      for item in candidates[:ROWS])
    return f"{len(candidates)} source candidates: {names}."


def _plan(data: dict) -> str:
    text = (f"plan_hash {data.get('plan_hash')} ({data.get('kind')}): {data.get('output_count')} outputs, "
            f"{data.get('batch_row_count')} batch rows, {data.get('estimated_calls')} estimated source calls, "
            f"{len(data.get('warnings', []))} warnings, issue codes {_codes(data.get('issues', []))}.")
    if data.get("truncated"):
        text += " Rows are truncated; page them with plan_inspect."
    return text


def _job(data: dict) -> str:
    artifacts = data.get("artifacts") or {}
    text = (f"job {data.get('id')} {data.get('state')}: {data.get('completed', 0)}/{data.get('total', 0)} "
            f"completed, {data.get('failed', 0)} failed; {artifacts.get('weather_count', 0)} weather artifacts; "
            f"{data.get('error_count', 0)} errors.")
    if data.get("cancellation_requested"):
        text += " Cancellation requested."
    return text


def _artifact(data: dict) -> str:
    text = (f"artifact {data.get('artifact_id')} role={data.get('role')} {data.get('bytes')} bytes "
            f"sha256={str(data.get('sha256', ''))[:12]}")
    if "simulation_ready" in data:
        text += f"; simulation_ready={data.get('simulation_ready')}"
    if data.get("qc_issue_codes"):
        text += f"; QC codes {', '.join(data['qc_issue_codes'])}"
    return text + "."


def _upload(data: dict) -> str:
    return (f"Registered EPW artifact {data.get('artifact_id')}: {data.get('rows')} rows; "
            f"input QC codes {_codes(data.get('input_qc', []))}.")


def _capabilities(data: dict) -> str:
    families = ", ".join(f"{item['family']} ({item['status']})" for item in data.get("families", []))
    return f"View families: {families}. Variables: {', '.join(data.get('variables', {}))}."


def _describe(data: dict) -> str:
    lines = []
    for source in data.get("sources", [])[:ROWS]:
        variables = ", ".join(f"{name} missing {entry.get('missing_hours')}h"
                              for name, entry in (source.get("variables") or {}).items())
        lines.append(f"{source.get('artifact_id')} {source.get('years')}: {variables}")
    return "\n".join(lines) or "No sources described."


def _view(data: dict) -> str:
    spec = (data.get("specs") or [{}])[0]
    request = data.get("request") or {}
    text = (f"view_id {data.get('view_id')}: {spec.get('family') or request.get('family')} of "
            f"{request.get('variable')}. {spec.get('summary', '')} {data.get('total_rows')} rows prepared; "
            "the renderer draws and pages them.")
    if data.get("warnings"):
        text += " Warnings: " + _codes(data["warnings"]) + "."
    return text


def _page(data: dict) -> str:
    return (f"view_id {data.get('view_id')}: {len(data.get('rows', []))} of {data.get('total_rows')} rows; "
            f"next_offset {data.get('next_offset')}.")


def _export(data: dict) -> str:
    return f"Compact ZIP artifact {data.get('artifact_id')}: {data.get('bytes')} bytes; {data.get('uri')}."


SUMMARIES: dict[str, Callable[[dict], str]] = {
    "weather_geocode": _geocode, "weather_places_interpret": _interpret,
    "weather_places_preview": _preview, "weather_place_set": _preview,
    "weather_locations_review": _review, "weather_product_offers": _offers,
    "weather_assess": _assess, "weather_discover": _discover,
    "weather_plan": _plan, "plan_inspect": _plan,
    "weather_submit": _job, "weather_fetch": _job, "job_inspect": _job, "job_cancel": _job,
    "job_retry_failed": _job, "artifact_inspect": _artifact,
    "epw_upload": _upload, "epw_register_path": _upload,
    "weather_visualization_capabilities": _capabilities, "weather_data_describe": _describe,
    "weather_visualize": _view, "weather_data_page": _page, "weather_export_compact": _export,
}


def summarize(tool: str, data: dict[str, Any]) -> str:
    """A short text for model context; unknown tools or odd data fall back to clipped JSON."""
    function = SUMMARIES.get(tool)
    if function is not None:
        try:
            return _clip(function(data))
        except Exception:
            pass
    return _clip(json.dumps(data, sort_keys=True, allow_nan=False))
```

- [ ] **Step 5: Create `src/openepw/mcp/descriptions.py`**

```python
"""Tool descriptions and server instructions written for a tool-calling model."""

INSTRUCTIONS = (
    "OpenEPW plans and retrieves building-energy weather files (EPW). Workflow: resolve places "
    "(weather_places_interpret, weather_geocode, weather_places_preview, weather_place_set); review "
    "them with weather_locations_review and get the person's approval; offer products with "
    "weather_product_offers and let the person choose; plan with weather_plan using exactly the "
    "approved locations, the chosen products and years the person stated; the person reviews the "
    "plan before weather_submit, which asks the client to confirm with the person. 'Supported' or "
    "'listed' means eligible to try retrieval, not quality assured. Inspect QC with artifact_inspect "
    "and never claim simulation readiness. Future weather is suspended. Keep EPW bytes out of prompts."
)

DESCRIPTIONS: dict[str, str] = {
    "weather_geocode": (
        "Resolve one short place name (1-150 characters) to up to 10 point candidates with ids, "
        "coordinates and names. Use when the person names a single place. Do not pick among several "
        "candidates yourself; ask the person to choose. mode accepts only 'point'."),
    "weather_places_interpret": (
        "Classify free place text as coordinates, a list, a single place, a descriptive set or invalid. "
        "Use when the text may hold several places, coordinates or a set such as 'all cities in Oregon'. "
        "For a descriptive set, ask the person the returned questions and pass the returned draft back "
        "with their reply. Do not enumerate a set before its questions are answered."),
    "weather_places_preview": (
        "Resolve up to 1,000 names or 'lat, lon' strings to numbered rows using the top geocoder match "
        "per name; ambiguous and unresolved rows are flagged. Use after weather_places_interpret returns "
        "a list or coordinates, or to apply an edit; pass earlier rows back unchanged to keep them pinned. "
        "Do not treat ambiguous rows as confirmed; the person reviews them."),
    "weather_place_set": (
        "List a clarified descriptive place set from GeoNames in population order as numbered rows. "
        "Use only with the complete query returned by weather_places_interpret. Do not invent country, "
        "region or population values."),
    "weather_locations_review": (
        "Normalize a point, a point list or an area: estimate fixed standard-time offsets from longitude "
        "where missing, sample areas, and return points, a standard-time note and a location key. Use "
        "before asking the person to approve locations; the plan must use exactly the reviewed geography. "
        "Do not change coordinates or offsets after the person approved them."),
    "weather_product_offers": (
        "List named downloadable weather products for reviewed locations with catalog availability per "
        "location (listed or unverified) and the catalog years used. Use to give the person a product "
        "choice; product (historical, tmy, tmyx, published), provider and years narrow the offers. Do "
        "not describe listed products as quality assured; listed means eligible to try retrieval."),
    "weather_assess": (
        "Compare catalog eligibility, evidence dates and unknowns for a weather request without "
        "retrieval. Use to explain why a source is or is not eligible. Do not use it for future weather "
        "(suspended) and do not treat 'supported' as complete data."),
    "weather_discover": (
        "Legacy discovery of source candidates and catalog alternatives for a weather request; "
        "weather_plan already runs discovery. Use only when an external client needs raw candidates. Do "
        "not use it to choose products for a person; use weather_product_offers."),
    "weather_plan": (
        "Store an immutable weather plan for reviewed locations, chosen products and explicit years or "
        "dates; returns plan_hash, outputs, batch rows, warnings and estimated source calls. Use only "
        "after the person approved the locations and chose products. Do not submit it yourself; the "
        "person reviews the plan and the host submits."),
    "plan_inspect": (
        "Page a stored plan's outputs, batch rows and selected candidates with reasons by plan_hash "
        "(limit 1-50). Use to explain a plan before review or answer questions about it. Do not try to "
        "modify a plan; changed choices need a new weather_plan."),
    "epw_upload": (
        "Host tool: register a person's EPW from base64 bytes encoded outside model context (5 MB "
        "maximum); returns artifact_id, rows and input QC. Use when the person attaches an EPW file. Do "
        "not place EPW bytes in model prompts."),
    "epw_register_path": (
        "Host tool: register a local EPW beneath a directory the server was started with (--allow-root), "
        "5 MB maximum. Use when the person names a file under that directory. Do not guess paths."),
    "weather_submit": (
        "Host tool: submit a stored, reviewed weather plan by plan_hash; the server asks the client to "
        "confirm with the person before any provider retrieval. Use when the person approves the plan "
        "review. Do not call it without that approval; clients that cannot confirm get APPROVAL_REQUIRED."),
    "job_inspect": (
        "Inspect a job's state, counts, per-output rows, issue codes and artifact ids. Use to report "
        "progress or results. Do not poll it in a loop; hosts follow job progress themselves."),
    "job_cancel": (
        "Host tool: request cancellation of a running job; completed artifacts remain. Use when the "
        "person asks to stop a job. Do not cancel on your own initiative."),
    "job_retry_failed": (
        "Host tool: retry only missing or failed outputs of a finished job under the original approval. "
        "Use when the person asks to retry. Do not retry on your own initiative."),
    "artifact_inspect": (
        "Verify an artifact checksum and return bounded metadata, linked manifest and QC ids, QC issue "
        "codes and simulation_ready (currently always false). Use before describing a retrieved or "
        "uploaded EPW. Do not claim an EPW is simulation-ready."),
    "weather_visualization_capabilities": (
        "List implemented and planned view families and the variables with units. Use before proposing "
        "a chart. Do not offer planned families as available."),
    "weather_data_describe": (
        "Describe up to 20 EPW artifacts: variables, units, calendar, years and missing hours. Use to "
        "choose a variable or explain data gaps. Do not infer values beyond these counts."),
    "weather_visualize": (
        "Prepare a bounded, framework-neutral view of EPW artifacts (family and variable) and return a "
        "view_id, a factual summary and the first data page for the renderer. Use when the person asks "
        "for a chart of retrieved or uploaded EPWs. Do not restate data rows; describe the summary."),
    "weather_data_page": (
        "Host tool: page prepared view rows by view_id (limit 1-200); offset 0 also returns the spec. "
        "Use when a renderer needs more rows. Do not use it to read data into model context."),
    "weather_export_compact": (
        "Host tool: build a checksummed compact ZIP of a completed job's outputs with its mapping. Use "
        "when the person asks for an export. Do not export without that request; export does not grant "
        "redistribution rights."),
    "weather_fetch": (
        "Legacy alias: store an inline weather plan and submit it with the same person confirmation as "
        "weather_submit. Use only from v0.1 clients. Do not use it in new clients; plan with weather_plan "
        "and submit by hash."),
    "weather_inspect": (
        "Legacy alias for job_inspect (job_id) or artifact_inspect (artifact_id). Use only from v0.1 "
        "clients. Do not use it in new clients."),
}
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_support.py -q`
Expected: all PASS.

- [ ] **Step 7: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add src/openepw/mcp/schemas.py src/openepw/mcp/summaries.py src/openepw/mcp/descriptions.py tests/unit/test_mcp_support.py
git commit -m "fix(mcp): add schemas, summaries and descriptions for agent clients"
```

---

### Task 4: Rewrite the MCP server on the support modules

**Files:**
- Rewrite: `src/openepw/mcp/server.py`
- Modify (test helpers that index `[1]`): `tests/mcp/test_future_suspension.py:23`, `tests/mcp/test_visualization.py:21`, `tests/unit/test_places_mcp.py:23`, `tests/unit/test_stage4_mcp_jobs.py:18`, `tests/harness/test_graph_places.py:32`, `tests/unit/test_availability_adapters.py:74`
- Test: `tests/mcp/test_contract.py`

**Interfaces:**
- Consumes: Task 3 modules.
- Produces: every tool returns `CallToolResult` with `content[0].text` = `summarize(name, data)` and `structuredContent` = bounded data; `tool_error(exc) -> ToolError`; `respond(name, data) -> CallToolResult`; `create_server(service=None, *, allowed_roots=None)` unchanged signature (Task 6 adds `runner`).

- [ ] **Step 1: Add failing contract tests** — append to `tests/mcp/test_contract.py`

```python
import json


def _error(excinfo):
    text = str(excinfo.value)
    return json.loads(text[text.index("{"):])


def test_dict_parameters_publish_inlined_field_schemas(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name, field in (("weather_plan", "request"), ("weather_discover", "request"),
                        ("weather_assess", "query"), ("weather_place_set", "query"),
                        ("weather_visualize", "request")):
        schema = tools[name].inputSchema["properties"][field]
        assert schema.get("properties"), name
        assert "$ref" not in json.dumps(schema), name
    assert "locations" in tools["weather_plan"].inputSchema["properties"]["request"]["properties"]
    assert all(tool.description and "Do not" in tool.description for tool in tools.values())


def test_validation_errors_name_the_failing_field(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("weather_plan", {
            "request": {"locations": {"lat": 200, "lon": 0}, "years": [2020]}}))
    payload = _error(excinfo)
    assert payload["code"] == "INVALID_REQUEST" and payload["retryable"] is False
    assert any(item["loc"].startswith("locations") for item in payload["details"])
    assert "200" not in json.dumps(payload["details"])


def test_internal_errors_carry_a_correlation_id_but_no_detail(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))

    def broken(*args, **kwargs):
        raise RuntimeError(r"C:\secret\path token=zzz-private")

    service.geocode = broken
    server = create_server(service)
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.call_tool("weather_geocode", {"query": "Ithaca"}))
    payload = _error(excinfo)
    assert payload["code"] == "INTERNAL_ERROR" and len(payload["correlation_id"]) == 12
    assert "secret" not in str(excinfo.value) and "zzz" not in str(excinfo.value)


def test_results_carry_a_summary_and_structured_data(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    result = asyncio.run(server.call_tool("weather_visualization_capabilities", {}))
    assert result.structuredContent["families"]
    text = result.content[0].text
    assert text.startswith("View families:") and len(text) <= 1500
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/mcp/test_contract.py -q`
Expected: FAIL (schema has no `properties`; no `details`; result is a tuple, not `CallToolResult`).

- [ ] **Step 3: Rewrite `src/openepw/mcp/server.py`**

```python
"""Local MCP adapter over the shared service, job and artifact stores."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter, ValidationError

from ..availability import AvailabilityQuery
from ..epw import read_epw
from ..jobs.worker import JobRunner
from ..models import OpenEPWError, WeatherPlan, WeatherRequest
from ..places.models import MAX_PLACES, PlacePreview, PlaceSetQuery
from ..qc import validate
from ..service import WeatherService
from ..visualization import VisualizationRequest
from .descriptions import DESCRIPTIONS, INSTRUCTIONS
from .schemas import (
    AvailabilityQueryArg,
    PlaceSetQueryArg,
    VisualizationRequestArg,
    WeatherRequestArg,
)
from .summaries import summarize

MAX_UPLOAD = 5_000_000
MAX_RESOURCE = 10_000_000
MAX_RESULT = 160_000
logger = logging.getLogger("openepw.mcp")


def _json(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _bounded(value: Any) -> Any:
    result = _json(value)
    if len(json.dumps(result, allow_nan=False)) > MAX_RESULT:
        raise OpenEPWError("RESOURCE_LIMIT", "Result is too large; narrow the request")
    return result


def _preview_summary(preview: PlacePreview) -> dict[str, Any]:
    """Compact preview: rows carry the points, so the GeoJSON and location copies are dropped."""
    rows = [row.model_dump(mode="json", exclude_none=True, exclude_defaults=True, exclude={"region"})
            | {"index": row.index, "input": row.input, "status": row.status} for row in preview.rows]
    return {"digest": preview.digest, "count": len(rows), "resolved": len(preview.locations), "rows": rows,
            "issues": [issue.model_dump(mode="json") for issue in preview.issues],
            "attribution": preview.attribution}


def _plan_summary(plan: WeatherPlan) -> dict[str, Any]:
    request = plan.request.model_dump(mode="json")
    if plan.kind == "weather":
        request = {key: request.get(key) for key in (
            "product", "years", "start", "end", "missing_policy", "dataset_selections"
        )}
    return _bounded({
        "plan_hash": plan.plan_hash, "kind": plan.kind, "request": request,
        "baseline_ref": _json(plan.baseline_ref) if plan.baseline_ref else None,
        "outputs": [{"id": row.id, "name": row.name,
                     "occurrence_index": row.occurrence_index,
                     "requested_location_id": row.requested_location_id}
                    for row in plan.outputs[:50]],
        "output_count": len(plan.outputs),
        "batch_rows": [row.model_dump(mode="json") for row in plan.batch_rows[:50]],
        "batch_row_count": len(plan.batch_rows),
        "issues": [issue.model_dump(mode="json") for issue in plan.issues[:50]],
        "warnings": plan.warnings[:50],
        "estimated_calls": plan.estimated_calls,
        "estimated_bytes": plan.estimated_bytes,
        "truncated": len(plan.outputs) > 50 or len(plan.batch_rows) > 50,
    })


def _job_summary(job: Any) -> dict[str, Any]:
    raw = job.model_dump(mode="json")
    bundle = raw.pop("bundle", None)
    raw["error_count"] = len(raw["errors"])
    raw["errors"] = raw["errors"][:50]
    if bundle:
        raw["artifacts"] = {
            "weather": [item["id"] for item in bundle["weather"][:50]],
            "weather_count": len(bundle["weather"]),
            **{name: bundle[name]["id"] for name in ("request", "plan", "manifest", "qc")},
            "additional": [item["id"] for item in bundle["additional"][:50]],
        }
    return _bounded(raw)


def validation_details(error: ValidationError) -> list[dict[str, str]]:
    """Field paths and messages only; pydantic messages do not echo the input value."""
    return [{"loc": ".".join(str(part) for part in item["loc"]), "msg": item["msg"]}
            for item in error.errors()[:20]]


def tool_error(exc: Exception) -> ToolError:
    """A safe JSON error for any failure inside a tool."""
    if isinstance(exc, ToolError):
        return exc
    payload: dict[str, Any]
    if isinstance(exc, OpenEPWError):
        payload = exc.issue.model_dump(mode="json")
    elif isinstance(exc, ValidationError):
        payload = {"code": "INVALID_REQUEST", "message": "Request schema validation failed",
                   "retryable": False, "details": validation_details(exc)}
    elif isinstance(exc, (ValueError, TypeError)):
        payload = {"code": "INVALID_REQUEST", "message": "Request schema validation failed",
                   "retryable": False}
    else:
        correlation = uuid.uuid4().hex[:12]
        logger.error("MCP internal error %s: %s", correlation, type(exc).__name__)
        payload = {"code": "INTERNAL_ERROR", "message": "Local operation failed",
                   "retryable": False, "correlation_id": correlation}
    return ToolError(json.dumps(payload))


def respond(name: str, data: Any) -> CallToolResult:
    """Short summary text for model context; bounded full data for renderers."""
    bounded = _bounded(data)
    return CallToolResult(content=[TextContent(type="text", text=summarize(name, bounded))],
                          structuredContent=bounded)


def call(name: str, function: Callable[..., Any], *args: Any) -> CallToolResult:
    try:
        return respond(name, function(*args))
    except Exception as exc:
        raise tool_error(exc) from None


def create_server(service=None, *, allowed_roots: list[str | Path] | None = None):
    service = service or WeatherService()
    roots = [Path(root).resolve() for root in (allowed_roots or [])]
    runner = JobRunner(service)

    @asynccontextmanager
    async def lifespan(server):
        runner.recover()
        yield {"runner": runner}
        runner.close()

    server = FastMCP("openepw", host="127.0.0.1", port=8001, lifespan=lifespan,
                     instructions=INSTRUCTIONS)

    def tool(function):
        return server.tool(description=DESCRIPTIONS[function.__name__])(function)

    def weather_request(raw):
        request = WeatherRequest.model_validate(raw)
        # Owner decision 2026-09-27: a full place preview (up to MAX_PLACES points) can be planned.
        if isinstance(request.locations, list) and len(request.locations) > MAX_PLACES:
            raise OpenEPWError("RESOURCE_LIMIT", f"MCP request exceeds {MAX_PLACES} locations")
        return request

    def submit(plan_hash, kind, idempotency_key):
        plan = service.plan_store.get(plan_hash)
        if plan.kind == "future":
            raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
        if plan.kind != kind:
            raise OpenEPWError("INVALID_REQUEST", "Plan kind does not match submit tool")
        return _job_summary(runner.submit(plan, idempotency_key))

    @tool
    def weather_geocode(query: str, mode: str = "point") -> CallToolResult:
        def action():
            if not query.strip() or len(query) > 150:
                raise OpenEPWError("INVALID_REQUEST", "Place name must be 1–150 characters")
            return service.geocode(query, mode=mode)
        return call("weather_geocode", action)

    @tool
    def weather_places_interpret(text: str, draft: dict | None = None) -> CallToolResult:
        def action():
            if not text.strip() or len(text) > 4000:
                raise OpenEPWError("INVALID_REQUEST", "Place text must be 1–4000 characters")
            return service.interpret_places(text, draft)
        return call("weather_places_interpret", action)

    @tool
    def weather_places_preview(places: list[str | dict]) -> CallToolResult:
        def action():
            texts = [item if isinstance(item, str) else str(item.get("input", "")) for item in places]
            if not places or any(not text.strip() or len(text) > 150 for text in texts):
                raise OpenEPWError("INVALID_REQUEST", "Each place must be 1–150 characters")
            return _preview_summary(service.preview_places(places))
        return call("weather_places_preview", action)

    @tool
    def weather_place_set(query: PlaceSetQueryArg) -> CallToolResult:
        return call("weather_place_set",
                    lambda: _preview_summary(service.place_set(PlaceSetQuery.model_validate(query))))

    @tool
    def weather_assess(query: AvailabilityQueryArg) -> CallToolResult:
        def action():
            if query.get("kind") == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
            return service.assess_availability(
                TypeAdapter(AvailabilityQuery).validate_python(query))
        return call("weather_assess", action)

    @tool
    def weather_discover(request: WeatherRequestArg) -> CallToolResult:
        return call("weather_discover", lambda: service.discover(weather_request(request)))

    @tool
    def weather_plan(request: WeatherRequestArg, kind: str = "weather") -> CallToolResult:
        def action():
            if kind == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
            if kind != "weather":
                raise OpenEPWError("INVALID_REQUEST", "Unknown plan kind")
            return _plan_summary(service.plan(weather_request(request)))
        return call("weather_plan", action)

    @tool
    def plan_inspect(plan_hash: str, offset: int = 0, limit: int = 50) -> CallToolResult:
        def action():
            if offset < 0 or not 1 <= limit <= 50:
                raise OpenEPWError("INVALID_REQUEST", "Invalid plan page")
            plan = service.plan_store.get(plan_hash)
            return {
                **_plan_summary(plan),
                "outputs": [row.model_dump(mode="json")
                            for row in plan.outputs[offset:offset + limit]],
                "batch_rows": [row.model_dump(mode="json")
                               for row in plan.batch_rows[offset:offset + limit]],
                "selected_candidates": [
                    {"id": candidate.id, "source": candidate.source.model_dump(mode="json"),
                     "product_id": candidate.product_id,
                     "selection_reasons": candidate.selection_reasons}
                    for candidate in plan.selected_candidates[offset:offset + limit]
                ],
                "offset": offset, "limit": limit,
            }
        return call("plan_inspect", action)

    @tool
    def epw_upload(content_base64: str, filename: str | None = None) -> CallToolResult:
        def action():
            if len(content_base64) > 6_666_672:
                raise OpenEPWError("RESOURCE_LIMIT", "EPW upload exceeds 5 MB")
            try:
                body = base64.b64decode(content_base64, validate=True)
            except (ValueError, binascii.Error):
                raise OpenEPWError("INVALID_BASELINE", "Invalid base64 EPW content") from None
            if not body or len(body) > MAX_UPLOAD:
                raise OpenEPWError("RESOURCE_LIMIT", "EPW upload exceeds 5 MB")
            data = read_epw(body)
            ref = service.register_baseline(body)
            return {"artifact_id": ref.id, "sha256": ref.sha256, "bytes": ref.bytes,
                    "rows": len(data.data), "input_qc": [i.model_dump(mode="json")
                    for i in validate(data)[:20]],
                    "filename": Path(filename).name if filename else None}
        return call("epw_upload", action)

    @tool
    def epw_register_path(path: str) -> CallToolResult:
        def action():
            target = Path(path).resolve()
            if not any(target.is_relative_to(root) for root in roots):
                raise OpenEPWError("ACCESS_DENIED", "Path is outside allowed local roots")
            if not target.is_file() or target.stat().st_size > MAX_UPLOAD:
                raise OpenEPWError("INVALID_BASELINE", "Baseline path missing or too large")
            data = read_epw(target)
            ref = service.register_baseline(target)
            return {"artifact_id": ref.id, "sha256": ref.sha256, "bytes": ref.bytes,
                    "rows": len(data.data), "input_qc": [i.model_dump(mode="json")
                    for i in validate(data)[:20]]}
        return call("epw_register_path", action)

    @tool
    def weather_submit(plan_hash: str, idempotency_key: str | None = None) -> CallToolResult:
        return call("weather_submit", submit, plan_hash, "weather", idempotency_key)

    @tool
    def job_inspect(job_id: str) -> CallToolResult:
        def action():
            job = runner.store.get(job_id)
            result = _job_summary(job)
            result["completed_output_ids"] = list(runner.store.items(job_id))[:50]
            if job.bundle:
                _, path = service.artifacts.resolve(job.bundle.manifest.id)
                manifest = json.loads(path.read_text(encoding="utf-8"))
                result["batch_rows"] = [
                    {"occurrence_index": row.get("occurrence_index"),
                     "period_start": row.get("period_start"),
                     "period_end": row.get("period_end"),
                     "output_id": row.get("output_id"), "status": row.get("status"),
                     "issue_codes": row.get("issue_codes", [])}
                    for row in manifest.get("batch_rows", [])[:50]
                ]
                result["future_rows"] = [
                    {"output_id": row.get("output_id"), "status": row.get("status"),
                     "issue_codes": row.get("issue_codes", [])}
                    for row in manifest.get("future_rows", [])[:50]
                ]
            return result
        return call("job_inspect", action)

    @tool
    def job_cancel(job_id: str) -> CallToolResult:
        return call("job_cancel", lambda: _job_summary(runner.store.cancel(job_id)))

    @tool
    def job_retry_failed(job_id: str, idempotency_key: str | None = None) -> CallToolResult:
        def action():
            if runner.store.get(job_id).kind == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP retry is suspended")
            return _job_summary(runner.retry_failed(job_id, idempotency_key))
        return call("job_retry_failed", action)

    @tool
    def artifact_inspect(artifact_id: str) -> CallToolResult:
        def action():
            ref, path = service.artifacts.resolve(artifact_id)
            result = {"artifact_id": ref.id, "role": ref.role, "media_type": ref.media_type,
                      "bytes": ref.bytes, "sha256": ref.sha256,
                      "uri": "weather://artifacts/" + ref.id,
                      "registration_route": ref.registration_route}

            def summarize_json(item_ref, item_path):
                if item_ref.bytes > 1_000_000:
                    return {"summary_truncated": True}
                value = json.loads(item_path.read_text(encoding="utf-8"))
                if item_ref.role == "manifest" and isinstance(value, dict):
                    return {
                        "simulation_ready": value.get("simulation_ready"),
                        "batch_rows": [{"occurrence_index": row.get("occurrence_index"),
                                        "status": row.get("status"),
                                        "issue_codes": row.get("issue_codes", [])}
                                       for row in value.get("batch_rows", [])[:50]],
                        "output_count": len(value.get("outputs", [])),
                    }
                if item_ref.role == "qc" and isinstance(value, list):
                    return {"qc_issue_codes": sorted({
                        issue["code"] for row in value[:50]
                        for issue in row.get("issues", []) if "code" in issue
                    })}
                return {}

            if ref.role in ("manifest", "qc"):
                result.update(summarize_json(ref, path))
            if ref.role == "weather":
                try:
                    manifest = service.artifacts.sibling(ref, "manifest.json", "manifest")
                    qc = service.artifacts.sibling(ref, "qc.json", "qc")
                    result.update({"manifest_artifact_id": manifest.id,
                                   "qc_artifact_id": qc.id})
                    _, manifest_path = service.artifacts.resolve(manifest.id)
                    _, qc_path = service.artifacts.resolve(qc.id)
                    result.update(summarize_json(manifest, manifest_path))
                    result.update(summarize_json(qc, qc_path))
                except OpenEPWError:
                    pass
            return result
        return call("artifact_inspect", action)

    @tool
    def weather_visualization_capabilities() -> CallToolResult:
        return call("weather_visualization_capabilities", service.visualization_capabilities)

    @tool
    def weather_data_describe(artifact_ids: list[str]) -> CallToolResult:
        return call("weather_data_describe", service.describe_weather_data, artifact_ids)

    @tool
    def weather_visualize(request: VisualizationRequestArg) -> CallToolResult:
        return call("weather_visualize",
                    lambda: service.visualize_weather(VisualizationRequest.model_validate(request)))

    @tool
    def weather_data_page(view_id: str, offset: int = 0, limit: int = 100) -> CallToolResult:
        return call("weather_data_page", service.page_weather_data, view_id, offset, limit)

    @tool
    def weather_export_compact(job_id: str) -> CallToolResult:
        def action():
            ref = runner.export_compact(job_id)
            return {"artifact_id": ref.id, "bytes": ref.bytes, "sha256": ref.sha256,
                    "uri": "weather://artifacts/" + ref.id}
        return call("weather_export_compact", action)

    # v0.1 aliases remain available during migration.
    @tool
    def weather_fetch(plan: dict, idempotency_key: str | None = None) -> CallToolResult:
        def action():
            selected = WeatherPlan.model_validate(plan)
            if selected.kind == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
            if selected.kind != "weather":
                raise OpenEPWError("INVALID_REQUEST", "Expected a weather plan")
            return _job_summary(runner.submit(selected, idempotency_key))
        return call("weather_fetch", action)

    @tool
    def weather_inspect(job_id: str | None = None, artifact_id: str | None = None) -> CallToolResult:
        if job_id:
            return job_inspect(job_id)
        if artifact_id:
            return artifact_inspect(artifact_id)
        raise ToolError(json.dumps({"code": "INVALID_REQUEST", "retryable": False,
                                    "message": "Provide job_id or artifact_id"}))

    @server.resource("weather://artifacts/{artifact_id}")
    def artifact(artifact_id: str) -> bytes:
        """Read checksum-verified EPW, manifest, QC or export bytes by opaque ID."""
        try:
            ref, path = service.artifacts.resolve(artifact_id)
            if ref.bytes > MAX_RESOURCE:
                raise ValueError("Artifact exceeds MCP resource limit")
            return path.read_bytes()
        except (OpenEPWError, OSError, ValueError):
            raise ValueError("Artifact unavailable or exceeds resource limit") from None

    return server
```

- [ ] **Step 4: Update test helpers that indexed the old tuple result**

| File:line | Old | New |
| --- | --- | --- |
| `tests/mcp/test_future_suspension.py:23` | `return asyncio.run(server.call_tool(name, arguments))[1]` | `return asyncio.run(server.call_tool(name, arguments)).structuredContent` |
| `tests/mcp/test_visualization.py:21` | `return asyncio.run(server.call_tool(name, arguments))[1]` | `return asyncio.run(server.call_tool(name, arguments)).structuredContent` |
| `tests/unit/test_places_mcp.py:23` | `return asyncio.run(server.call_tool(name, kwargs))[1]` | `return asyncio.run(server.call_tool(name, kwargs)).structuredContent` |
| `tests/unit/test_stage4_mcp_jobs.py:18` | `return asyncio.run(server.call_tool(name, kwargs))[1]` | `return asyncio.run(server.call_tool(name, kwargs)).structuredContent` |
| `tests/harness/test_graph_places.py:32` | `return (await self.server.call_tool(name, arguments))[1]` | `return (await self.server.call_tool(name, arguments)).structuredContent` |
| `tests/unit/test_availability_adapters.py:74` | `actual = result if isinstance(result, dict) else result[1]` | `actual = result.structuredContent` |

- [ ] **Step 5: Run the MCP, places, harness and adapter tests**

Run: `.venv/Scripts/python.exe -m pytest tests/mcp tests/unit/test_places_mcp.py tests/unit/test_stage4_mcp_jobs.py tests/unit/test_availability_adapters.py tests/unit/test_interfaces.py tests/harness -q`
Expected: all PASS (the stdio tests start real subprocesses and take longer).

- [ ] **Step 6: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add src/openepw/mcp/server.py tests/mcp tests/unit/test_places_mcp.py tests/unit/test_stage4_mcp_jobs.py tests/unit/test_availability_adapters.py tests/harness/test_graph_places.py
git commit -m "fix(mcp): publish typed schemas, field errors and summarized results"
```

---

### Task 5: MCP tools for location review and product offers

**Files:**
- Modify: `src/openepw/mcp/server.py` (two tools; import `GeographyArg`)
- Test: `tests/unit/test_mcp_review_offers.py`

**Interfaces:**
- Consumes: `WeatherService.review_locations`, `WeatherService.product_offers` (Tasks 1–2); `GeographyArg` (Task 3).
- Produces: tools `weather_locations_review(locations)` and `weather_product_offers(locations, product=None, provider=None, years=None)`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_mcp_review_offers.py`

```python
import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from openepw.config import RuntimeConfig
from openepw.mcp.server import create_server
from openepw.service import WeatherService

ITHACA = {"lat": 42.44, "lon": -76.5, "name": "Ithaca"}


def test_location_review_estimates_offsets_and_returns_a_key(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    result = asyncio.run(server.call_tool("weather_locations_review", {"locations": ITHACA}))
    data = result.structuredContent
    assert data["points"][0]["standard_offset_minutes"] == -300 and data["offset_estimated"] is True
    assert data["key"] in result.content[0].text and "UTC-05:00" in result.content[0].text


def test_location_review_rejects_invalid_coordinates_with_details(tmp_path):
    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    with pytest.raises(ToolError, match="INVALID_REQUEST"):
        asyncio.run(server.call_tool("weather_locations_review", {"locations": {"lat": 95, "lon": 0}}))


def test_product_offers_tool_matches_the_service(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    server = create_server(service)
    result = asyncio.run(server.call_tool("weather_product_offers",
                                          {"locations": ITHACA, "product": "tmy"}))
    expected = service.product_offers(ITHACA, product="tmy")
    assert result.structuredContent == expected
    assert expected["options"] and all(option["group"] == "typical" for option in expected["options"])
    assert expected["options"][0]["id"] in result.content[0].text
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_review_offers.py -q`
Expected: FAIL with `ToolError: Unknown tool: weather_locations_review`.

- [ ] **Step 3: Register the tools**

In `src/openepw/mcp/server.py` add `GeographyArg` to the `from .schemas import (...)` block and add after `weather_place_set`:

```python
    @tool
    def weather_locations_review(locations: GeographyArg) -> CallToolResult:
        return call("weather_locations_review", service.review_locations, locations)

    @tool
    def weather_product_offers(locations: GeographyArg, product: str | None = None,
                               provider: str | None = None,
                               years: list[int] | None = None) -> CallToolResult:
        def action():
            if product not in (None, "historical", "amy", "tmy", "tmyx", "published"):
                raise OpenEPWError("INVALID_REQUEST", "Unknown product type")
            return service.product_offers(locations, product=product, provider=provider, years=years)
        return call("weather_product_offers", action)
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_review_offers.py tests/mcp/test_contract.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openepw/mcp/server.py tests/unit/test_mcp_review_offers.py
git commit -m "fix(mcp): add location review and product offer tools"
```

---

### Task 6: One job runner per data root, shared by the API and MCP server

**Files:**
- Create: `src/openepw/jobs/lock.py`
- Modify: `src/openepw/jobs/worker.py:115-120` (`recover`, `close`)
- Modify: `src/openepw/mcp/server.py` (`create_server` signature and lifespan)
- Modify: `src/openepw/api/app.py` (shared MCP server on `app.state`)
- Test: `tests/unit/test_runner_lock.py`, `tests/unit/test_mcp_shared_runner.py`

**Interfaces:**
- Produces: `acquire_runner_lock(root) -> Path`, `release_runner_lock(path) -> None` (raises `OpenEPWError("DATA_ROOT_BUSY", ...)` across processes; re-entrant within one process); `create_server(service=None, *, allowed_roots=None, runner: JobRunner | None = None)`; `server.openepw_runner`; `app.state.mcp_server` (or `None` without the `mcp` extra).

- [ ] **Step 1: Write the failing lock tests** — `tests/unit/test_runner_lock.py`

```python
import os
import subprocess
import sys
from pathlib import Path

from openepw.jobs.lock import acquire_runner_lock, release_runner_lock

SRC = Path(__file__).parents[2] / "src"
PROBE = (
    "import sys\n"
    "from openepw.jobs.lock import acquire_runner_lock\n"
    "try:\n"
    "    acquire_runner_lock(sys.argv[1])\n"
    "except Exception as error:\n"
    "    print(getattr(getattr(error, 'issue', None), 'code', type(error).__name__))\n"
    "    raise SystemExit(3)\n"
)


def _probe(root):
    return subprocess.run([sys.executable, "-c", PROBE, str(root)], capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(SRC)}, timeout=60)


def test_owners_in_one_process_share_the_lock(tmp_path):
    first = acquire_runner_lock(tmp_path)
    second = acquire_runner_lock(tmp_path)
    assert first == second
    release_runner_lock(second)
    release_runner_lock(first)
    release_runner_lock(acquire_runner_lock(tmp_path))


def test_another_process_is_refused_until_the_lock_is_released(tmp_path):
    held = acquire_runner_lock(tmp_path)
    try:
        refused = _probe(tmp_path)
        assert refused.returncode == 3 and "DATA_ROOT_BUSY" in refused.stdout
    finally:
        release_runner_lock(held)
    assert _probe(tmp_path).returncode == 0
```

- [ ] **Step 2: Write the failing sharing tests** — `tests/unit/test_mcp_shared_runner.py`

```python
import asyncio

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.mcp.server import create_server
from openepw.service import WeatherService


async def _open_and_close(server):
    async with create_connected_server_and_client_session(server) as client:
        await client.list_tools()


def test_a_supplied_runner_is_used_and_left_running(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path))
    runner = JobRunner(service)
    try:
        server = create_server(service, runner=runner)
        assert server.openepw_runner is runner
        asyncio.run(_open_and_close(server))
        assert runner.pool._shutdown is False
    finally:
        runner.close()


def test_the_app_shares_its_runner_with_its_mcp_server(tmp_path):
    with TestClient(create_app(WeatherService(RuntimeConfig(data_root=tmp_path)))) as client:
        state = client.app.state
        assert state.mcp_server is not None
        assert state.mcp_server.openepw_runner is state.runner
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_runner_lock.py tests/unit/test_mcp_shared_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.jobs.lock'`.

- [ ] **Step 4: Create `src/openepw/jobs/lock.py`**

```python
"""One job runner per data root: a cross-process file lock, shared within one process."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import IO, Any

from ..models import OpenEPWError

_guard = threading.Lock()
_held: dict[Path, list[Any]] = {}          # lock path -> [owner count, open file]


def _lock(file: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file: IO[bytes]) -> None:
    file.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def acquire_runner_lock(root: str | Path) -> Path:
    """Hold the data root for job execution; owners in this process share one lock."""
    path = Path(root).resolve() / "runner.lock"
    with _guard:
        if path in _held:
            _held[path][0] += 1
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        file = path.open("a+b")
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write(b"\0")
            file.flush()
        file.seek(0)
        try:
            _lock(file)
        except OSError:
            file.close()
            raise OpenEPWError(
                "DATA_ROOT_BUSY",
                "Another OpenEPW process is running jobs for this data root; stop it or use another "
                "--data-root") from None
        _held[path] = [1, file]
        return path


def release_runner_lock(path: Path) -> None:
    with _guard:
        entry = _held.get(path)
        if entry is None:
            return
        entry[0] -= 1
        if entry[0] == 0:
            _unlock(entry[1])
            entry[1].close()
            del _held[path]
```

- [ ] **Step 5: Hold the lock while a runner recovers and runs jobs**

In `src/openepw/jobs/worker.py` replace `recover` and `close` with:

```python
    def recover(self):
        """Take the data root for this process, then resume unfinished jobs."""
        from .lock import acquire_runner_lock

        if getattr(self, "_root_lock", None) is None:
            self._root_lock = acquire_runner_lock(self.service.config.data_root)
        for job_id in self.store.unfinished():
            self.enqueue(job_id)

    def close(self):
        from .lock import release_runner_lock

        self.pool.shutdown(wait=True)
        if getattr(self, "_root_lock", None) is not None:
            release_runner_lock(self._root_lock)
            self._root_lock = None
```

and add `self._root_lock: Path | None = None` at the end of `JobRunner.__init__` (import `Path` from `pathlib` at the top if it is not already imported).

- [ ] **Step 6: Let `create_server` accept a shared runner**

In `src/openepw/mcp/server.py` replace the start of `create_server` (signature through the `lifespan` definition) with:

```python
def create_server(service=None, *, allowed_roots: list[str | Path] | None = None,
                  runner: JobRunner | None = None):
    """Build the MCP server; a supplied runner is shared and left to its owner to close."""
    service = service or WeatherService()
    roots = [Path(root).resolve() for root in (allowed_roots or [])]
    owns_runner = runner is None
    runner = runner or JobRunner(service)

    @asynccontextmanager
    async def lifespan(server):
        if owns_runner:
            runner.recover()
        try:
            yield {"runner": runner}
        finally:
            if owns_runner:
                runner.close()
```

and immediately after the `server = FastMCP(...)` line add:

```python
    server.openepw_runner = runner  # type: ignore[attr-defined]
```

- [ ] **Step 7: Share the app's runner with an in-process MCP server**

In `src/openepw/api/app.py`, directly after `app.state.runner = runner`, add:

```python
    try:
        from ..mcp.server import create_server
    except ImportError:  # the mcp extra is optional for the REST server
        app.state.mcp_server = None
    else:
        # Agent sessions connect in-process (P4); it never runs a second job runner.
        app.state.mcp_server = create_server(service, runner=runner)
```

- [ ] **Step 8: Run the new and affected tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_runner_lock.py tests/unit/test_mcp_shared_runner.py tests/unit/test_jobs.py tests/unit/test_api.py tests/mcp tests/unit/test_stage4_mcp_jobs.py tests/harness tests/pilot -q`
Expected: all PASS. If a harness or pilot test fails with `DATA_ROOT_BUSY`, it opened two job-running processes on one data root at the same time; give the second its own `tmp_path` subdirectory rather than weakening the lock, and note it in the commit message.

- [ ] **Step 9: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add src/openepw/jobs/lock.py src/openepw/jobs/worker.py src/openepw/mcp/server.py src/openepw/api/app.py tests/unit/test_runner_lock.py tests/unit/test_mcp_shared_runner.py
git commit -m "fix(jobs): run one job runner per data root and share it with MCP"
```

---

### Task 7: Submission needs the person's confirmation (MCP elicitation)

**Files:**
- Create: `src/openepw/mcp/approval.py`
- Modify: `src/openepw/models/__init__.py` (`WeatherJob.approved_via`)
- Modify: `src/openepw/jobs/store.py:38-48`, `src/openepw/jobs/worker.py:45-49` and `retry_failed`
- Modify: `src/openepw/mcp/server.py` (`submit`, `weather_submit`, `weather_fetch`)
- Modify: `src/openepw/api/app.py:349`, `src/openepw/chat/coordinator.py:1100-1101`
- Modify: `src/openepw/harness/mcp_client.py`, `src/openepw/harness/trace.py`, `src/openepw/harness/agent.py:278-288`
- Modify: `tests/pilot/test_journeys.py` (approve before each submit), `tests/unit/test_stage4_mcp_jobs.py:64-76`
- Modify: `pyproject.toml:16-17` (`mcp>=1.30,<2`)
- Create: `tests/unit/mcp_memory.py`
- Test: `tests/unit/test_mcp_approval.py`

**Interfaces:**
- Consumes: `create_server(..., runner=...)` (Task 6).
- Produces: `confirmation_message(plan_hash) -> str`; `plan_hash_from_message(message) -> str | None`; `SubmitConfirmation` (pydantic, `approve: bool`); `async confirm_submission(ctx, plan_hash) -> str` (returns `"elicitation"`; raises `APPROVAL_REQUIRED` / `APPROVAL_DECLINED`); `approval_callback(is_approved: Callable[[str], bool])` for `ClientSession(elicitation_callback=...)`; `WeatherJob.approved_via: Literal["elicitation", "api", "chat"] | None`; `JobRunner.submit(plan, idempotency_key=None, retry_of=None, approved_via=None)`; `StdioMCPPort.approve(plan_hash)`; test helper `session_call(server, name, arguments, *, approve=None) -> CallToolResult`.

- [ ] **Step 1: Create the test helper** — `tests/unit/mcp_memory.py`

```python
"""Call the openepw MCP server through a real in-memory client session in tests."""

import asyncio

from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, ElicitResult


def session_call(server, name, arguments, *, approve=None) -> CallToolResult:
    """approve=None: the client cannot confirm; True/False: it accepts or declines."""

    async def answer(context, params):
        if approve:
            return ElicitResult(action="accept", content={"approve": True})
        return ElicitResult(action="decline")

    async def run():
        async with create_connected_server_and_client_session(
                server, elicitation_callback=answer if approve is not None else None) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(run())
```

- [ ] **Step 2: Write the failing tests** — `tests/unit/test_mcp_approval.py`

```python
import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from mcp.types import ElicitRequestFormParams
from mcp_memory import session_call
from test_batch import StationProvider

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.jobs.worker import JobRunner
from openepw.mcp.approval import approval_callback, confirmation_message, plan_hash_from_message
from openepw.mcp.server import create_server
from openepw.models import WeatherRequest
from openepw.service import WeatherService

REQUEST = {"locations": {"lat": 1, "lon": 0}, "start": "2024-01-01", "end": "2024-01-01"}
HASH = "a" * 64


@pytest.fixture
def stack(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    runner = JobRunner(service)
    yield service, runner, create_server(service, runner=runner)
    runner.close()


def _plan(server):
    return asyncio.run(server.call_tool("weather_plan", {"request": REQUEST})).structuredContent


def test_message_round_trips_the_plan_hash():
    assert plan_hash_from_message(confirmation_message(HASH)) == HASH
    assert plan_hash_from_message("Approve something else?") is None


def test_client_callback_accepts_only_recorded_approvals():
    callback = approval_callback({HASH}.__contains__)
    params = ElicitRequestFormParams(message=confirmation_message(HASH),
                                     requestedSchema={"type": "object", "properties": {}})
    assert asyncio.run(callback(None, params)).action == "accept"
    other = ElicitRequestFormParams(message=confirmation_message("b" * 64),
                                    requestedSchema={"type": "object", "properties": {}})
    assert asyncio.run(callback(None, other)).action == "decline"


def test_confirmed_submit_runs_and_records_how_it_was_approved(stack):
    service, runner, server = stack
    plan = _plan(server)
    result = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]}, approve=True)
    assert not result.isError
    job_id = result.structuredContent["id"]
    assert result.structuredContent["approved_via"] == "elicitation"
    for _ in range(100):
        if runner.store.get(job_id).state not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert runner.store.get(job_id).state == "completed"


def test_declined_or_unconfirmable_submit_starts_nothing(stack):
    service, runner, server = stack
    plan = _plan(server)
    declined = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]}, approve=False)
    assert declined.isError and "APPROVAL_DECLINED" in declined.content[0].text
    unable = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]})
    assert unable.isError and "APPROVAL_REQUIRED" in unable.content[0].text
    assert list(runner.store.unfinished()) == []


def test_legacy_inline_fetch_needs_the_same_confirmation_and_stores_the_plan(stack):
    service, runner, server = stack
    plan = service.plan(WeatherRequest.model_validate(REQUEST))
    inline = {"plan": plan.model_dump(mode="json")}
    refused = session_call(server, "weather_fetch", inline)
    assert refused.isError and "APPROVAL_REQUIRED" in refused.content[0].text
    accepted = session_call(server, "weather_fetch", inline, approve=True)
    assert not accepted.isError and accepted.structuredContent["approved_via"] == "elicitation"
    assert service.plan_store.get(plan.plan_hash).plan_hash == plan.plan_hash


def test_rest_submission_records_api_approval(tmp_path):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    with TestClient(create_app(service)) as client:
        plan = client.post("/v1/weather/plan", json=REQUEST).json()
        job = client.post("/v1/weather/jobs", json={"plan_hash": plan["plan_hash"]}).json()
        assert job["approved_via"] == "api"
```

(`POST /v1/weather/plan` takes the `WeatherRequest` body directly and returns the plan with
`plan_hash`; `POST /v1/weather/jobs` takes `{"plan_hash": ...}`, as in `tests/unit/test_api.py`.)

- [ ] **Step 3: Run them to see them fail**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_approval.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.mcp.approval'`.

- [ ] **Step 4: Create `src/openepw/mcp/approval.py`**

```python
"""Submission needs the person's confirmation, asked through MCP elicitation.

A model-callable approval tool could approve itself, so none exists. The server asks the
client; the openepw host answers only for plans the person approved in a plan review, and
other clients show their own confirmation.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.fastmcp import Context
from mcp.types import ClientCapabilities, ElicitationCapability, ElicitResult
from pydantic import BaseModel, Field

from ..models import OpenEPWError

_PLAN = re.compile(r"\bplan ([0-9a-f]{64})\b")


class SubmitConfirmation(BaseModel):
    approve: bool = Field(description="Run this reviewed plan and start provider retrieval")


def confirmation_message(plan_hash: str) -> str:
    return (f"Approve and run reviewed weather plan {plan_hash}? "
            "This starts provider retrieval.")


def plan_hash_from_message(message: str) -> str | None:
    match = _PLAN.search(message or "")
    return match.group(1) if match else None


async def confirm_submission(ctx: Context, plan_hash: str) -> str:
    """Ask the client to confirm; returns how the submission was approved."""
    try:
        session = ctx.session
    except ValueError:                        # called outside a client request (direct call)
        session = None
    capable = session is not None and session.check_client_capability(
        ClientCapabilities(elicitation=ElicitationCapability()))
    if not capable:
        raise OpenEPWError("APPROVAL_REQUIRED",
                           "Submitting needs a client that can confirm the reviewed plan with the person")
    result = await ctx.elicit(confirmation_message(plan_hash), SubmitConfirmation)
    if not isinstance(result, AcceptedElicitation) or not result.data.approve:
        raise OpenEPWError("APPROVAL_DECLINED", "The plan was not approved; nothing was submitted")
    return "elicitation"


def approval_callback(is_approved: Callable[[str], bool]):
    """Client side: accept a confirmation only for a plan the person already approved."""

    async def callback(context: Any, params: Any) -> ElicitResult:
        plan_hash = plan_hash_from_message(getattr(params, "message", ""))
        if plan_hash and is_approved(plan_hash):
            return ElicitResult(action="accept", content={"approve": True})
        return ElicitResult(action="decline")

    return callback
```

- [ ] **Step 5: Record `approved_via` on jobs**

In `src/openepw/models/__init__.py`, add to `WeatherJob` after `idempotency_key`:

```python
    approved_via: Literal["elicitation", "api", "chat"] | None = None
```

In `src/openepw/jobs/store.py` change the `submit` signature to
`def submit(self, plan, idempotency_key=None, retry_of=None, approved_via=None):` and add
`approved_via=approved_via,` to the `WeatherJob(...)` constructor call.

In `src/openepw/jobs/worker.py` change `JobRunner.submit` to:

```python
    def submit(self, plan, idempotency_key=None, retry_of=None, approved_via=None):
        if isinstance(plan, str):
            plan = self.service.plan_store.get(plan)
        job = self.store.submit(plan, idempotency_key, retry_of=retry_of, approved_via=approved_via)
        self.enqueue(job.id)
        return job
```

and in `retry_failed` change the final line
`return self.submit(subplan(plan, missing), idempotency_key, retry_of=job_id)` to
`return self.submit(subplan(plan, missing), idempotency_key, retry_of=job_id, approved_via=job.approved_via)`.

In `src/openepw/api/app.py:349` change `return runner.submit(selected_plan, payload.idempotency_key)` to
`return runner.submit(selected_plan, payload.idempotency_key, approved_via="api")`.

In `src/openepw/chat/coordinator.py:1100-1101` change

```python
            jobs = [runner.submit(self.service.plan_store.get(item),
                                  f"chat:{session_id}:{key}" + (f":{index}" if index else ""))
```

to

```python
            jobs = [runner.submit(self.service.plan_store.get(item),
                                  f"chat:{session_id}:{key}" + (f":{index}" if index else ""),
                                  approved_via="chat")
```

- [ ] **Step 6: Confirm before submitting in the MCP server**

In `src/openepw/mcp/server.py`:

1. Add imports: `from mcp.server.fastmcp import Context, FastMCP` (replacing the existing `FastMCP` import) and `from .approval import confirm_submission`.
2. After `call(...)` add:

```python
async def acall(name: str, function: Callable[..., Any], *args: Any) -> CallToolResult:
    try:
        return respond(name, await function(*args))
    except Exception as exc:
        raise tool_error(exc) from None
```

3. Replace the inner `submit` helper with:

```python
    async def submit(plan, idempotency_key, ctx):
        if plan.kind == "future":
            raise OpenEPWError("FEATURE_SUSPENDED", "Future-weather MCP access is suspended")
        if plan.kind != "weather":
            raise OpenEPWError("INVALID_REQUEST", "Expected a weather plan")
        approved_via = await confirm_submission(ctx, plan.plan_hash)
        return _job_summary(runner.submit(plan, idempotency_key, approved_via=approved_via))
```

4. Replace `weather_submit` with:

```python
    @tool
    async def weather_submit(plan_hash: str, ctx: Context,
                             idempotency_key: str | None = None) -> CallToolResult:
        async def action():
            return await submit(service.plan_store.get(plan_hash), idempotency_key, ctx)
        return await acall("weather_submit", action)
```

5. Replace `weather_fetch` with:

```python
    @tool
    async def weather_fetch(plan: dict, ctx: Context,
                            idempotency_key: str | None = None) -> CallToolResult:
        async def action():
            selected = WeatherPlan.model_validate(plan)
            if selected.kind == "weather":
                service.plan_store.put(selected)
            return await submit(selected, idempotency_key, ctx)
        return await acall("weather_fetch", action)
```

- [ ] **Step 7: Keep the legacy console submitting**

In `src/openepw/harness/mcp_client.py`: add `from ..mcp.approval import approval_callback`; in `StdioMCPPort.__init__` add `self.approved: set[str] = set()`; add the method

```python
    def approve(self, plan_hash: str) -> None:
        """Record the person's (or auto-submit setting's) approval of one plan hash."""
        self.approved.add(plan_hash)
```

and change the session line in `__aenter__` to

```python
        self.session = await self.stack.enter_async_context(ClientSession(
            reader, writer, elicitation_callback=approval_callback(self.approved.__contains__)))
```

In `src/openepw/harness/trace.py`, add to `TracingMCPPort`:

```python
    def approve(self, plan_hash: str) -> None:
        approve = getattr(self.port, "approve", None)
        if callable(approve):
            approve(plan_hash)
```

In `src/openepw/harness/agent.py` `submit_plan`, insert before `job = await self._call(f"{kind}_submit", plan_hash=self.plan_hash)`:

```python
        approve = getattr(self.mcp, "approve", None)
        if callable(approve):
            approve(self.plan_hash)
```

Add to `tests/harness/test_agent.py`:

```python
def test_submit_records_approval_before_calling_weather_submit():
    import asyncio

    from openepw.harness.agent import ReferenceAgent

    class ApprovingPort:
        def __init__(self):
            self.calls = []

        def approve(self, plan_hash):
            self.calls.append(("approve", plan_hash))

        async def call(self, name, **arguments):
            self.calls.append((name, arguments.get("plan_hash")))
            return {"id": "job1", "state": "completed", "plan_hash": "a" * 64, "completed": 1,
                    "failed": 0, "total": 1, "artifacts": {"weather": []}}

    port = ApprovingPort()
    agent = ReferenceAgent(port, model=None)
    agent.plan_hash = "a" * 64
    asyncio.run(agent.submit_plan("weather", preface="Weather."))
    assert port.calls.index(("approve", "a" * 64)) < port.calls.index(("weather_submit", "a" * 64))
```

In `tests/pilot/test_journeys.py`, insert `client.approve(<hash>)` on the line before each `weather_submit` call, using the same hash expression the call passes: before lines 146 and 379 `client.approve(plan["plan_hash"])`; before 223 `client.approve(weather["plan_hash"])`; before 250 `client.approve(hashes["warn"])`; before 259 `client.approve(hashes["error"])`; before 266 `client.approve(hashes["batch_error"])`.

In `tests/unit/test_stage4_mcp_jobs.py` (`test_weather_plan_submit_inspect_and_compact_export`), add `from mcp_memory import session_call` and `from openepw.jobs.worker import JobRunner` to the imports, and replace

```python
    server = create_server(service)
```

with

```python
    runner = JobRunner(service)
    server = create_server(service, runner=runner)
```

and replace `submitted = _call(server, "weather_submit", plan_hash=plan["plan_hash"])` with

```python
    submitted = session_call(server, "weather_submit", {"plan_hash": plan["plan_hash"]},
                             approve=True).structuredContent
```

and add `runner.close()` as the test's last line.

- [ ] **Step 8: Raise the MCP floor**

In `pyproject.toml` change `mcp = ["mcp>=1.20,<2"]` to `mcp = ["mcp>=1.30,<2"]` and, in the `harness` extra, `"mcp>=1.20,<2"` to `"mcp>=1.30,<2"`.

- [ ] **Step 9: Run the approval, job, harness and pilot tests**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_approval.py tests/unit/test_stage4_mcp_jobs.py tests/unit/test_jobs.py tests/mcp tests/harness tests/pilot -q`
Expected: all PASS (pilot tests that need network stay skipped).

- [ ] **Step 10: Lint, type-check and commit**

Run: `.venv/Scripts/python.exe -m ruff check src tests` then `.venv/Scripts/python.exe -m mypy`
Expected: no errors.

```bash
git add pyproject.toml src/openepw/mcp/approval.py src/openepw/mcp/server.py src/openepw/models/__init__.py src/openepw/jobs src/openepw/api/app.py src/openepw/chat/coordinator.py src/openepw/harness tests/unit/mcp_memory.py tests/unit/test_mcp_approval.py tests/unit/test_stage4_mcp_jobs.py tests/harness/test_agent.py tests/pilot/test_journeys.py
git commit -m "fix(mcp): require the person's confirmation before weather submission"
```

---

### Task 8: Tool access classes, documentation and full verification

**Files:**
- Create: `src/openepw/mcp/access.py`
- Test: `tests/mcp/test_contract.py` (append)
- Modify: `docs/mcp/README.md`, `ARCHITECTURE.md` (Interfaces section), `FEATURES.md` (Local MCP contract row), `docs/decisions/0005-mcp-agent-chat.md` (status), `.github/workflows/ci.yml` is **not** changed in P1

**Interfaces:**
- Produces: `MODEL_TOOLS`, `HOST_TOOLS`, `LEGACY_TOOLS` (frozensets of tool names) for the P2 agent host.

- [ ] **Step 1: Write the failing test** — append to `tests/mcp/test_contract.py`

```python
def test_every_registered_tool_has_exactly_one_access_class(tmp_path):
    from openepw.mcp.access import HOST_TOOLS, LEGACY_TOOLS, MODEL_TOOLS

    server = create_server(WeatherService(RuntimeConfig(data_root=tmp_path)))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == MODEL_TOOLS | HOST_TOOLS | LEGACY_TOOLS
    assert not (MODEL_TOOLS & HOST_TOOLS or MODEL_TOOLS & LEGACY_TOOLS or HOST_TOOLS & LEGACY_TOOLS)
    assert "weather_submit" in HOST_TOOLS and "weather_plan" in MODEL_TOOLS
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/Scripts/python.exe -m pytest tests/mcp/test_contract.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'openepw.mcp.access'`.

- [ ] **Step 3: Create `src/openepw/mcp/access.py`**

```python
"""Which tools a model may call, which the host calls on a person's action, which are legacy."""

MODEL_TOOLS = frozenset({
    "weather_places_interpret", "weather_geocode", "weather_places_preview", "weather_place_set",
    "weather_locations_review", "weather_product_offers", "weather_assess", "weather_plan",
    "plan_inspect", "job_inspect", "artifact_inspect", "weather_data_describe",
    "weather_visualization_capabilities", "weather_visualize",
})
HOST_TOOLS = frozenset({
    "weather_submit", "job_cancel", "job_retry_failed", "weather_export_compact",
    "epw_upload", "epw_register_path", "weather_data_page",
})
LEGACY_TOOLS = frozenset({"weather_discover", "weather_fetch", "weather_inspect"})
```

- [ ] **Step 4: Update `docs/mcp/README.md`**

Replace the section from `## Tools and results` through the paragraph ending `simulation_ready=false; do not claim simulator certification.` with:

```markdown
## Tools and results

Tools are grouped by who calls them (`openepw.mcp.access`). Each result's text content is a
short summary for model context with the identifiers needed to continue; `structuredContent`
holds the bounded full data for renderers. Dict parameters publish inlined JSON schemas.

| Group | Tools |
| --- | --- |
| Model may call | `weather_places_interpret`, `weather_geocode`, `weather_places_preview`, `weather_place_set`, `weather_locations_review`, `weather_product_offers`, `weather_assess`, `weather_plan`, `plan_inspect`, `job_inspect`, `artifact_inspect`, `weather_data_describe`, `weather_visualization_capabilities`, `weather_visualize` |
| Host on a person's action | `weather_submit`, `job_cancel`, `job_retry_failed`, `weather_export_compact`, `epw_upload`, `epw_register_path`, `weather_data_page` |
| Legacy | `weather_discover` (planning discovers internally), `weather_fetch`, `weather_inspect` |

`weather_locations_review` returns points with fixed standard-time offsets (estimated from
longitude when missing), a standard-time note and a location key. `weather_product_offers`
returns named downloadable products with catalog availability per location.

## Approval

`weather_submit` and the legacy `weather_fetch` ask the client to confirm with the person
through MCP elicitation before any provider retrieval. A client without elicitation support
receives `APPROVAL_REQUIRED`; a declined confirmation returns `APPROVAL_DECLINED`. Jobs record
`approved_via` (`elicitation`, `api` or `chat`). The legacy console answers the confirmation
for plans it was told to submit (`StdioMCPPort.approve`).

## Errors and limits

Tool failures set `isError=true` with JSON `{code, message, retryable}`. Validation errors add
`details: [{loc, msg}]` without input values; unexpected failures add a `correlation_id` that
is logged on the server. Results are capped at 160 KB; plans and job summaries page or
truncate at 50 rows; an oversized query returns `RESOURCE_LIMIT`. One process runs jobs for a
data root; a second gets `DATA_ROOT_BUSY`. Future-weather endpoints remain suspended
(`FEATURE_SUSPENDED`). A catalog `supported` answer means eligible to try retrieval; only
output QC describes retrieved-weather gaps. Every manifest records `simulation_ready=false`.
```

In the "Example flow" list, change step 2 to: "Call `weather_locations_review`, get the person's approval, call `weather_product_offers` and let them choose, then `weather_plan`; inspect its `plan_hash`, rows and warnings. After the person approves, call `weather_submit` with that hash and confirm when asked."

- [ ] **Step 5: Update `ARCHITECTURE.md`, `FEATURES.md` and ADR 0005**

In `ARCHITECTURE.md`, after the paragraph that ends `See [local MCP contract](docs/mcp/README.md).` (around line 254), add:

```markdown
Since 2026-10 (ADR 0005, P1) the MCP server is shaped for tool-calling agents: product offers
and location offset review are `WeatherService` operations with MCP tools; dict parameters
publish inlined schemas; results carry a short model summary plus structured data; submission
requires an MCP elicitation confirmation; and the API process shares its single `JobRunner`
with an in-process MCP server (`app.state.mcp_server`). A data-root lock keeps job execution
to one process.
```

In `FEATURES.md`, replace the third column of the `| Local MCP contract |` row with:
`Real stdio and in-memory SDK sessions, typed tool schemas, summarized results, location review and product offer tools, elicitation-confirmed submission, one runner per data root; existing future records remain readable; no remote auth rollout`.

In `docs/decisions/0005-mcp-agent-chat.md`, replace the status sentence with:
`Status: design agreed with the owner on 2026-10-04/05; P1 (service moves and MCP contract) implemented on feature/mcp-agent-chat; P2–P5 pending.`

- [ ] **Step 6: Run the full verification**

Run each and record the actual result lines:

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe -m build
```

Expected: pytest passes with only the existing live/optional skips; ruff, mypy and build succeed. If any pre-existing test outside this plan fails, check it against `fd8d659` (`git stash; pytest <test>; git stash pop`) before changing anything, and report it.

- [ ] **Step 7: Commit**

```bash
git add src/openepw/mcp/access.py tests/mcp/test_contract.py docs/mcp/README.md ARCHITECTURE.md FEATURES.md docs/decisions/0005-mcp-agent-chat.md
git commit -m "fix(docs): document the agent-ready MCP contract and tool access"
```

---

## Later phases (separate plans)

Each phase gets its own plan written after the previous phase lands, so it builds on the real
interfaces rather than guesses.

| Phase | Plan scope | Depends on |
| --- | --- | --- |
| P2 | `openepw.agent`: `interactions`, `session` (SQLite event log, revisions, back snapshots), `gates`, `tools` (ask-tools, result shaping using `MODEL_TOOLS`), `mcp_port` (in-memory and stdio, `approval_callback`), `policy_guided`; `openepw chat` CLI text renderer; guided scenario evals S1–S5, S9–S12, S15, S17, S18, S21, S22 | P1 tools, access classes, approval |
| P3 | `model_port` (OpenAI adapter with ledger and budget stop, `ScriptedModel`), `policy_model` loop with limits, suspension and repair; mode switching; scripted scenarios S6–S8, S13, S14, S16, S19, S20; `openepw eval` with live opt-in | P2 session and gates |
| P4 | `/v2/agent` routes with SSE in FastAPI over `app.state.mcp_server`; React form renderer and mode toggle; parity tests and vitest fixtures; CI `web` job; optional streamable HTTP `/mcp` behind bearer auth (deferred here from P1); browser check | P3 |
| P5 | Retire `ChatCoordinator`, `chat/products.py` shim, `ReferenceAgent`, `ChatSession`, `GraphChatSession`, `/v1/chat/*`; docs and validation record | P4 evals passing in both renderers |

Merging into `deploy/staging` needs the owner's explicit go-ahead after P4. The
`feature/account-login` branch also edits `api/app.py` (site gate); expect a merge conflict
there when the branches meet.

## Execution notes (2026-10-05)

Owner-approved deviations made during execution. The code blocks above are left as written
and are superseded where they differ.

- Task 3 (summaries): MCP result summaries never put data rows into text. An unknown or
  failed summary falls back to a key-only stub (field names plus identifier values) and logs a
  warning. Full summarizer tests were added.
- Task 7 (retry): `job_retry_failed` does not run "under the original approval" as the
  description text above says. It asks the person to confirm through elicitation, naming the
  original job's plan hash; validation that cannot start anything runs before the prompt, and a
  weather plan with no outputs is refused with `NO_EXECUTABLE_OUTPUTS` before any prompt. REST
  `/v1/jobs/{id}/retry` and the web chat retry keep the original job's `approved_via`. The
  legacy console approves the original plan for `/retry`.
- Data-root lock: it is per process, so owners within one process share it; a second process
  on the same data root fails at startup with `DATA_ROOT_BUSY`.
- Final-review fixes:
  - Owned-runner lifecycle: the SDK enters the server lifespan once per client session, so a
    runner owned by `create_server` now recovers (taking the data-root lock) on the first
    session only and is never closed per session; `openepw mcp` closes it when the server
    stops. A supplied runner is still left to its owner.
  - Argument-error mapping: an `OpenEPWMCP` FastMCP subclass unwraps the SDK's
    "Error executing tool" wrapper, so argument-validation errors become bare-JSON
    `INVALID_REQUEST` with `details` (no input values) and every tool error is bare JSON.
    Generic `ValueError`/`TypeError` mappings are logged by exception type.
  - Offer request mapping: each `product_offers` option carries
    `request: {product, dataset_selections}`, the `WeatherRequest` fields that choose it.
  - Retry prompt: `job_retry_failed` asks "Approve retrying the failed or missing outputs of
    job <id> from reviewed weather plan <hash>?", which keeps the `plan <hash>` token.
- Deferred to later phases:
  - Offers do not yet carry the availability evidence dates promised in spec section 5; this
    moves to the P2 product-gate work.
  - P2 must decide whether the host substitutes the approved geography and selections into
    `weather_plan` (or passes references), and expose one service helper that computes the
    review key from a request.
  - Cap points before validating in `review_locations`, and add a location cap to
    `weather_product_offers`.
  - Lock hardening, with P4 HTTP hosting: the lock leaks if `recover` raises, release is not
    exception-safe, `OSError` classification, and the broad `except ImportError` in `app.py`.
  - A per-root runner registry so two runners in one process cannot both recover jobs.
  - One-shot approvals bound to the plan-review revision in P2 (the legacy
    `StdioMCPPort.approved` set is sticky).
  - A sanitized traceback at DEBUG level for correlation ids.
  - Per-tool expected identifiers in the summary test.
