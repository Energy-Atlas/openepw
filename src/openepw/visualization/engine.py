"""EPW-to-view semantics; independent of MCP, CLI and rendering libraries."""

import calendar
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..artifacts.store import ArtifactStore
from ..dataset import WeatherDataset, local_interval_starts
from ..epw import read_epw
from ..models import OpenEPWError
from .catalog import INITIAL_FAMILIES, VARIABLES
from .models import VisualizationRequest, VisualizationSpec


@dataclass
class Source:
    artifact_id: str
    sha256: str
    dataset: WeatherDataset
    temporal_kind: str
    product: str | None
    provider: str | None = None
    dataset_name: str | None = None
    resolved_location: dict | None = None
    lineage: dict | None = None

    @property
    def local(self) -> pd.DatetimeIndex:
        return local_interval_starts(self.dataset)

    @property
    def years(self) -> list[int]:
        if self.dataset.calendar == "synthetic":
            return []
        labels = self.dataset.source_years
        if self.dataset.calendar == "noleap" and len(set(labels)) == 1:
            return list(set(labels))
        return sorted(set(int(year) for year in self.local.year))

    def metadata(self, variable: str | None = None) -> dict:
        dataset = self.dataset
        result = {
            "artifact_id": self.artifact_id,
            "sha256": self.sha256,
            "temporal_kind": self.temporal_kind,
            "product": self.product,
            "provider": self.provider,
            "dataset": self.dataset_name,
            "calendar": dataset.calendar,
            "years": self.years,
            "rows": len(dataset.data),
            "location": dataset.location.model_dump(mode="json"),
        }
        if self.resolved_location is not None:
            result["resolved_location"] = self.resolved_location
        if variable and self.lineage and variable in self.lineage:
            result["lineage"] = self.lineage[variable]
        return result


def _load(store: ArtifactStore, artifact_id: str) -> Source:
    ref, path = store.resolve(artifact_id)
    if ref.role not in ("weather", "baseline") or ref.bytes > 10_000_000:
        raise OpenEPWError("INVALID_ARTIFACT", "A bounded EPW artifact is required")
    temporal_kind = "unverified"
    product = None
    provider = None
    dataset_name = None
    resolved_location = None
    lineage = None
    if ref.role == "weather":
        bundle_dir = store.root / Path(ref.path).parent
        try:
            plan_ref = store.sibling(ref, "plan.json", "plan")
        except OpenEPWError:
            if (bundle_dir / "plan.json").exists():
                raise OpenEPWError("INVALID_ARTIFACT", "Linked plan failed verification") from None
            plan_ref = None
        if plan_ref:
            _, plan_path = store.resolve(plan_ref.id)
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise OpenEPWError("INVALID_ARTIFACT", "Linked plan is unreadable") from None
            if plan.get("kind") == "future":
                raise OpenEPWError("FEATURE_SUSPENDED", "Future weather views are suspended")
            product = plan.get("request", {}).get("product")
            temporal_kind = ("reference" if product in ("tmy", "tmyx", "published")
                             else "actual" if product in ("historical", "amy")
                             else "unverified")
        try:
            manifest_ref = store.sibling(ref, "manifest.json", "manifest")
        except OpenEPWError:
            if (bundle_dir / "manifest.json").exists():
                raise OpenEPWError("INVALID_ARTIFACT", "Linked manifest failed verification") from None
            manifest_ref = None
        if manifest_ref:
            _, manifest_path = store.resolve(manifest_ref.id)
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                entry = next((item for item in manifest.get("outputs", [])
                              if item.get("artifact_id") == ref.id), None)
                native_source = entry.get("source", {}) if entry else {}
                provider = native_source.get("provider")
                dataset_name = native_source.get("dataset")
                resolved_location = native_source.get("location")
                lineage = entry.get("lineage") if entry else None
            except (OSError, ValueError, TypeError, AttributeError):
                raise OpenEPWError("INVALID_ARTIFACT", "Linked manifest is unreadable") from None
    dataset = read_epw(path)
    if not dataset.data.index.is_unique or not dataset.data.index.is_monotonic_increasing:
        raise OpenEPWError("INVALID_ARTIFACT", "EPW intervals are duplicate or unordered")
    if np.isinf(dataset.data.select_dtypes(include=[np.number]).to_numpy(dtype=float)).any():
        raise OpenEPWError("INVALID_ARTIFACT", "EPW contains nonfinite numeric values")
    if dataset.calendar == "synthetic":
        temporal_kind = "reference" if temporal_kind == "reference" else "unverified"
    return Source(ref.id, ref.sha256, dataset, temporal_kind, product,
                  provider, dataset_name, resolved_location, lineage)


