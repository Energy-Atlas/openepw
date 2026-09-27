"""Typed place-set queries and previews shared by the service, MCP and harness."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import Issue, Location, Model

# Owner decision 2026-09-27: previews share the existing request point cap.
MAX_PLACES = 1000
GEONAMES_ATTRIBUTION = ("Place sets from GeoNames (geonames.org), CC BY 4.0; populations are GeoNames "
                        "values, not census figures, and are provided as is.")


class PlaceSetQuery(Model):
    """A fully specified descriptive place set; nothing is enumerated before this exists."""

    kind: Literal["city", "capital"]
    country: str = Field(pattern=r"^[A-Z]{2}$")
    admin1: str | None = Field(default=None, pattern=r"^[A-Z0-9]{1,6}$")
    min_population: int | None = Field(default=None, ge=1000)
    limit: int = Field(ge=1, le=MAX_PLACES)

    @model_validator(mode="after")
    def city_needs_definition(self):
        if self.kind == "city" and self.min_population is None:
            raise ValueError("A city set needs a minimum population")
        return self


class RegionMatch(Model):
    country: str
    admin1: str | None = None
    label: str


class PlaceRow(Model):
    index: int
    input: str
    status: Literal["resolved", "unresolved"]
    name: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    source: Literal["coordinates", "geocoder", "geonames"] | None = None
    ambiguous: bool = False
    candidate_count: int = 0
    population: int | None = None
    region: str | None = None
    source_id: str | None = None


class PlaceSetResult(Model):
    rows: list[PlaceRow]
    total_matching: int
    truncated: bool
    source_file: str
    source_sha256: str
    retrieved_at: str
    attribution: str = GEONAMES_ATTRIBUTION


class PlacePreview(Model):
    """Numbered points ready to plan; ambiguity and unresolved rows stay visible."""

    rows: list[PlaceRow]
    locations: list[Location]
    geojson: dict[str, Any]
    digest: str
    issues: list[Issue] = Field(default_factory=list)
    attribution: list[str] = Field(default_factory=list)
