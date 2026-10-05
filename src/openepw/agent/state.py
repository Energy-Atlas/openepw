"""What the conversation has established so far, and the session that holds it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..models import Model
from .interactions import Interaction


class Facts(Model):
    """Pending and approved choices. Only approved facts reach a plan (see gates.build_requests)."""

    stage: Literal["request", "results"] = "request"
    place_set: dict[str, Any] | None = None          # {"draft": ..., "questions": [...]}
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    place_rows: list[dict[str, Any]] = Field(default_factory=list)
    geography: Any = None                            # proposed point, point list or area
    review: dict[str, Any] | None = None             # weather_locations_review result for geography
    approved_key: str | None = None                  # review key the person approved
    product_type: str | None = None                  # historical | tmy | tmyx | published (from text)
    provider: str | None = None
    offers: list[dict[str, Any]] = Field(default_factory=list)
    offer_availability: dict[str, Any] | None = None
    chosen: list[dict[str, Any]] = Field(default_factory=list)   # chosen offers, each with "request"
    years: list[int] = Field(default_factory=list)   # only from the person's text or a form
    plans: list[dict[str, Any]] = Field(default_factory=list)
    job_ids: list[str] = Field(default_factory=list)
    finished_job_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)

    def set_geography(self, value: Any) -> None:
        """A new geography needs a new review, approval, product choice and plan."""
        self.geography = value
        self.review = None
        self.approved_key = None
        self.offers = []
        self.offer_availability = None
        self.chosen = []
        self.plans = []

    def reset_place(self) -> None:
        self.place_set = None
        self.candidates = []
        self.place_rows = []

    def new_request(self) -> None:
        """Start over; finished jobs and EPW artifacts stay available."""
        self.stage = "request"
        self.reset_place()
        self.set_geography(None)
        self.product_type = None
        self.provider = None
        self.years = []
        self.job_ids = []


class SessionState(Model):
    id: str
    revision: int = 0
    mode: Literal["guided", "agent"] = "guided"
    facts: Facts = Field(default_factory=Facts)
    form: Interaction | None = None