def _sources(store: ArtifactStore, artifact_ids: list[str]) -> list[Source]:
    if not artifact_ids or len(artifact_ids) > 100 or len(set(artifact_ids)) != len(artifact_ids):
        raise OpenEPWError("RESOURCE_LIMIT", "Provide 1 to 100 distinct EPW artifact IDs")
    return [_load(store, artifact_id) for artifact_id in artifact_ids]


def describe_sources(store: ArtifactStore, artifact_ids: list[str]) -> dict:
    if len(artifact_ids) > 20:
        raise OpenEPWError("RESOURCE_LIMIT", "Describe at most 20 EPWs at once")
    descriptions = []
    for source in _sources(store, artifact_ids):
        detail = source.metadata()
        expected = len(_expected_local(source))
        detail["variables"] = {
            variable: {"unit": entry["unit"],
                       "missing_hours": expected - int(source.dataset.data[variable].notna().sum()),
                       "valid_hours": int(source.dataset.data[variable].notna().sum())}
            for variable, entry in VARIABLES.items()
            if variable in source.dataset.data
        }
        descriptions.append(detail)
    return {"schema_version": "1", "sources": descriptions}


def _expected_hours(year: int, month: int | None, calendar_name: str) -> int:
    if month is None:
        return (8784 if calendar.isleap(year) and calendar_name != "noleap" else 8760)
    if month == 2 and calendar_name == "noleap":
        return 672
    return calendar.monthrange(year, month)[1] * 24


def _aggregate(values: pd.Series, expected: int, operation: str,
               allow_partial: bool) -> tuple[float | None, int, str]:
    valid = int(values.notna().sum())
    if valid == 0 or (valid != expected and not allow_partial):
        return None, valid, "incomplete"
    observed = values.dropna()
    result = {"mean": observed.mean, "sum": observed.sum,
              "min": observed.min, "max": observed.max}[operation]()
    return float(result), valid, "complete" if valid == expected else "partial"


def _expected_local(source: Source) -> pd.DatetimeIndex:
    local = source.local
    span = int((local[-1] - local[0]) / pd.Timedelta(hours=1)) + 1
    if span > 20_000:
        raise OpenEPWError("RESOURCE_LIMIT", "Source period exceeds 20,000 local hours")
    expected = pd.date_range(local[0], local[-1], freq="h")
    if source.dataset.calendar == "noleap":
        expected = expected[~((expected.month == 2) & (expected.day == 29))]
    return expected


def _period_rows(source: Source, variable: str, family: str, operation: str,
                 allow_partial: bool) -> list[dict]:
    if (source.temporal_kind == "reference" or source.dataset.calendar == "synthetic") and (
        family == "annual_series"
    ):
        raise OpenEPWError("INCOMPATIBLE_SOURCES", "Reference months are not an actual-year trend")
    local = source.local
    values = source.dataset.data[variable]
    years = source.years or [int(local[0].year)]
    rows = []
    for year in years:
        months = range(1, 13) if family == "monthly_series" else (None,)
        for month in months:
            index_year = (int(local[0].year) if source.dataset.calendar == "noleap"
                          else year)
            mask = (local.year == index_year)
            if month is not None:
                mask &= local.month == month
            expected = _expected_hours(year, month, source.dataset.calendar)
            value, valid, quality = _aggregate(values.iloc[np.flatnonzero(mask)], expected,
                                               operation, allow_partial)
            display_year = (None if source.temporal_kind == "reference" or
                            source.dataset.calendar == "synthetic" else year)
            rows.append({
                "artifact_id": source.artifact_id, "year": display_year, "month": month,
                "period": (f"reference-{month:02d}" if display_year is None else
                           f"{year:04d}-{month:02d}") if month else f"{year:04d}",
                "value": value, "expected_hours": expected,
                "valid_hours": valid, "missing_hours": expected - valid,
                "quality": quality,
            })
    return rows


