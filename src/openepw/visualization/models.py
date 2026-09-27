"""Versioned declarative request accepted by the shared visualization service."""

from typing import Any, Literal

from pydantic import Field, model_validator

from ..models import Model
from .catalog import FAMILIES


class VisualizationRequest(Model):
    schema_version: Literal["1"] = "1"
    artifact_ids: list[str] = Field(min_length=1, max_length=100)
    family: str
    variable: str = Field(min_length=1)
    aggregation: Literal["mean", "sum", "min", "max"] | None = None
    allow_partial: bool = False
    options: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid(self):
        if self.family not in FAMILIES:
            raise ValueError("Unknown visualization family")
        if len(set(self.artifact_ids)) != len(self.artifact_ids) or any(
            len(item) != 32 or any(ch not in "0123456789abcdef" for ch in item)
            for item in self.artifact_ids
        ):
            raise ValueError("Artifact IDs must be unique lowercase hex identifiers")
        if set(self.options) - ({"bins"} if self.family == "histogram" else set()):
            raise ValueError("Unsupported visualization option")
        bins = self.options.get("bins")
        if bins is not None and not 2 <= bins <= 50:
            raise ValueError("Histogram bins must be between 2 and 50")
        return self


class VisualizationDataRef(Model):
    view_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    shape: Literal["rows", "points", "matrix"]
    total_rows: int = Field(ge=0)
    page_tool: Literal["weather_data_page"] = "weather_data_page"


class VisualizationQuality(Model):
    expected_hours: int = Field(ge=0)
    valid_hours: int = Field(ge=0)
    missing_hours: int = Field(ge=0)

    @model_validator(mode="after")
    def valid(self):
        if self.valid_hours + self.missing_hours != self.expected_hours:
            raise ValueError("Coverage counts must sum to expected hours")
        return self


class VisualizationSpec(Model):
    schema_version: Literal["1"] = "1"
    family: str
    data_ref: VisualizationDataRef
    encodings: dict[str, Any]
    transforms: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    quality: VisualizationQuality
    summary: str

    @model_validator(mode="after")
    def valid(self):
        if self.family not in FAMILIES:
            raise ValueError("Unknown visualization family")
        return self
