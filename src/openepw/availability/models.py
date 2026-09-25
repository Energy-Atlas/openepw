"""Evidence and assessment contracts for local weather availability."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from openepw.models import Issue, Location, Model, WeatherRequest


class EvidenceRef(Model):
    id: str
    source_url: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime
    checked_at: datetime | None = None
    basis: Literal["documentation", "inventory", "targeted_probe", "review"]
    last_modified: str | None = None
    etag: str | None = None
    published_at: date | None = None
    terms: str | None = None
    attribution: str | None = None
    scope: str | None = None


class ProductRecord(Model):
    id: str
    provider: str
    dataset: str
    version: str | None = None
    access_route: str = "https"
    native_product_id: str | None = None
    spatial_kind: Literal["point", "station", "grid", "area", "unknown"] = "unknown"
    temporal_kind: Literal["actual", "tmy_reference", "future_window"]
    footprint: tuple[float, float, float, float] | None = None
    longitude_convention: Literal["-180_180", "0_360"] | None = None
    source_variables: list[str] = Field(default_factory=list)
    adapter_variables: list[str] = Field(default_factory=list)
    native_resolution_minutes: int | None = Field(default=None, gt=0)
    delivered_resolution_minutes: int | None = Field(default=None, gt=0)
    access_requirements: list[str] = Field(default_factory=list)
    citation: str | None = None
    license_effective: str | None = None
    license_original: str | None = None
    license_history: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class SiteRecord(Model):
    id: str
    product_id: str
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    elevation_m: float | None = None
    position_status: Literal[
        "published", "inferred", "consensus", "approximate_locality", "unknown", "conflicted"
    ] = "unknown"
    station_identity_status: Literal["verified", "candidate", "ambiguous", "unknown"] = "unknown"
    candidate_station_ids: list[str] = Field(default_factory=list)
    operating_start: date | None = None
    operating_end: date | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ActualScope(Model):
    kind: Literal["actual"] = "actual"
    years: list[int] = Field(default_factory=list)
    month_counts: dict[int, dict[int, int]] = Field(default_factory=dict)
    operating_start: date | None = None
    operating_end: date | None = None


class TMYReferenceScope(Model):
    kind: Literal["tmy_reference"] = "tmy_reference"
    start_year: int | None = None
    end_year: int | None = None
    product_label: str
    selected_month_years: dict[int, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def chronological(self):
        if (self.start_year is None) != (self.end_year is None):
            raise ValueError("TMY reference period must have both endpoints")
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("TMY reference period is reversed")
        return self


class FutureWindowScope(Model):
    kind: Literal["future_window"] = "future_window"
    start_year: int | None = None
    end_year: int | None = None
    scenario: str
    model: str | None = None
    member: str | None = None
    grid: str | None = None
    listed_years: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def chronological(self):
        if (self.start_year is None) != (self.end_year is None):
            raise ValueError("Future window must have both endpoints")
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("Future window is reversed")
        return self


TemporalScope = Annotated[
    ActualScope | TMYReferenceScope | FutureWindowScope, Field(discriminator="kind")
]


class AvailabilityEntry(Model):
    id: str
    product_id: str
    site_id: str | None = None
    scope: TemporalScope
    variables: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_basis: Literal["documentation", "inventory", "targeted_probe"]
    exclusions: list[str] = Field(default_factory=list)
    weather_complete: bool | None = None
    probe_location: Location | None = None
    source_etag: str | None = None


class ReviewAnnotation(Model):
    product_id: str
    catalog_url: str
    status: Literal[
        "reviewed_metadata_match", "approximate_locality", "name_code_conflict", "stale_evidence"
    ]
    rationale: str
    accepted_on: date
    evidence_ids: list[str]
    source_checksums: dict[str, str]
    alternate_url: str | None = None
    coordinate_authority: str | None = None
    original_position_status: str | None = None
    original_match_reason: str | None = None
    epw_coordinates_verified: bool = False
    weather_equivalence_verified: bool = False


class CatalogBundle(Model):
    schema_version: Literal["1"] = "1"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    products: list[ProductRecord] = Field(default_factory=list)
    sites: list[SiteRecord] = Field(default_factory=list)
    entries: list[AvailabilityEntry] = Field(default_factory=list)
    reviews: list[ReviewAnnotation] = Field(default_factory=list)


class CatalogSnapshotRef(Model):
    generation_id: str
    schema_version: str = "1"
    importer_version: str = "1"
    source_checksums: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    activated_at: datetime | None = None
    stale_sources: list[str] = Field(default_factory=list)


class EligibilityDecision(Model):
    status: Literal["supported", "excluded", "unknown"]
    reasons: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_bases: list[str] = Field(default_factory=list)
    stale: bool = False
    access: Literal["ready", "credentials_required", "terms_required", "unknown"] = "unknown"
    health: Literal["healthy", "degraded", "unknown"] = "unknown"


class SuitabilityOption(Model):
    id: str
    occurrence_index: int = Field(ge=0)
    product: ProductRecord
    site: SiteRecord | None = None
    eligibility: EligibilityDecision
    missing_required_variables: list[str] = Field(default_factory=list)
    missing_preferred_variables: list[str] = Field(default_factory=list)
    distance_km: float | None = None
    elevation_delta_m: float | None = None
    identity_status: Literal["verified", "provisional", "unknown"] = "unknown"
    reasons: list[str] = Field(default_factory=list)
    rank: int | None = None


class LocationAssessment(Model):
    occurrence_index: int = Field(ge=0)
    requested_location: Location
    ranked_option_ids: list[str] = Field(default_factory=list)
    recommended_option_ids: list[str] = Field(default_factory=list)
    unresolved_mapping: list[str] = Field(default_factory=list)


class WeatherAvailabilityQuery(Model):
    kind: Literal["weather"] = "weather"
    request: WeatherRequest
    purpose: Literal["building_energy", "solar", "thermal_extremes"] | None = None
    required_variables: list[str] | None = None
    max_distance_km: float | None = Field(default=None, ge=0)
    max_elevation_delta_m: float | None = Field(default=None, ge=0)
    refresh: Literal["never", "if_needed"] = "never"


class FutureAvailabilityQuery(Model):
    kind: Literal["future"] = "future"
    location: Location
    method: Literal["morph", "climate_profile"]
    profile: Literal["typical", "extreme", "ensemble", "sampled"] = "typical"
    scenario: str
    climate_period: tuple[int, int]
    reference_period: tuple[int, int] | None = None
    model: str | None = None
    member: str | None = None
    purpose: Literal["building_energy", "solar", "thermal_extremes"] | None = None
    required_variables: list[str] | None = None
    max_distance_km: float | None = Field(default=None, ge=0)
    max_elevation_delta_m: float | None = Field(default=None, ge=0)
    refresh: Literal["never", "if_needed"] = "never"


AvailabilityQuery = Annotated[
    WeatherAvailabilityQuery | FutureAvailabilityQuery, Field(discriminator="kind")
]


class AvailabilityResult(Model):
    locations: list[LocationAssessment] = Field(default_factory=list)
    options: list[SuitabilityOption] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    snapshots: list[CatalogSnapshotRef] = Field(default_factory=list)
    checked_at: datetime
