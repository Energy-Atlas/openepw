"""What the conversation has established so far, and the session that holds it."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..models import Model
from .interactions import Interaction

SEEN_LIMIT = 2000
SEEN_TOLERANCE = 0.05          # degrees: a geocoder's point rounded to two decimals still matches
# The parts of a request the person sets (design 2026-10-30 §3); the plan is derived from them.
Part = Literal["place", "preference", "products", "years"]
PARTS: tuple[Part, ...] = ("place", "preference", "products", "years")
# Who last set a part: the person's own message, a form answer, the host from the person's input,
# or the model (a filter it passed without the person's words).
By = Literal["text", "form", "host", "model"]


def matches_preference(offer: dict[str, Any], product: str | None, provider: str | None) -> bool:
    """True when a chosen offer fits a product preference (the same rules as the offers filter)."""
    kind = offer["request"]["product"]
    if product in ("historical", "amy") and kind != "historical":
        return False
    if product in ("tmy", "published") and kind == "historical":
        return False
    if product == "tmyx" and kind != "tmyx":
        return False
    return not provider or any(item.get("provider") == str(provider).lower()
                               for item in offer["request"]["dataset_selections"])


class Facts(Model):
    """Pending and approved choices. Only approved facts reach a plan (see gates.build_requests).

    Sessions saved before the request parts existed load with the defaults of the last three
    fields, which keep their meaning: every year and every chosen product confirmed.
    """

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
    proposed_years: list[int] = Field(default_factory=list)  # years written in a question; part of years
    origins: dict[str, dict[str, Any]] = Field(default_factory=dict)   # part -> {"by", "seq"}
    recheck: bool = False                            # the chosen products must be chosen again

    @property
    def confirmed_years(self) -> list[int]:
        """The years a plan may use: written plainly, or confirmed on a form."""
        return [year for year in self.years if year not in self.proposed_years]

    def set_geography(self, value: Any) -> None:
        """A new geography needs a new review, approval and plan. Chosen products are kept to
        recheck: the product form shows them again, preselected where still offered."""
        self.geography = value
        self.review = None
        self.approved_key = None
        self.offers = []
        self.offer_availability = None
        self.recheck = bool(self.chosen)
        self.plans = []

    def change(self, part: Part, value: Any, *, by: By, seq: int = 0, proposed: Any = ()) -> None:
        """Set one part and reset only what depends on it (design §4). The plan always resets.

        ``value`` is the geography (place), a (product, provider) pair (preference), the chosen
        offers (products) or the years (years, with ``proposed`` naming those asked about).
        """
        self.plans = []
        if part == "place":
            self.set_geography(value)
        elif part == "preference":
            self.product_type, self.provider = value
            self.offers, self.offer_availability = [], None
            if not all(matches_preference(offer, *value) for offer in self.chosen):
                self.recheck = True
        elif part == "products":
            self.chosen, self.recheck = list(value), False
        else:
            years = sorted(set(value))
            if years != self.years:
                self.offers, self.offer_availability = [], None   # their availability is per year
            self.years = years
            self.proposed_years = sorted(set(proposed) & set(years))
        self.origins[part] = {"by": by, "seq": seq}

    def confirm_years(self, years: Any, *, by: By = "form", seq: int = 0) -> bool:
        """Confirm proposed years shown on a form; True when any was proposed."""
        confirmed = set(years) & set(self.proposed_years)
        if not confirmed:
            return False
        self.proposed_years = [year for year in self.proposed_years if year not in confirmed]
        self.plans = []
        self.origins["years"] = {"by": by, "seq": seq}
        return True

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
        self.chosen, self.recheck = [], False
        self.years, self.proposed_years = [], []
        self.origins = {}
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