def _hourly_rows(source: Source, variable: str) -> list[dict]:
    local = source.local
    expected = _expected_local(source)
    values = pd.Series(source.dataset.data[variable].to_numpy(), index=local).reindex(expected)
    rows = []
    for local_time, value in values.items():
        valid = not pd.isna(value)
        rows.append({"artifact_id": source.artifact_id,
                     "period": pd.Timestamp(str(local_time)).isoformat(),
                     "value": float(value) if valid else None,
                     "expected_hours": 1, "valid_hours": int(valid),
                     "missing_hours": int(not valid),
                     "quality": "complete" if valid else "incomplete"})
    return rows


def _histogram_rows(sources: list[Source], variable: str, bins: int) -> tuple[list[dict], list[float]]:
    samples = [source.dataset.data[variable].dropna().to_numpy(dtype=float)
               for source in sources]
    nonempty = [values for values in samples if len(values)]
    if not nonempty:
        raise OpenEPWError("NO_MATCHING_DATA", "No valid values are available for the histogram")
    edges = np.histogram_bin_edges(np.concatenate(nonempty), bins=bins)
    rows = []
    for source, values in zip(sources, samples):
        counts, _ = np.histogram(values, bins=edges)
        expected = len(_expected_local(source))
        for index, count in enumerate(counts):
            rows.append({"artifact_id": source.artifact_id,
                         "bin_start": float(edges[index]),
                         "bin_end": float(edges[index + 1]), "count": int(count),
                         "expected_hours": expected, "valid_hours": len(values),
                         "missing_hours": expected - len(values),
                         "quality": "complete" if len(values) == expected else "partial"})
    return rows, [float(value) for value in edges]


def _spatial_rows(sources: list[Source], variable: str, operation: str,
                  allow_partial: bool) -> tuple[list[dict], dict, str]:
    if len(sources) < 2:
        raise OpenEPWError("INCOMPATIBLE_SOURCES", "Spatial view requires two or more locations")
    kinds = {source.temporal_kind for source in sources}
    years = {tuple(source.years) for source in sources}
    products = {source.product for source in sources}
    native_sources = {(source.provider, source.dataset_name) for source in sources}
    if len(kinds) != 1 or len(years) != 1 or len(products) != 1 or len(native_sources) != 1 or any(
        len(source.years) != 1 for source in sources
    ):
        raise OpenEPWError("INCOMPATIBLE_SOURCES",
                            "Spatial sources must share one period and product kind")
    rows = []
    for source in sources:
        period_row = _period_rows(source, variable, "annual_series", operation,
                                  allow_partial)[0]
        rows.append({**period_row, "lat": source.dataset.location.lat,
                     "lon": source.dataset.location.lon,
                     "location_id": source.dataset.location.id})
    coordinates = [(row["lat"], row["lon"]) for row in rows]
    if len(set(coordinates)) != len(coordinates):
        raise OpenEPWError("INCOMPATIBLE_SOURCES",
                            "Duplicate spatial coordinates require source selection")
    latitudes = sorted({lat for lat, _ in coordinates})
    longitudes = sorted({lon for _, lon in coordinates})
    if len(latitudes) * len(longitudes) == len(rows):
        lookup = {(row["lat"], row["lon"]): row for row in rows}
        encoding = {"latitudes": latitudes, "longitudes": longitudes,
                    "values": [[lookup[lat, lon]["value"] for lon in longitudes]
                               for lat in latitudes],
                    "quality": [[lookup[lat, lon]["quality"] for lon in longitudes]
                                for lat in latitudes]}
        return rows, encoding, "matrix"
    return rows, {"latitude": "lat", "longitude": "lon", "value": "value"}, "points"


