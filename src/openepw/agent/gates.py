"""Host guard-rails: the next required step, and plan requests built only from approved facts."""

from __future__ import annotations

from typing import Any

from ..models import DatasetSelection
from .state import Facts

# Copernicus CDS requests wait in Copernicus's queue, so they run as their own job.
QUEUED_PROVIDERS = frozenset({"cds"})


class GateRequired(Exception):
    """A step the person must complete first; ``need`` names it (see next_need)."""

    def __init__(self, need: str, message: str):
        super().__init__(message)
        self.need = need


def needs_years(facts: Facts) -> bool:
    return any(offer["request"]["product"] == "historical" for offer in facts.chosen)


def _reviewed(facts: Facts) -> bool:
    return facts.review is not None and facts.approved_key == facts.review["key"]


def next_need(facts: Facts) -> str:
    if facts.stage == "results":
        return "next_steps"
    if facts.place_set:
        return "place_set"
    if facts.candidates:
        return "choose_location"
    if facts.geography is None:
        return "where"
    if not _reviewed(facts):
        return "review_location"
    if not facts.chosen:
        return "choose_products"
    if needs_years(facts) and not facts.years:
        return "years"
    if not facts.plans:
        return "plan"
    if not facts.job_ids:
        return "review_plan"
    return "jobs"


def _selection(value: dict[str, Any]) -> dict[str, Any]:
    return DatasetSelection.model_validate(value).model_dump(mode="json")


def build_requests(facts: Facts) -> list[dict[str, Any]]:
    """One request per kind from the approved review, chosen offers and stated years."""
    if not _reviewed(facts):
        raise GateRequired("review_location", "The person has not approved these locations")
    if not facts.chosen:
        raise GateRequired("choose_products", "The person has not chosen a weather product")
    if needs_years(facts) and not facts.years:
        raise GateRequired("years", "Actual-year weather needs the person's years")
    assert facts.review is not None
    base = {"locations": facts.review["geography"], "sampling": facts.review.get("sampling") or {}}

    def selections(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [_selection(item) for offer in offers for item in offer["request"]["dataset_selections"]]

    actual = [offer for offer in facts.chosen if offer["request"]["product"] == "historical"]
    typical = [offer for offer in facts.chosen if offer["request"]["product"] != "historical"]
    queued = [offer for offer in actual if any(item["provider"] in QUEUED_PROVIDERS
                                               for item in offer["request"]["dataset_selections"])]
    direct = [offer for offer in actual if offer not in queued]
    requests = [{**base, "product": "historical", "years": list(facts.years),
                 "dataset_selections": selections(group)} for group in (direct, queued) if group]
    if typical:
        kinds = {offer["request"]["product"] for offer in typical}
        requests.append({**base, "product": kinds.pop() if len(kinds) == 1 else "tmy", "years": [],
                         "dataset_selections": selections(typical)})
    return requests


def check_plan_request(facts: Facts, request: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a proposed plan request to the approved facts, or say which step is missing.

    Locations and sampling always come from the approved review; datasets must be among the
    chosen offers; years must be among the person's stated years.
    """
    approved = build_requests(facts)
    product = request.get("product", "historical")
    proposed = [_selection(item) for item in request.get("dataset_selections") or []]
    match = next((item for item in approved if item["product"] == product
                  and all(selection in item["dataset_selections"] for selection in proposed)), None)
    if match is None:
        raise GateRequired("choose_products", "The plan's product or datasets differ from the person's choice")
    years = list(request.get("years") or [])
    if not set(years) <= set(facts.years):
        raise GateRequired("years", "The plan's years differ from the years the person stated")
    return {**match, "dataset_selections": proposed or match["dataset_selections"]}
