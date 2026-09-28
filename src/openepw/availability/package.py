"""The availability catalog as a public CSV data package.

``export_package`` writes a catalog bundle as CSV tables plus a Frictionless
``datapackage.json`` that records every file's schema, byte size and SHA-256.
``load_package`` verifies each file against the descriptor and rebuilds the same bundle,
so a published package can seed a catalog without an opaque database file.

Layout, one directory per provider so each source's licence applies to its own files::

    datapackage.json
    data/sources.csv                   evidence: where each record came from
    data/reviews.csv                   owner-reviewed OneBuilding catalog decisions
    data/<provider>/products.csv       one row per product
    data/<provider>/sites.csv          stations and published locations
    data/<provider>/entries.csv        availability, one row per product/site scope
    data/<provider>/month-counts.csv   hourly records per month for actual-year entries
    data/footprints/...                coverage masks, copied byte for byte

Cells are empty for missing values, lists and mappings are JSON, dates and times are
ISO 8601 and numbers keep their full precision. Empty strings are not representable and
are refused on export rather than silently turned into missing values.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import (
    AvailabilityEntry,
    CatalogBundle,
    EvidenceRef,
    ProductRecord,
    ReviewAnnotation,
    SiteRecord,
)

PROFILE = "tabular-data-package"
MONTHS = [f"m{month:02d}" for month in range(1, 13)]


class PackageError(ValueError):
    """The package is incomplete, altered or not representable; nothing was loaded."""


@dataclass(frozen=True)
class LoadedPackage:
    descriptor: dict
    bundle: CatalogBundle
    footprints: dict[str, bytes] = field(default_factory=dict)


# Column name, Frictionless type and description, table by table.
SOURCES = [
    ("id", "string", "Evidence identifier referenced by other tables"),
    ("source_url", "string", "Where the evidence was read"),
    ("sha256", "string", "SHA-256 of the retrieved source"),
    ("retrieved_at", "datetime", "When the source was downloaded"),
    ("checked_at", "datetime", "When the source was last checked"),
    ("basis", "string", "documentation, inventory, targeted_probe or review"),
    ("last_modified", "string", "HTTP Last-Modified of the source"),
    ("etag", "string", "HTTP ETag of the source"),
    ("published_at", "date", "Publication date stated by the source"),
    ("terms", "string", "Terms or licence stated by the source"),
    ("attribution", "string", "Attribution the source asks for"),
    ("scope", "string", "What part of the source the evidence covers"),
]
PRODUCTS = [
    ("id", "string", "Product identifier"),
    ("provider", "string", "Data provider"),
    ("dataset", "string", "Provider dataset name"),
    ("version", "string", "Dataset version"),
    ("access_route", "string", "How the data is fetched"),
    ("native_product_id", "string", "Provider's own identifier or file URL"),
    ("spatial_kind", "string", "point, station, grid, area or unknown"),
    ("temporal_kind", "string", "actual, tmy_reference or future_window"),
    ("footprint_west", "number", "Coverage bounding box, west longitude"),
    ("footprint_south", "number", "Coverage bounding box, south latitude"),
    ("footprint_east", "number", "Coverage bounding box, east longitude"),
    ("footprint_north", "number", "Coverage bounding box, north latitude"),
    ("longitude_convention", "string", "-180_180 or 0_360"),
    ("source_variables", "array", "Variables the source publishes"),
    ("adapter_variables", "array", "Variables openepw reads from it"),
    ("adapter_supported", "boolean", "Whether openepw can download it"),
    ("native_resolution_minutes", "integer", "Native time step"),
    ("delivered_resolution_minutes", "integer", "Time step as delivered"),
    ("access_requirements", "array", "Keys or terms needed to download"),
    ("citation", "string", "How to cite the product"),
    ("license_effective", "string", "Licence in force"),
    ("license_original", "string", "Licence at first publication"),
    ("license_history", "string", "Licence changes"),
    ("evidence_ids", "array", "Evidence in sources.csv"),
]
SITES = [
    ("id", "string", "Site identifier"),
    ("product_id", "string", "Product in products.csv"),
    ("name", "string", "Published station name"),
    ("lat", "number", "Latitude, degrees north"),
    ("lon", "number", "Longitude, degrees east"),
    ("elevation_m", "number", "Elevation, metres"),
    ("position_status", "string", "How the position is known"),
    ("station_identity_status", "string", "How the station identity is known"),
    ("candidate_station_ids", "array", "Station identifiers that may match"),
    ("operating_start", "date", "First day of operation"),
    ("operating_end", "date", "Last day of operation"),
    ("evidence_ids", "array", "Evidence in sources.csv"),
]
ENTRIES = [
    ("id", "string", "Entry identifier"),
    ("product_id", "string", "Product in products.csv"),
    ("site_id", "string", "Site in sites.csv; empty for gridded products"),
    ("scope_kind", "string", "actual, tmy_reference or future_window"),
    ("years", "array", "actual: years with data"),
    ("operating_start", "date", "actual: first day available"),
    ("operating_end", "date", "actual: last day available"),
    ("start_year", "integer", "tmy_reference/future_window: first year of the period"),
    ("end_year", "integer", "tmy_reference/future_window: last year of the period"),
    ("product_label", "string", "tmy_reference: published product label"),
    ("selected_month_years", "object", "tmy_reference: year chosen for each month"),
    ("scenario", "string", "future_window: emissions scenario"),
    ("model", "string", "future_window: climate model"),
    ("member", "string", "future_window: ensemble member"),
    ("grid", "string", "future_window: model grid"),
    ("listed_years", "array", "future_window: years listed by the source"),
    ("variables", "array", "Variables available"),
    ("evidence_ids", "array", "Evidence in sources.csv"),
    ("evidence_basis", "string", "documentation, inventory or targeted_probe"),
    ("exclusions", "array", "Known exclusions"),
    ("weather_complete", "boolean", "Whether all EPW weather fields are present"),
    ("probe_lat", "number", "targeted_probe: latitude probed"),
    ("probe_lon", "number", "targeted_probe: longitude probed"),
    ("probe_id", "string", "targeted_probe: location identifier"),
    ("probe_name", "string", "targeted_probe: location name"),
    ("probe_elevation", "number", "targeted_probe: elevation, metres"),
    ("probe_standard_offset_minutes", "integer", "targeted_probe: standard time offset"),
    ("source_etag", "string", "ETag of the source file"),
]
MONTH_COUNTS = [("entry_id", "string", "Entry in entries.csv"), ("year", "integer", "Calendar year")] + [
    (name, "integer", f"Hourly records in month {name[1:]}") for name in MONTHS]
REVIEWS = [
    ("catalog_url", "string", "Reviewed OneBuilding file"),
    ("product_id", "string", "Product in onebuilding/products.csv"),
    ("status", "string", "Review outcome"),
    ("rationale", "string", "Why"),
    ("accepted_on", "date", "Date the owner accepted it"),
    ("evidence_ids", "array", "Evidence in sources.csv"),
    ("source_checksums", "object", "SHA-256 of each evidence source at review"),
    ("alternate_url", "string", "Equivalent file elsewhere"),
    ("coordinate_authority", "string", "Where the coordinates come from"),
    ("original_position_status", "string", "Position status before review"),
    ("original_match_reason", "string", "Match reason before review"),
    ("epw_coordinates_verified", "boolean", "EPW header coordinates checked"),
    ("weather_equivalence_verified", "boolean", "Weather data compared"),
]
_SCOPE_COLUMNS = {
    "actual": ("years", "operating_start", "operating_end"),
    "tmy_reference": ("start_year", "end_year", "product_label", "selected_month_years"),
    "future_window": ("start_year", "end_year", "scenario", "model", "member", "grid", "listed_years"),
}
_FOOTPRINT = ("footprint_west", "footprint_south", "footprint_east", "footprint_north")
_PROBE = {"probe_lat": "lat", "probe_lon": "lon", "probe_id": "id", "probe_name": "name",
          "probe_elevation": "elevation", "probe_standard_offset_minutes": "standard_offset_minutes"}
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


# -- cells ------------------------------------------------------------------------------

def _cell(value, kind: str, where: str) -> str:
    if value is None:
        return ""
    if kind in ("array", "object"):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if kind == "boolean":
        return "true" if value else "false"
    if kind == "number":
        return repr(float(value))
    if kind == "integer":
        return str(int(value))
    if value == "":
        raise PackageError(f"{where} is an empty string, which a CSV cell cannot tell from missing")
    return str(value)


def _value(cell: str, kind: str):
    if cell == "":
        return None
    if kind in ("array", "object"):
        return json.loads(cell)
    if kind == "boolean":
        if cell not in ("true", "false"):
            raise ValueError(f"not a boolean: {cell!r}")
        return cell == "true"
    if kind == "number":
        return float(cell)
    if kind == "integer":
        return int(cell)
    return cell                                   # strings, and ISO dates the models parse


# -- rows -------------------------------------------------------------------------------

def _plain(record) -> dict:
    return record.model_dump(mode="json")


def _product_row(product: ProductRecord) -> dict:
    row = _plain(product)
    footprint = row.pop("footprint")
    row.update(zip(_FOOTPRINT, footprint or (None,) * 4))
    return row


def _entry_row(entry: AvailabilityEntry) -> dict:
    row = _plain(entry)
    scope = row.pop("scope")
    kind = scope.pop("kind")
    scope.pop("month_counts", None)
    row["scope_kind"] = kind
    row.update(scope)
    probe = row.pop("probe_location") or {}
    row.update({column: probe.get(key) for column, key in _PROBE.items()})
    return row


def _product(row: dict) -> ProductRecord:
    corners = [row.pop(name) for name in _FOOTPRINT]
    row["footprint"] = None if all(corner is None for corner in corners) else corners
    return ProductRecord.model_validate(_present(row))


def _entry(row: dict, month_counts: dict) -> AvailabilityEntry:
    kind = row.pop("scope_kind")
    scope = {"kind": kind}
    for name in {column for columns in _SCOPE_COLUMNS.values() for column in columns}:
        value = row.pop(name)
        if name in _SCOPE_COLUMNS.get(kind, ()) and value is not None:
            scope[name] = value
    if kind == "actual":
        scope["month_counts"] = month_counts.get(row["id"], {})
    probe = {key: row.pop(column) for column, key in _PROBE.items()}
    row["probe_location"] = _present(probe) or None
    row["scope"] = scope
    return AvailabilityEntry.model_validate(_present(row))


def _present(row: dict) -> dict:
    """Leave missing cells out so each model applies its own defaults."""
    return {name: value for name, value in row.items() if value is not None}


# -- files ------------------------------------------------------------------------------

def _csv(columns, rows, where: str) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([name for name, _, _ in columns])
    for row in rows:
        extra = set(row) - {name for name, _, _ in columns}
        if extra:
            raise PackageError(f"{where} has fields the package does not describe: {sorted(extra)}")
        writer.writerow([_cell(row.get(name), kind, f"{where} {row.get('id', '')}.{name}")
                         for name, kind, _ in columns])
    return buffer.getvalue().encode("utf-8")


def _schema(columns, key, foreign=()) -> dict:
    fields = []
    for name, kind, description in columns:
        item = {"name": name, "type": kind, "description": description}
        if kind == "date":
            item["format"] = "%Y-%m-%d"
        fields.append(item)
    schema = {"fields": fields, "missingValues": [""], "primaryKey": key}
    if foreign:
        schema["foreignKeys"] = [{"fields": column, "reference": {"resource": resource, "fields": target}}
                                 for column, resource, target in foreign]
    return schema


def _resource_name(path: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", path.lower().removesuffix(".csv").replace("/", "-"))


def export_package(bundle: CatalogBundle, out: Path, footprints_root: Path | None, *,
                   name: str, version: str, metadata: dict | None = None) -> Path:
    """Write ``bundle`` and the footprint files as a data package; returns datapackage.json."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    provider_of = {product.id: product.provider for product in bundle.products}
    providers = sorted(set(provider_of.values()))
    for provider in providers:
        if not _PROVIDER.match(provider):
            raise PackageError(f"Provider name {provider!r} cannot be a folder name")

    def grouped(records, product_id):
        groups: dict[str, list] = {provider: [] for provider in providers}
        for record in records:
            if product_id(record) not in provider_of:
                raise PackageError(f"{record.id} refers to an unknown product")
            groups[provider_of[product_id(record)]].append(record)
        return groups

    sites = grouped(bundle.sites, lambda site: site.product_id)
    entries = grouped(bundle.entries, lambda entry: entry.product_id)
    tables: list[tuple] = [("data/sources.csv", SOURCES, [_plain(e) for e in bundle.evidence], ["id"], ()),
              ("data/reviews.csv", REVIEWS, [_plain(r) for r in bundle.reviews], ["catalog_url"], ())]
    for provider in providers:
        base = f"data/{provider}"
        products = [p for p in bundle.products if p.provider == provider]
        months = [{"entry_id": entry.id, "year": year, **{MONTHS[m - 1]: count for m, count in counts.items()}}
                  for entry in entries[provider] if entry.scope.kind == "actual"
                  for year, counts in entry.scope.month_counts.items()]
        for row in months:
            if set(row) - {"entry_id", "year", *MONTHS}:
                raise PackageError(f"{row['entry_id']} has a month outside 1-12")
        tables += [
            (f"{base}/products.csv", PRODUCTS, [_product_row(p) for p in products], ["id"], ()),
            (f"{base}/sites.csv", SITES, [_plain(s) for s in sites[provider]], ["id"],
             [("product_id", _resource_name(f"{base}/products.csv"), "id")]),
            (f"{base}/entries.csv", ENTRIES, [_entry_row(e) for e in entries[provider]], ["id"],
             [("product_id", _resource_name(f"{base}/products.csv"), "id")]),
        ]
        if months:
            tables.append((f"{base}/month-counts.csv", MONTH_COUNTS, months, ["entry_id", "year"],
                           [("entry_id", _resource_name(f"{base}/entries.csv"), "id")]))

    resources = []
    for path, columns, rows, key, foreign in tables:
        data = _csv(columns, rows, path)
        resources.append({"name": _resource_name(path), "path": path, "profile": "tabular-data-resource",
                          "format": "csv", "mediatype": "text/csv", "encoding": "utf-8",
                          **_stamp(out, path, data), "schema": _schema(columns, key, foreign)})
    if footprints_root is not None and Path(footprints_root).is_dir():
        root = Path(footprints_root)
        for file in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if file.is_file():
                path = f"data/footprints/{file.relative_to(root).as_posix()}"
                resources.append({"name": _resource_name(path), "path": path, "format": file.suffix.lstrip("."),
                                  "mediatype": "application/json" if file.suffix == ".json" else
                                  "application/octet-stream", **_stamp(out, path, file.read_bytes())})
    descriptor = {"profile": PROFILE, "name": name, "version": version, **(metadata or {}),
                  "catalog_schema_version": bundle.schema_version, "resources": resources}
    target = out / "datapackage.json"
    target.write_text(json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return target


def _stamp(out: Path, path: str, data: bytes) -> dict:
    target = out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"bytes": len(data), "hash": f"sha256:{hashlib.sha256(data).hexdigest()}"}


