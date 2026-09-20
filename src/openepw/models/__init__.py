"""Versioned wire contracts. Runtime credentials never belong in these objects."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class SamplingSpec(Model):
    dx_km: float = Field(default=25, gt=0)
    dy_km: float = Field(default=25, gt=0)
    offset_x_km: float = 0
    offset_y_km: float = 0
    max_locations: int = Field(default=1000, ge=1, le=10000)


class HybridPolicy(Model):
    enabled: bool = False
    assignments: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if self.assignments and not self.enabled:
            raise ValueError("Variable assignments require explicit hybrid enabled")
        return self


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
    leap_policy: Literal["preserve"] = "preserve"
    formats: list[Literal["epw"]] = Field(default_factory=lambda: ["epw"])

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
            object.__setattr__(
                self, "climate_period", (self.target_year - 14, self.target_year + 15)
            )
        for period in (self.climate_period, self.reference_period):
            if period and (period[0] > period[1] or period[0] < 1850 or period[1] > 2300):
                raise ValueError("Invalid climate period")
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
    issues: list[Issue] = Field(default_factory=list)
    observed_at: str = Field(default_factory=utcnow)


class GeocodeResult(Model):
    query: str
    mode: str = "point"
    candidates: list[Location]
    attribution: str = "Open-Meteo / GeoNames"
    issues: list[Issue] = Field(default_factory=list)


class FetchTask(Model):
    id: str
    source: SourceRef
    parameters: dict[str, Any]
    cache_key: str
    dependents: list[str] = Field(default_factory=list)


class TransformStep(Model):
    id: str
    method: str
    version: str = "0.1"
    inputs: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class OutputSpec(Model):
    requested_location_id: str
    task_ids: list[str]
    name: str


class WeatherPlan(Model):
    schema_version: Literal["0.1"] = "0.1"
    kind: Literal["weather", "future"] = "weather"
    request: WeatherRequest | FutureRequest
    selected_candidates: list[Candidate] = Field(default_factory=list)
    tasks: list[FetchTask] = Field(default_factory=list)
    transforms: list[TransformStep] = Field(default_factory=list)
    outputs: list[OutputSpec] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    estimated_calls: int = 0
    estimated_bytes: int | None = None
    capability_version: Literal["0.1"] = "0.1"
    plan_hash: str = ""

    @model_validator(mode="after")
    def valid(self):
        raw = self.model_dump(mode="json", exclude={"plan_hash"})
        for candidate in raw["selected_candidates"]:
            candidate.pop("observed_at", None)
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
