"""What the conversation has established so far, and the session that holds it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..models import Model
from .interactions import Interaction

SEEN_LIMIT = 2000
SEEN_TOLERANCE = 0.05          # degrees: a geocoder's point rounded to two decimals still matches


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
    started_plans: list[str] = Field(default_factory=list)   # every plan hash submitted; only grows

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
    # Agent mode: the current model turn's items, the ask-tool call waiting for the person, and
    # the event number where the turn began (earlier events form the history the model sees).
    turn: list[dict[str, Any]] = Field(default_factory=list)
    pending_call: dict[str, str] | None = None
    turn_seq: int = 0
    # Guardrails: strikes so far, why the session ended (None while open), whether a strike was
    # recorded in the current input, whether that input was the person's own text, and one-time
    # notices already shown. Back never restores these.
    strikes: int = 0
    ended: str | None = None
    ended_reopen: Literal["allow", "deny"] | None = None   # the ending profile's reopen rule
    downgraded: bool = False                                # guided for good after the strike limit
    struck_this_turn: bool = False
    turn_origin: Literal["", "text", "answer", "system"] = ""
    shown_notices: list[str] = Field(default_factory=list)
    # Points the session has seen (place-tool results, reviews, typed coordinates); a lookup may
    # use only points near these. Back restores the earlier list.
    seen_points: list[tuple[float, float]] = Field(default_factory=list)

    def see(self, points: list[tuple[float, float]]) -> None:
        """Remember points, once each (to four decimals), keeping the newest SEEN_LIMIT."""
        known = {(round(lat, 4), round(lon, 4)) for lat, lon in self.seen_points}
        for lat, lon in points:
            key = (round(lat, 4), round(lon, 4))
            if key not in known:
                known.add(key)
                self.seen_points.append(key)
        del self.seen_points[:-SEEN_LIMIT]

    def has_seen(self, lat: float, lon: float, tolerance: float = SEEN_TOLERANCE) -> bool:
        return any(abs(lat - seen_lat) <= tolerance and abs(lon - seen_lon) <= tolerance
                   for seen_lat, seen_lon in self.seen_points)



def points_in(value: Any, *, limit: int = SEEN_LIMIT) -> list[tuple[float, float]]:
    """Points ({lat, lon} or {latitude, longitude}) anywhere in a tool result, bounded."""
    found: list[tuple[float, float]] = []
    stack: list[tuple[Any, int]] = [(value, 0)]
    visited = 0
    while stack and len(found) < limit and visited < 20 * limit:
        item, depth = stack.pop()
        visited += 1
        if isinstance(item, dict):
            for lat_key, lon_key in (("lat", "lon"), ("latitude", "longitude")):
                lat, lon = item.get(lat_key), item.get(lon_key)
                if (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                        and not isinstance(lat, bool) and not isinstance(lon, bool)
                        and -90 <= lat <= 90 and -180 <= lon <= 180):
                    found.append((float(lat), float(lon)))
            children = list(item.values())
        elif isinstance(item, list):
            children = item
        else:
            continue
        if depth < 8:
            stack.extend((child, depth + 1) for child in reversed(children)
                         if isinstance(child, (dict, list)))
    return found