def build_view(store: ArtifactStore, request: VisualizationRequest) -> dict:
    if request.family not in INITIAL_FAMILIES:
        raise OpenEPWError("VISUALIZATION_UNSUPPORTED",
                            f"{request.family} is planned; choose an implemented family")
    if request.variable not in VARIABLES:
        raise OpenEPWError("INVALID_VARIABLE", "Variable is not in the supported registry")
    if request.options and request.family != "histogram":
        raise OpenEPWError("INVALID_REQUEST", "Options are unsupported for this family")
    variable = VARIABLES[request.variable]
    operation = request.aggregation or ("sum" if request.variable in ("ghi", "dni", "dhi")
                                        else "mean")
    if request.family in ("annual_series", "monthly_series", "spatial") and (
        operation not in variable["aggregations"]
    ):
        raise OpenEPWError("INVALID_AGGREGATION", "Aggregation is not valid for this variable")
    sources = _sources(store, request.artifact_ids)
    if request.family == "annual_series" and len(sources) > 1 and any(
        source.temporal_kind != "actual" for source in sources
    ):
        raise OpenEPWError("INCOMPATIBLE_SOURCES",
                            "Annual trends require verified actual-year source identity")
    extra_encoding: dict = {}
    shape = "rows"
    if request.family in ("annual_series", "monthly_series"):
        rows = [row for source in sources for row in _period_rows(
            source, request.variable, request.family, operation, request.allow_partial)]
    elif request.family == "time_series":
        if sum(len(_expected_local(source)) for source in sources) > 20_000:
            raise OpenEPWError("RESOURCE_LIMIT", "Hourly view exceeds 20,000 rows")
        rows = [row for source in sources for row in _hourly_rows(source, request.variable)]
    elif request.family == "histogram":
        if request.aggregation is not None:
            raise OpenEPWError("INVALID_AGGREGATION", "Histogram uses observed values")
        rows, edges = _histogram_rows(sources, request.variable,
                                      request.options.get("bins", 10))
        extra_encoding = {"x": {"field": "bin_start", "end_field": "bin_end",
                                "variable": request.variable, "unit": variable["unit"],
                                "bin_edges": edges},
                          "y": {"field": "count", "unit": "hours"}}
    elif request.family == "spatial":
        rows, extra_encoding, shape = _spatial_rows(
            sources, request.variable, operation, request.allow_partial)
    else:
        raise OpenEPWError("VISUALIZATION_UNSUPPORTED",
                            f"{request.family} implementation is pending")
    if not rows:
        raise OpenEPWError("NO_MATCHING_DATA", "No weather intervals are present")
    if request.family == "histogram":
        expected = sum(len(_expected_local(source)) for source in sources)
        missing = expected - sum(int(source.dataset.data[request.variable].notna().sum())
                                 for source in sources)
    else:
        missing = sum(row["missing_hours"] for row in rows)
        expected = sum(row["expected_hours"] for row in rows)
    if request.family == "histogram":
        encodings = {**extra_encoding, "series": ["artifact_id"]}
    elif request.family == "spatial":
        encodings = {**extra_encoding,
                     "value": {"field": "value", "variable": request.variable,
                               "unit": variable["unit"]}}
    else:
        encodings = {"x": {"field": "period", "kind": "local_hour" if
                           request.family == "time_series" else "local_period"},
                     "y": {"field": "value", "variable": request.variable,
                           "unit": variable["unit"]}, "series": ["artifact_id"]}
    transforms = [{"operation": "select", "artifact_ids": request.artifact_ids}]
    if request.family in ("annual_series", "monthly_series", "spatial"):
        transforms.extend([{"operation": "group", "by": ["artifact_id", "year"] +
                           (["month"] if request.family == "monthly_series" else [])},
                           {"operation": "aggregate", "method": operation}])
    elif request.family == "histogram":
        transforms.append({"operation": "bin", "edges": encodings["x"]["bin_edges"]})
    spec = {
        "schema_version": "1", "family": request.family,
        "data_ref": {"view_id": None, "shape": shape, "total_rows": len(rows),
                     "page_tool": "weather_data_page"},
        "encodings": encodings,
        "transforms": transforms,
        "sources": [source.metadata(request.variable) for source in sources],
        "quality": {"expected_hours": expected, "valid_hours": expected - missing,
                    "missing_hours": missing},
        "summary": (f"{len(rows)} {request.family} points; {missing} missing hourly "
                    f"values across {len(sources)} source EPWs."),
    }
    return {"schema_version": "1", "request": request.model_dump(mode="json"),
            "specs": [VisualizationSpec.model_validate(spec).model_dump(mode="json")],
            "rows": rows, "total_rows": len(rows),
            "warnings": ([{"code": "INCOMPLETE_PERIOD"}] if missing else [])}
