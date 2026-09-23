"""Versioned wire contracts. Runtime credentials never belong in these objects."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_assignment=True)


class Issue(Model):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    field: str | None = None
    location_id: str | None = None
    task_id: str | None = None
    retryable: bool = False
    dataset_selection: dict[str, str | None] | None = None


class OpenEPWError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.issue = Issue(code=code, message=message, severity="error", retryable=retryable)
        super().__init__(f"{code}: {message}")


class Location(Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    id: str | None = None
    name: str | None = None
    elevation: float | None = None
    standard_offset_minutes: int = Field(default=0, ge=-720, le=840)

    @property
    def key(self) -> str:
        return self.id or digest(self.model_dump())[:16]


class BoundingBox(Model):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def valid(self):
        if self.south >= self.north or self.west == self.east:
            raise ValueError("Bounding box must have positive area")
        return self


class PolygonQuery(Model):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]

    @model_validator(mode="after")
    def valid(self):
        for ring in self.coordinates:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings must be closed with at least three vertices")
            for lon, lat in ring:
                Location(lat=lat, lon=lon)
        if not self.coordinates:
            raise ValueError("Empty polygon")
        return self


def nominal_offset_minutes(lon: float) -> int:
    """Approximate fixed standard time from longitude, not a legal time zone."""
    return math.floor(lon / 15 + 0.5) * 60


class SamplingSpec(Model):
    dx_km: float = Field(default=25, gt=0)
    dy_km: float = Field(default=25, gt=0)
    offset_x_km: float = 0
    offset_y_km: float = 0
    max_locations: int = Field(default=1000, ge=1, le=10000)
    standard_offset: Literal["utc", "longitude"] = "utc"


class HybridPolicy(Model):
    enabled: bool = False
    assignments: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if self.assignments and not self.enabled:
            raise ValueError("Variable assignments require explicit hybrid enabled")
        return self


class DatasetSelection(Model):
    provider: str = Field(min_length=1)
    dataset: str = Field(min_length=1)
    product_id: str | None = None


class WeatherRequest(Model):
    schema_version: Literal["0.1"] = "0.1"
    locations: list[Location] | Location | BoundingBox | PolygonQuery
    sampling: SamplingSpec = Field(default_factory=SamplingSpec)
    product: Literal["historical", "amy", "tmy", "tmyx", "published"] = "historical"
    years: list[int] = Field(default_factory=list)
    start: date | None = None
    end: date | None = None
    product_id: str | None = None
    providers: list[str] = Field(default_factory=list)
    dataset: str | None = None
    dataset_selections: list[DatasetSelection] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    required_variables: list[str] = Field(
        default_factory=lambda: [
            "dry_bulb",
            "dew_point",
            "relative_humidity",
            "pressure",
            "ghi",
            "dni",
            "dhi",
            "wind_speed",
            "wind_direction",
        ]
    )
    hybrid_policy: HybridPolicy = Field(default_factory=HybridPolicy)
    missing_policy: Literal["warn", "error"] = "warn"
    skip_feb_29: bool = Field(default=False, exclude_if=lambda value: not value)
    formats: list[Literal["epw"]] = Field(default_factory=lambda: ["epw"])

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_leap_policy(cls, value):
        if not isinstance(value, dict) or "leap_policy" not in value:
            return value
        data = dict(value)
        policy = data.pop("leap_policy")
        if policy not in ("preserve", "skip_feb_29"):
            raise ValueError("Unknown leap policy")
        skip = policy == "skip_feb_29"
        if "skip_feb_29" in data and data["skip_feb_29"] != skip:
            raise ValueError("Conflicting leap policy values")
        data["skip_feb_29"] = skip
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def leap_policy(self) -> Literal["preserve", "skip_feb_29"]:
        return "skip_feb_29" if self.skip_feb_29 else "preserve"

    @model_validator(mode="after")
    def valid(self):
        if isinstance(self.locations, list) and (
            not self.locations or len(self.locations) > self.sampling.max_locations
        ):
            raise ValueError("Invalid location count")
        if self.product in ("tmy", "tmyx", "published") and (self.years or self.start or self.end):
            raise ValueError("Published products cannot be requested as actual years/dates")
        if self.years and (self.start or self.end):
            raise ValueError("Specify years or dates, not both")
        if bool(self.start) != bool(self.end) or (
            self.start and self.end and self.start > self.end
        ):
            raise ValueError("Both dates are required in chronological order")
        if any(y < 1900 or y > 2200 for y in self.years) or len(set(self.years)) != len(self.years):
            raise ValueError("Invalid or duplicate year")
        if self.product in ("historical", "amy") and not (self.years or self.start):
            raise ValueError("Historical requests require years or inclusive dates")
        if self.skip_feb_29:
            if self.product not in ("historical", "amy") or not self.years:
                raise ValueError("skip_feb_29 requires an actual-year historical or AMY request")
        selections = [(s.provider, s.dataset, s.product_id) for s in self.dataset_selections]
        if len(selections) != len(set(selections)):
            raise ValueError("Duplicate dataset selection")
        if self.dataset_selections and self.hybrid_policy.enabled:
            raise ValueError("Dataset selections cannot be combined with hybrid assignment")
        return self


class FutureRequest(Model):
    schema_version: Literal["0.1"] = "0.1"
    baseline: str
    method: Literal["morph", "climate_profile"] = "morph"
    target_year: int | None = Field(default=None, ge=2020, le=2200)
    climate_period: tuple[int, int] | None = None
    reference_period: tuple[int, int] | None = None
    climate_scenario: Literal["ssp126", "ssp245", "ssp370", "ssp585", "rcp45", "rcp85"]
    profile: Literal["typical", "extreme", "ensemble", "sampled"] = "typical"
    models: list[str] = Field(default_factory=list)
    members: list[str] = Field(default_factory=list)
    extreme: dict[str, str | float] = Field(default_factory=dict)
    signals: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.climate_period is None:
            if self.target_year is None:
                raise ValueError("Provide target year or climate period")
            period: tuple[int, int] | None = (self.target_year - 14, self.target_year + 15)
            if self.method == "climate_profile":
                period = next(
                    (p for p in ((2045, 2054), (2085, 2094)) if p[0] <= self.target_year <= p[1]),
                    None,
                )
                if period is None:
                    raise ValueError("Hourly archive target must lie in a published window")
            object.__setattr__(self, "climate_period", period)
        for period in (self.climate_period, self.reference_period):
            if period and (period[0] > period[1] or period[0] < 1850 or period[1] > 2300):
                raise ValueError("Invalid climate period")
        assert self.climate_period is not None
        if (
            self.target_year
            and not self.climate_period[0] <= self.target_year <= self.climate_period[1]
        ):
            raise ValueError("Target year lies outside climate period")
        return self


class SourceRef(Model):
    provider: str
    dataset: str
    access_path: str = "https"
    version: str | None = None
    identity: str | None = None
    location: Location | None = None
    provisional: bool = True
    resolution_km: float | None = None
    license: str | None = None
    citation: str | None = None


class Candidate(Model):
    id: str
    source: SourceRef
    product_id: str | None = None
    weather_types: list[str] = Field(default_factory=list)
    variables: list[str] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    interval_minutes: int | None = None
    requires_credentials: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    selection_reasons: list[str] = Field(default_factory=list)
    location_id: str | None = None
    observed_at: str = Field(default_factory=utcnow)


class DiscoveryResult(Model):
    locations: list[Location]
    candidates: list[Candidate]
    selected_candidate_ids: list[str] = Field(default_factory=list)
    # Location key -> candidate ids, best first, by the same rule as selected_candidate_ids.
    ranked_candidate_ids: dict[str, list[str]] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)
    observed_at: str = Field(default_factory=utcnow)


class GeocodeResult(Model):
    query: str
    mode: str = "point"
    candidates: list[Location]
    attribution: str = "Open-Meteo / GeoNames"
    issues: list[Issue] = Field(default_factory=list)


class FetchTask(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    source: SourceRef
    parameters: dict[str, Any]
    cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    dependents: list[str] = Field(default_factory=list)


class TransformStep(Model):
    id: str
    method: str
    version: str = "0.1"
    inputs: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class OutputSpec(Model):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    index: int | None = Field(default=None, ge=0)
    requested_location_id: str
    task_ids: list[str]
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}\.epw$")
    dataset_selection: DatasetSelection | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class WeatherPlan(Model):
    schema_version: Literal["0.1"] = "0.1"
    kind: Literal["weather", "future"] = "weather"
    request: WeatherRequest | FutureRequest
    selected_candidates: list[Candidate] = Field(default_factory=list)
    tasks: list[FetchTask] = Field(default_factory=list)
    transforms: list[TransformStep] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list, exclude_if=lambda value: not value)
    estimated_calls: int = 0
    estimated_bytes: int | None = None
    capability_version: Literal["0.1"] = "0.1"
    plan_hash: str = ""

    @model_validator(mode="after")
    def valid(self):
        raw = self.model_dump(mode="json", exclude={"plan_hash"})
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)) or any(
            not o.task_ids or not set(o.task_ids) <= set(ids) for o in self.outputs
        ):
            raise ValueError("Plan contains duplicate tasks or unresolved output references")
        if (self.kind == "future") != isinstance(self.request, FutureRequest):
            raise ValueError("Plan kind and request schema disagree")
        if len(self.outputs) > 1000 or len(self.tasks) > 2000:
            raise ValueError("Plan exceeds execution item limits")
        output_ids = [o.id for o in self.outputs if o.id is not None]
        if output_ids and (
            len(output_ids) != len(self.outputs)
            or len(output_ids) != len(set(output_ids))
            or len({o.name for o in self.outputs}) != len(self.outputs)
        ):
            raise ValueError("New plans require unique output IDs and filenames")
        for candidate in raw["selected_candidates"]:
            candidate.pop("observed_at", None)
        for output in raw["outputs"]:
            if output.get("id") is None:
                output.pop("id", None)
            if output.get("index") is None:
                output.pop("index", None)
        sampling = raw["request"].get("sampling")
        if isinstance(sampling, dict) and sampling.get("standard_offset") == "utc":
            sampling.pop("standard_offset")
        hashed = digest(raw)
        if self.plan_hash and self.plan_hash != hashed:
            raise ValueError("Plan contents do not match plan_hash; create a new plan")
        object.__setattr__(self, "plan_hash", hashed)
        return self


class VariableLineage(Model):
    variable: str
    source: SourceRef
    raw_sha256: str
    transforms: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    derived: bool = False
    filled: bool = False
    unchanged: bool = False


class ArtifactRef(Model):
    id: str
    path: str
    media_type: str
    bytes: int
    sha256: str
    role: str


class ArtifactBundle(Model):
    bundle_id: str
    weather: list[ArtifactRef] = Field(default_factory=list)
    request: ArtifactRef
    plan: ArtifactRef
    manifest: ArtifactRef
    qc: ArtifactRef
    additional: list[ArtifactRef] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)


class WeatherJob(Model):
    id: str
    plan_hash: str
    retry_of: str | None = None
    kind: Literal["weather", "future"] = "weather"
    state: Literal[
        "queued", "running", "completed", "partially_completed", "failed", "cancelled"
    ] = "queued"
    total: int
    completed: int = 0
    failed: int = 0
    submitted_at: str = Field(default_factory=utcnow)
    finished_at: str | None = None
    cancellation_requested: bool = False
    errors: list[Issue] = Field(default_factory=list)
    bundle: ArtifactBundle | None = None
    idempotency_key: str | None = None
