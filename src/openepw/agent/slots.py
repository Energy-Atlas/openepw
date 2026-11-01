"""The parts of a request, their status and origin, and the request summary form.

Statuses are derived from the facts, so there is one source of truth (design 2026-10-30 §3):
``empty``, ``proposed`` (given but not confirmed), ``confirmed`` and ``recheck`` (confirmed, but a
change to another part means it must be shown again). Plans use confirmed parts only.
"""

from __future__ import annotations

from typing import Any

from .guard import clean_external
from .interactions import Interaction, Option
from .state import PARTS, Facts, Part

LABELS: dict[str, str] = {"place": "Place", "preference": "Product preference", "products": "Products",
                          "years": "Years"}
KINDS = {"historical": "actual year (AMY)", "tmy": "typical year", "tmyx": "typical year (TMYx)",
         "published": "published typical-year EPW"}
ORIGIN_WORDS = {"text": "from your message", "form": "on a form", "host": "found from your message",
                "model": "suggested by the assistant"}


def _reviewed(facts: Facts) -> bool:
    return facts.review is not None and facts.approved_key == facts.review.get("key")


def status(facts: Facts, part: Part) -> str:
    if part == "place":
        if _reviewed(facts):
            return "confirmed"
        pending = facts.geography is not None or facts.candidates or facts.place_set or facts.place_rows
        return "proposed" if pending else "empty"
    if part == "preference":
        if facts.product_type is None and facts.provider is None:
            return "empty"
        by = (facts.origins.get("preference") or {}).get("by", "text")
        return "proposed" if by == "model" else "confirmed"
    if part == "products":
        if facts.recheck:
            return "recheck"
        return "confirmed" if facts.chosen else "empty"
    if not facts.years:
        return "empty"
    return "proposed" if facts.proposed_years else "confirmed"


def _names(points: list[dict[str, Any]], max_chars: int) -> str:
    named = [clean_external(str(item.get("name") or f"{item['lat']:.3f}, {item['lon']:.3f}"), max_chars)
             for item in points[:3]]
    return ", ".join(named) + (f" and {len(points) - 3} more" if len(points) > 3 else "")


def _value(facts: Facts, part: Part, max_chars: int) -> str:
    if part == "place":
        if facts.review:
            return _names(list(facts.review.get("points") or []), max_chars)
        if facts.place_set or facts.candidates:
            return "being chosen"
        geography = facts.geography
        points = geography if isinstance(geography, list) else [geography] if isinstance(geography, dict) else []
        if points and all(isinstance(item, dict) and "lat" in item for item in points):
            return _names(points, max_chars)
        return "an area" if geography is not None else "none"
    if part == "preference":
        words = [KINDS.get(facts.product_type or "", facts.product_type or "any product")]
        if facts.provider:
            words.append(f"from {clean_external(facts.provider, 40)}")
        return " ".join(words) if facts.product_type or facts.provider else "any product"
    if part == "products":
        return "; ".join(clean_external(str(offer.get("label") or offer["id"]), max_chars)
                         for offer in facts.chosen) or "none"
    if not facts.years:
        return "none"
    return ", ".join(f"{year} (asked about, not confirmed)" if year in facts.proposed_years else str(year)
                     for year in facts.years)


def parts(facts: Facts, *, max_chars: int = 120) -> list[dict[str, Any]]:
    """One entry per part: ``{part, label, value, status, origin}`` (origin in words, or "")."""
    found = []
    for part in PARTS:
        by = (facts.origins.get(part) or {}).get("by")
        found.append({"part": part, "label": LABELS[part], "value": _value(facts, part, max_chars),
                      "status": status(facts, part), "origin": ORIGIN_WORDS.get(by or "", "")})
    return found


def plan_status(facts: Facts) -> str:
    if not facts.plans:
        return "none"
    if all(plan.get("job_id") for plan in facts.plans if plan.get("output_count")):
        return f"{len(facts.plans)} plan(s) started"
    return f"{len(facts.plans)} plan(s) waiting for Run"


def lines(facts: Facts, *, max_chars: int = 120) -> list[str]:
    """The parts as text lines, for forms and renderers without ``data.parts``."""
    shown = []
    for entry in parts(facts, max_chars=max_chars):
        origin = f", {entry['origin']}" if entry["origin"] and entry["status"] != "empty" else ""
        shown.append(f"{entry['label']}: {entry['value']} ({entry['status']}{origin})")
    return shown


def change_options(facts: Facts) -> list[Option]:
    """A Change action per part; products only once the place is approved."""
    return [Option(id=f"change:{part}", label=f"Change {LABELS[part].lower()}")
            for part in PARTS if part != "products" or _reviewed(facts)]


def request_form(facts: Facts, *, max_chars: int = 120) -> Interaction:
    """The request summary: each part with its status; approve confirms what is proposed."""
    proposed = [entry["label"].lower() for entry in parts(facts, max_chars=max_chars)
                if entry["status"] == "proposed" and entry["part"] != "place"]
    note = (f"Approve to confirm the {' and '.join(proposed)}, or change a part." if proposed
            else "Approve to keep it as it is, or change a part.")
    if status(facts, "place") == "proposed":
        note += " The place is confirmed on the location review."
    return Interaction(kind="request_summary", gate="review_request", prompt="Is this your request?",
                       summary="\n".join([*lines(facts, max_chars=max_chars), f"Plan: {plan_status(facts)}", note]),
                       options=change_options(facts),
                       data={"parts": parts(facts, max_chars=max_chars), "plan": plan_status(facts)})