# -- loading ----------------------------------------------------------------------------

def safe_path(path) -> str:
    """A resource path inside the package: relative, POSIX, no parent steps."""
    if not isinstance(path, str) or not path or "\\" in path or ":" in path:
        raise PackageError(f"Resource path {path!r} is not a relative POSIX path")
    if any(part in ("..", ".", "") for part in path.split("/")):
        raise PackageError(f"Resource path {path!r} leaves the package")
    return path


def verify(resource: dict, data: bytes):
    """Refuse a file whose size or SHA-256 differs from the descriptor."""
    path = resource.get("path")
    expected = str(resource.get("hash", ""))
    if not expected.startswith("sha256:") or len(expected) != 71:
        raise PackageError(f"{path} has no SHA-256 in the descriptor")
    if resource.get("bytes") != len(data) or hashlib.sha256(data).hexdigest() != expected[7:]:
        raise PackageError(f"{path} does not match its size or SHA-256 in the descriptor")


def load_package(descriptor_path: Path) -> LoadedPackage:
    """Verify every file of a package on disk and rebuild the catalog bundle."""
    descriptor_path = Path(descriptor_path)
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    files = {}
    for resource in descriptor.get("resources", []):
        path = safe_path(resource.get("path"))
        try:
            data = (descriptor_path.parent / path).read_bytes()
        except OSError:
            raise PackageError(f"{path} is missing") from None
        verify(resource, data)
        files[path] = data
    return from_files(descriptor, files)


