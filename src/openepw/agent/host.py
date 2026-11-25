"""Host steps both policies share: the forms they open and the one guarded way to run plans."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from ..models import VariableFill
from .gates import build_requests, open_gaps
from .guard import clean_external
from .interactions import Answer, Interaction, Option
from .mcp_port import ToolFailure
from .outputs import offer_export
from .session import AgentSession
from .slots import change_options, lines, parts, status
from .state import PARTS, Facts, matches_preference

VIEWS = (("view:monthly_series", "Monthly dry-bulb temperature chart"),
         ("view:histogram", "Dry-bulb temperature distribution"))
# Follow-ups after results; the host answers them without a plan or a new job (phase 5).
AFTER = (("outputs", "List my files"), ("download", "Download files"))
Advance = Callable[[AgentSession], Awaitable[None]]
PRODUCT_KINDS = {"historical": "actual year (AMY)", "tmy": "typical year (TMY)",
                 "tmyx": "typical year (TMYx)", "published": "published typical-year EPW"}
LOOKUP_NOTE = ("Listed means eligible to try retrieval, not quality assured. Products not shown are not "
               "offered for these places and years. Nothing is chosen: to get files, review the location "
               "and choose products on the form.")


def offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def point(candidate: dict[str, Any]) -> dict[str, Any]:
    """A geocoder candidate as a request point; its default offset (0) must not be kept."""
    return {key: candidate[key] for key in ("lat", "lon", "name", "id", "elevation")
            if candidate.get(key) is not None}


def plan_entry(request: dict[str, Any], data: dict[str, Any], summary: str) -> dict[str, Any]:
    """What a plan review shows and run submits for one weather_plan result."""
    return {"plan_hash": data["plan_hash"], "product": request["product"],
            "dataset_selections": request.get("dataset_selections", []),
            "years": list(request.get("years") or []),
            "output_count": data.get("output_count", 0), "summary": summary,
            "warnings": data.get("warnings", []), "gap_rows": data.get("gap_rows", [])}


def place_set_form(place_set: dict[str, Any]) -> Interaction:
    question = place_set["questions"][0]
    numbered = bool((place_set.get("draft") or {}).get("region_options"))
    options, answers = [], {}
    for index, option in enumerate(question.get("options", []), start=1):
        if question["field"] == "region":
            label = option["label"]
            answer = str(index) if numbered else label
        elif question["field"] == "definition":
            label, answer = f"{option['min_population']:,}", str(option["min_population"])
        else:
            label = "All (1,000)" if option["limit"] >= 1000 else str(option["limit"])
            answer = "all" if option["limit"] >= 1000 else f"top {option['limit']}"
        options.append(Option(id=f"place:{index}", label=label))
        answers[f"place:{index}"] = answer
    return Interaction(kind="choice", gate="place_set", prompt=question["prompt"], options=options,
                       data={"answers": answers, "field": question["field"]})


def review_form(facts: Facts, max_chars: int = 120) -> Interaction:
    review = facts.review
    assert review is not None
    count = review["point_count"]
    lines = [f"{index}. {clean_external(str(item.get('name') or 'point'), max_chars)} "
             f"({item['lat']:.4f}, {item['lon']:.4f}) "
             f"{offset(item['standard_offset_minutes'])}"
             for index, item in enumerate(review["points"][:25], start=1)]
    if count > 25:
        lines.append(f"... and {count - 25} more")
    lines.append(review["standard_time"])
    return Interaction(
        kind="location_review", gate="review_location",
        prompt="Are these the right locations?" if count > 1 else "Is this the right location?",
        summary="\n".join(lines), data={**review, "several": count > 1, "rows": facts.place_rows})


def availability_line(facts: Facts) -> str:
    """One grounded sentence on what the offers list for the years asked (from the offers themselves)."""
    years = (facts.offer_availability or {}).get("years") or []
    listed = [offer["label"] for offer in facts.offers if offer.get("sites") and offer.get("available") == offer["sites"]]
    partly = [offer["label"] for offer in facts.offers if 0 < (offer.get("available") or 0) < (offer.get("sites") or 0)]
    unverified = [offer["label"] for offer in facts.offers if offer.get("sites") and not offer.get("available")]
    parts = []
    if listed:
        parts.append("Listed: " + "; ".join(listed))
    if partly:
        parts.append("Listed at some places: " + "; ".join(partly))
    if unverified:
        parts.append("Not verified: " + "; ".join(unverified))
    if not parts:
        return ""
    scope = f"For {', '.join(str(year) for year in years)}" if years else "For these places"
    return f"{scope}. {'. '.join(parts)}. Products not shown are not offered for these places and years."


def product_form(facts: Facts) -> Interaction:
    """The product choice. Chosen products still offered are preselected (``data.selected``);
    ``data.recheck`` says a change elsewhere means they must be chosen again."""
    summary = "Listed means eligible to try retrieval, not quality assured."
    line = availability_line(facts)
    if line:
        summary = f"{line} {summary}"
    if (facts.offer_availability or {}).get("catalog_loaded") is False:
        summary += (" The local availability catalog is not loaded (openepw catalog import), so most "
                    "products are not verified here; planning checks each one.")
    offered = {offer["id"] for offer in facts.offers}
    selected = [offer["id"] for offer in facts.chosen if offer["id"] in offered]
    if facts.recheck:
        summary = ("Your change affects the products: choose them again"
                   + (" (those still offered are selected)" if selected else "") + ". " + summary)
    return Interaction(
        kind="product_choice", gate="choose_products", multi=True, prompt="Which weather products?",
        summary=summary,
        options=[Option(id=offer["id"], label=offer["label"], detail=offer.get("detail"))
                 for offer in facts.offers],
        data={"availability": facts.offer_availability, "selected": selected, "recheck": facts.recheck})


async def fetch_offers(s: AgentSession, *, product: str | None, provider: str | None, by: str = "host") -> None:
    """The offers for the approved locations and every written year (asked-about years included,
    so the product form shows them and choosing on it confirms them)."""
    facts = s.facts
    assert facts.review is not None
    data = (await s.tool("weather_product_offers", by=by, locations=facts.review["geography"],
                         product=product, provider=provider, years=facts.years or None)).data
    facts.offers, facts.offer_availability = data.get("options", []), data.get("availability")


async def refresh_offers(s: AgentSession) -> None:
    """After new years or a new preference, fetch the offers again before planning (design §4).

    Chosen products still offered stay confirmed and take the new availability; a product no
    longer offered makes the products part ``recheck``, so the product form is shown again.
    """
    facts = s.facts
    if facts.offers or not facts.chosen or facts.recheck or status(facts, "place") != "confirmed":
        return
    filtered = all(matches_preference(offer, facts.product_type, facts.provider) for offer in facts.chosen)
    await fetch_offers(s, product=facts.product_type if filtered else None,
                       provider=facts.provider if filtered else None)
    offered = {offer["id"]: offer for offer in facts.offers}
    dropped = [offer for offer in facts.chosen if offer["id"] not in offered]
    facts.chosen = [offered[offer["id"]] for offer in facts.chosen if offer["id"] in offered]
    if dropped:
        facts.recheck = True
        s.emit("assistant", "Not offered for these years and places: "
               + "; ".join(clean_external(str(offer.get("label") or offer["id"]), 120) for offer in dropped)
               + ". Choose the products again.", code="PRODUCTS_RECHECK")


def choose(s: AgentSession, ids: list[str]) -> None:
    """The person chose products on the product form; it also confirms the years it showed."""
    facts = s.facts
    facts.change("products", [offer for offer in facts.offers if offer["id"] in ids], by="form", seq=s.seq)
    availability = facts.offer_availability or {}
    if not availability.get("years_assumed"):
        facts.confirm_years(availability.get("years") or [], seq=s.seq)


def confirm_request(s: AgentSession) -> bool:
    """Approve on the request summary: years asked about and a suggested preference become
    confirmed. True when anything was only proposed."""
    facts = s.facts
    changed = facts.confirm_years(facts.proposed_years, seq=s.seq)
    if (facts.origins.get("preference") or {}).get("by") == "model":
        facts.origins["preference"] = {"by": "form", "seq": s.seq}
        changed = True
    return changed


def _status(option: dict[str, Any]) -> str:
    sites, available = option.get("sites") or 0, option.get("available") or 0
    if sites and available >= sites:
        return "listed"
    if available:
        return f"listed at {available} of {sites} places"
    return "not verified; checked when planning"


def lookup_summary(data: dict[str, Any], *, approved: bool, points: list[dict[str, Any]],
                   max_points: int = 5, max_products: int = 30) -> dict[str, Any]:
    """What a lookup tells the model: statuses from weather_product_offers, without its
    ``request`` objects, so a lookup can never feed a plan."""
    availability = data.get("availability") or {}
    options = data.get("options") or []
    tags = ((availability.get("locations") or [{}])[0].get("products") or []) if len(points) == 1 else []
    stations = {tag["option"]: tag["station"] for tag in tags if tag.get("station")}
    products = []
    for option in options[:max_products]:
        entry = {"label": option["label"],
                 "kind": PRODUCT_KINDS.get(option["request"]["product"], option["request"]["product"]),
                 "status": _status(option)}
        if station := stations.get(option["id"]):
            distance = station.get("distance_km")
            entry["station"] = f"{station.get('name') or 'station'}" + (
                f" · {distance:g} km" if distance is not None else "")
        products.append(entry)
    place: dict[str, Any] = {"approved": approved, "count": len(points), "points": [
        {"name": item.get("name"), "lat": round(item["lat"], 3), "lon": round(item["lon"], 3)}
        for item in points[:max_points]]}
    if len(points) > max_points:
        place["more_points"] = len(points) - max_points
    note = LOOKUP_NOTE
    if availability.get("catalog_loaded") is False:
        note += (" The local availability catalog is not loaded, so most products are not verified "
                 "here; planning checks each one.")
    summary = {"place": place, "years": availability.get("years") or [],
               "years_assumed": bool(availability.get("years_assumed")),
               "catalog_loaded": availability.get("catalog_loaded") is not False,
               "products": products}
    if len(options) > max_products:
        summary["more_products"] = len(options) - max_products
    return {**summary, "note": note}


def lookup_label(points: list[dict[str, Any]], max_chars: int = 120) -> str:
    """The fixed line the host shows before an answer about places that are not approved."""
    named = [f"{clean_external(str(item.get('name') or 'point'), max_chars)} "
             f"({item['lat']:.3f}, {item['lon']:.3f})" for item in points[:3]]
    if len(points) > 3:
        named.append(f"and {len(points) - 3} more")
    several = len(points) > 1
    return (f"Availability checked for {', '.join(named)}; "
            + ("these locations are" if several else "this location is")
            + " not approved yet. You'll confirm "
            + ("them" if several else "it") + " before choosing products.")


def years_form(facts: Facts | None = None) -> Interaction:
    current = ", ".join(map(str, facts.years)) if facts and facts.years else ""
    return Interaction(kind="text", gate="years", prompt="Which actual year or years?",
                       summary="Actual-year products need calendar years.",
                       data={"hint": "e.g. 2018 or 2016-2018" + (f" (now {current})" if current else "")})


def place_form(facts: Facts | None = None, max_chars: int = 120) -> Interaction:
    summary = "Give a place name, a list of places, or coordinates such as 42.44, -76.50."
    if facts is not None and status(facts, "place") != "empty":
        summary = f"Now: {parts(facts, max_chars=max_chars)[0]['value']}. {summary}"
    return Interaction(kind="map_input", gate="where", prompt="Where do you need weather?", summary=summary,
                       data={"hint": "e.g. Ithaca, NY · Boston; Denver · 42.44, -76.50"})


GAPS_PROMPT = "Some weather you asked for is missing from the chosen source, or may be. How should it be covered?"
GAPS_NOTE = ("A fill takes whole variables from the other source for the same hours, unchanged (not "
             "adjusted toward the station). Solar radiation always comes from one source.")
SHORT_GAPS_NOTE = ("Station records usually miss some hours; interpolation fills only gaps of up to 3 hours, "
                   "never solar, and records every hour it fills.")


def gap_rows(facts: Facts) -> list[dict[str, Any]]:
    """Gap rows of the plans not yet started, once each (planning/gaps.py)."""
    rows: dict[str, dict[str, Any]] = {}
    for plan in facts.plans:
        if plan.get("job_id"):
            continue
        for row in plan.get("gap_rows") or []:
            rows.setdefault(row["id"], row)
    return list(rows.values())


def _chosen_label(row: dict[str, Any]) -> str:
    labels = {option["id"]: option["label"] for option in row.get("options") or []}
    if row.get("unresolved"):
        return f"not decided at {row['unresolved']} of {row['places']} place(s)"
    if row.get("chosen"):
        return labels.get(row["chosen"], row["chosen"])
    return "decided per place: " + ", ".join(f"{count} {status.replace('_', ' ')}"
                                             for status, count in sorted(row.get("statuses", {}).items()))


def gap_line(row: dict[str, Any], max_chars: int = 120) -> str:
    places = f"{row['places']} place{'s' if row['places'] != 1 else ''}"
    label = row["label"][:1].lower() + row["label"][1:]          # keeps GHI, DNI and DHI
    source = clean_external(str(row["source"]), max_chars)
    if row.get("group") == "short_gaps":
        return f"{source}: {label} ({places}): {_chosen_label(row)}"
    return f"{source} has no {label} ({places}): {_chosen_label(row)}"


def gaps_form(facts: Facts, *, change: bool = False, max_chars: int = 120) -> Interaction:
    """The data-gaps form: one row per chosen source and variable group, each with its options
    and the recommended one selected. ``change`` (from the plan review) shows every row and
    replaces earlier choices; otherwise only rows still undecided, added to earlier choices."""
    rows = [row for row in gap_rows(facts) if change or row.get("unresolved")]
    shown = []
    for index, row in enumerate(rows, start=1):
        options = row.get("options") or []
        selected = row.get("chosen") if change and row.get("chosen") else next(
            (option["id"] for option in options if option.get("recommended")), options[0]["id"] if options else None)
        shown.append({**row, "selected": selected, "number": index,
                      "source": clean_external(str(row["source"]), max_chars)})
    lines = [f"{row['number']}. {gap_line(row, max_chars)}" for row in shown]
    notes = [note for row in shown for note in row.get("notes") or []]
    explained = [GAPS_NOTE] if any(row.get("group") != "short_gaps" for row in shown) else []
    if any(row.get("group") == "short_gaps" for row in shown):
        explained.append(SHORT_GAPS_NOTE)
    summary = "\n".join([*lines, *(f"Note: {note}" for note in notes[:3]), *explained])
    return Interaction(kind="data_gaps", gate="fill_gaps", prompt=GAPS_PROMPT, summary=summary,
                       data={"rows": shown, "mode": "replace" if change else "add"})


def _rule_key(fill: dict[str, Any]) -> tuple[Any, ...]:
    return (fill.get("group"), fill.get("for_provider"), fill.get("for_dataset"))


def apply_gap_choices(s: AgentSession, form: Interaction, choices: dict[str, str]) -> bool:
    """Turn the person's choice per row (option id; the selected one where none is given) into
    fill rules in ``facts.fills``. False, with the reason shown, for an unknown row or option."""
    facts = s.facts
    rows = form.data.get("rows") or []
    known = {row["id"] for row in rows}
    if not set(choices) <= known:
        s.emit("error", "Choose an option for each listed gap.", code="UNKNOWN_CHOICE")
        return False
    rules = [dict(fill) for fill in facts.fills]
    said = []
    for row in rows:
        chosen = choices.get(row["id"]) or row.get("selected")
        option = next((item for item in row.get("options") or [] if item["id"] == chosen), None)
        if option is None:
            s.emit("error", "Choose one of the listed options for each gap.", code="UNKNOWN_CHOICE")
            return False
        fill = VariableFill.model_validate(option["fill"]).model_dump(mode="json", exclude_none=True)
        if form.data.get("mode") == "replace":
            rules = [rule for rule in rules if _rule_key(rule) != _rule_key(fill)]
        rules = [rule for rule in rules if rule != fill] + [fill]
        said.append(f"{row['label']} for {row['source']}: {option['label']}")
    facts.fills = rules
    s.emit("assistant", "Data gaps: " + "; ".join(said) + ".", code="GAPS_DECIDED")
    return True


async def make_plans(s: AgentSession) -> None:
    """Plan every request group from the approved facts (all or nothing)."""
    facts = s.facts
    plans = []
    for request in build_requests(facts):
        result = await s.tool("weather_plan", request=request)
        plans.append(plan_entry(request, result.data, result.text))
    facts.plans = plans
    if not any(plan["output_count"] for plan in facts.plans):
        s.emit("assistant", "The plan has no executable output for these choices; choose other products.")
        facts.chosen, facts.plans = [], []


async def decide_gaps(s: AgentSession, form: Interaction, choices: dict[str, str]) -> bool:
    """Apply the person's gap choices, plan again with them, and show the next form under the
    same question (a model's review_plan call stays open): the gaps form again if some places
    are still undecided, else the plan review. False when nothing changed."""
    facts = s.facts
    if any(plan.get("job_id") for plan in facts.plans):
        s.emit("error", "A weather job already started from this plan; start a new request instead.",
               code="JOB_STARTED")
        return False
    if not apply_gap_choices(s, form, choices):
        return False
    facts.plans = []
    await make_plans(s)
    if not facts.plans:
        s.close_form()
        return True
    call = {"call_id": form.data["call_id"]} if "call_id" in form.data else {}
    max_chars = s.security.external_text.max_chars
    following = gaps_form(facts, max_chars=max_chars) if open_gaps(facts) else plan_form(facts, max_chars)
    s.open_form(following.model_copy(update={"data": {**following.data, **call}}))
    return True


def plan_form(facts: Facts, max_chars: int = 120) -> Interaction:
    """The plan review: Run approves exactly these plans; each part has a Change action."""
    shown = []
    for plan in facts.plans:
        heading = "Actual year" if plan["product"] == "historical" else "Typical year"
        started = f" (already started as job {plan['job_id'][:8]})" if plan.get("job_id") else ""
        shown.append(f"{heading}{started}: {plan['summary']}")
        shown.extend(f"Warning: {warning}" for warning in plan.get("warnings", [])[:5])
    rows = gap_rows(facts)
    if rows:
        shown.append("Data gaps:")
        shown.extend(f"- {gap_line(row, max_chars)}" for row in rows)
    if any(plan["product"] == "historical" for plan in facts.plans) and facts.review:
        shown.append(facts.review["standard_time"])
    shown.append("Listed sources are eligible to try; retrieved weather is checked by QC afterwards.")
    shown.extend(["Your request:", *lines(facts, max_chars=max_chars)])
    options = change_options(facts)
    if rows:
        options.append(Option(id="change:gaps", label="Change data gaps"))
    return Interaction(kind="plan_review", gate="review_plan",
                       prompt="Review the plan, then run it to start retrieval.",
                       summary="\n".join(shown), options=options,
                       # A copy: the run guard compares what was shown with the current plans.
                       data={"plans": [dict(plan) for plan in facts.plans],
                             "parts": parts(facts, max_chars=max_chars)})


def next_steps_form(facts: Facts) -> Interaction:
    options = [Option(id=choice, label=label) for choice, label in VIEWS] if facts.artifact_ids else []
    # Groups a finished job left wholly missing that another source could fill (session._finished).
    options += [Option(id=f"fill:{index}", label=f"{entry['option']['label']} for {entry['label'][:1].lower()}"
                       f"{entry['label'][1:]} ({entry['source']}) and plan again")
                for index, entry in enumerate(facts.after_gaps[:3])]
    if facts.finished_job_ids or facts.artifact_ids:
        options += [Option(id=choice, label=label) for choice, label in AFTER]
    if facts.retryable_jobs:
        options.append(Option(id="retry", label="Retry failed outputs"))
    if facts.finished_job_ids:
        options.append(Option(id="export", label="Compact ZIP of the outputs"))
    options.append(Option(id="new", label="Start a new weather request"))
    return Interaction(kind="choice", gate="next_steps", prompt="What next?", options=options)


def release(s: AgentSession, part: str, *, close: bool = True) -> bool:
    """Make room for the person's change to one part: the plan resets, a model question still
    open is closed as ``person_changed`` and the open form closes. False, with the reason shown,
    when a job already started from the plan.

    ``close=False`` keeps the open review until the next form replaces it (a replan that fails
    must not leave nothing to answer); a model's review becomes a host form, answered by the
    host rules, since its question is closed."""
    facts = s.facts
    if any(plan.get("job_id") for plan in facts.plans):
        s.emit("error", "A weather job already started from this plan; start a new request instead.",
               code="JOB_STARTED")
        return False
    facts.plans = []
    pending = s.state.pending_call
    if pending:
        s.state.turn.append({"type": "tool_result", "call_id": pending["id"], "name": pending["name"],
                             "output": json.dumps({"status": "person_changed", "part": part})})
        s.state.pending_call = None
    if close:
        s.close_form()
    elif s.form is not None and "call_id" in s.form.data:
        s.open_form(s.form.model_copy(update={"data": {key: value for key, value in s.form.data.items()
                                                        if key != "call_id"}}))
    return True


def products_with(s: AgentSession, selected: list[str]) -> None:
    """The product form with a typed change applied but not yet chosen: the person confirms it."""
    form = product_form(s.facts)
    s.open_form(form.model_copy(update={"data": {**form.data, "selected": selected, "change": "products"}}))


async def change_part(s: AgentSession, part: str, advance: Advance) -> None:
    """Change one part of the request (design §6.3): the host's path in both modes, no model call.

    The plan and its approval reset, a model question still open is closed as
    ``person_changed``, and only that part's form opens, with the current value shown or
    preselected. Opening it takes a snapshot, so Back undoes the Change.
    """
    facts = s.facts
    if part == "gaps" and gap_rows(facts):
        form = gaps_form(facts, change=True, max_chars=s.security.external_text.max_chars)
        if release(s, "gaps"):
            s.open_form(form)
        return
    if part not in PARTS:
        s.emit("error", "Choose one of the listed options.", code="UNKNOWN_CHOICE")
        return
    if not release(s, part):
        return
    max_chars = s.security.external_text.max_chars
    if part == "place":
        form = place_form(facts, max_chars)
    elif part == "years":
        form = years_form(facts)
    else:
        if part == "preference":
            facts.change("preference", (None, None), by="form", seq=s.seq)
        if status(facts, "place") != "confirmed":
            await advance(s)                         # products come after the location review
            return
        await fetch_offers(s, product=facts.product_type, provider=facts.provider)
        form = product_form(facts)
    s.open_form(form.model_copy(update={"data": {**form.data, "change": part}}))


async def answer_summary(s: AgentSession, form: Interaction, answer: Answer, advance: Advance) -> None:
    """Approve on a request summary the host opened. One opened on request (``/request``) returns
    to the form that was open in agent mode; otherwise the host goes on in guided order."""
    confirm_request(s)
    if "return_to" in form.data and s.state.mode == "agent":
        back = form.data["return_to"]
        stale = back and back.get("gate") == "review_plan" and not s.facts.plans
        if back and not stale:
            s.open_form(Interaction.model_validate(back))
        else:
            s.close_form()
            s.emit("assistant", "Your request is confirmed.")
        return
    await advance(s)


def shows_current_plans(s: AgentSession) -> bool:
    """True when the open form is a plan review listing exactly the plans run would submit."""
    shown = s.form.data.get("plans", []) if s.form and s.form.gate == "review_plan" else []
    return [plan["plan_hash"] for plan in shown] == [plan["plan_hash"] for plan in s.facts.plans]


async def run_plans(s: AgentSession, advance: Advance) -> list[str]:
    """Submit the reviewed plans after the person approved them; returns the started job ids.

    "Run" approves the plans on the open review, so a review that no longer matches the plans
    is reopened instead. Each approval answers exactly one confirmation.
    """
    if not shows_current_plans(s):
        s.emit("error", "The plan changed since it was shown; review it again before running.",
               code="GATE_REQUIRED", need="review_plan")
        await advance(s)
        return []
    plans = [plan for plan in s.facts.plans if plan["output_count"]]
    if not plans:
        s.emit("error", "There is no reviewed plan to run.", code="GATE_REQUIRED")
        return []
    if open_gaps(s.facts):
        s.emit("error", "Decide how to cover the data gaps before running.", code="GATE_REQUIRED",
               need="fill_gaps")
        await advance(s)
        return []
    started = []
    for plan in plans:
        if plan.get("job_id"):                       # started by an earlier, partly failed run
            continue
        s.approvals.approve(plan["plan_hash"])
        try:
            job = (await s.tool("weather_submit", plan_hash=plan["plan_hash"],
                                idempotency_key=f"agent:{s.id}:{plan['plan_hash'][:16]}")).data
        except Exception:
            if s.facts.job_ids:
                try:
                    await advance(s)                 # show which plans already started
                except Exception:
                    pass                             # the submission failure is the one to report
            raise
        finally:
            # One approval, one submission: never leave it pending if the server did not ask.
            s.approvals.consume(plan["plan_hash"])
        s.facts.plans = [{**item, "job_id": job["id"]} if item["plan_hash"] == plan["plan_hash"]
                         else item for item in s.facts.plans]
        if job["id"] not in s.facts.job_ids:
            s.facts.job_ids.append(job["id"])
        if plan["plan_hash"] not in s.facts.started_plans:
            s.facts.started_plans.append(plan["plan_hash"])
        started.append(job["id"])
        s.emit("job", f"Weather job {job['id'][:8]} started", job_id=job["id"], state=job.get("state"))
    s.close_form()
    return started


def refill(s: AgentSession, index: int) -> bool:
    """Plan the request again with a fill a finished job's results suggested (next steps):
    the group's earlier rule is replaced. Earlier files stay available."""
    facts = s.facts
    if not 0 <= index < len(facts.after_gaps):
        s.emit("error", "Choose one of the listed options.", code="UNKNOWN_CHOICE")
        return False
    entry = facts.after_gaps[index]
    fill = VariableFill.model_validate(entry["option"]["fill"]).model_dump(mode="json", exclude_none=True)
    facts.fills = [rule for rule in facts.fills if _rule_key(rule) != _rule_key(fill)] + [fill]
    facts.stage, facts.job_ids, facts.plans, facts.after_gaps = "request", [], [], []
    s.emit("assistant", f"Planning again: {entry['label']} for {entry['source']}: {entry['option']['label']}. "
                        "Review the plan, then run it.", code="GAPS_DECIDED")
    return True


async def visualize(s: AgentSession, family: str, *, by: str = "host") -> None:
    result = await s.tool("weather_visualize", by=by, request={
        "artifact_ids": s.facts.artifact_ids[-100:], "family": family, "variable": "dry_bulb"})
    s.emit("view", result.text, view_id=result.data["view_id"], family=family, variable="dry_bulb")


async def export(s: AgentSession) -> None:
    for job_id in s.facts.finished_job_ids:
        try:
            data = (await s.tool("weather_export_compact", job_id=job_id)).data
        except ToolFailure as failure:              # one job without a bundle must not stop the rest
            s.emit("error", f"Job {job_id[:8]}: {failure.code}: {failure.message}",
                   code=failure.code, job_id=job_id)
            continue
        offer_export(s, data["artifact_id"], data["bytes"], data.get("sha256"))