def from_files(descriptor: dict, files: dict[str, bytes]) -> LoadedPackage:
    """Rebuild the bundle from verified file contents keyed by resource path."""
    if descriptor.get("catalog_schema_version") != "1":
        raise PackageError("The package holds an unsupported catalog schema version")
    tables: dict[str, list[dict]] = {}
    for resource in descriptor["resources"]:
        if resource.get("format") != "csv":
            continue
        path = resource["path"]
        columns = [(item["name"], item["type"]) for item in resource["schema"]["fields"]]
        try:
            reader = csv.reader(io.StringIO(files[path].decode("utf-8"), newline=""))
            header = next(reader)
            if header != [name for name, _ in columns]:
                raise PackageError(f"{path} columns differ from its schema")
            tables[path] = [{name: _value(cell, kind) for (name, kind), cell in zip(columns, row, strict=True)}
                            for row in reader]
        except (ValueError, StopIteration) as error:
            if isinstance(error, PackageError):
                raise
            raise PackageError(f"{path} could not be read: {error}") from None

    def rows(suffix):
        return [row for path in sorted(tables) if path.endswith(suffix) for row in tables[path]]

    month_counts: dict[str, dict] = {}
    for row in rows("/month-counts.csv"):
        counts = {month: row[name] for month, name in enumerate(MONTHS, 1) if row[name] is not None}
        month_counts.setdefault(row["entry_id"], {})[row["year"]] = counts
    try:
        bundle = CatalogBundle(
            evidence=[EvidenceRef.model_validate(_present(row)) for row in tables.get("data/sources.csv", [])],
            products=[_product(row) for row in rows("/products.csv")],
            sites=[SiteRecord.model_validate(_present(row)) for row in rows("/sites.csv")],
            entries=[_entry(row, month_counts) for row in rows("/entries.csv")],
            reviews=[ReviewAnnotation.model_validate(_present(row)) for row in tables.get("data/reviews.csv", [])],
        )
    except ValueError as error:
        raise PackageError(f"The package does not describe a valid catalog: {error}") from None
    footprints = {path.removeprefix("data/footprints/"): data for path, data in files.items()
                  if path.startswith("data/footprints/")}
    return LoadedPackage(descriptor, bundle, footprints)
