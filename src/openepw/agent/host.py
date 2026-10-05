"""Host steps both policies share: the forms they open and the one guarded way to run plans."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from .interactions import Interaction, Option
from .mcp_port import ToolFailure
from .session import AgentSession
from .state import Facts

VIEWS = (("view:monthly_series", "Monthly dry-bulb temperature chart"),
         ("view:histogram", "Dry-bulb temperature distribution"))
Advance = Callable[[AgentSession], Awaitable[None]]


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
            "warnings": data.get("warnings", [])}


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


def review_form(facts: Facts) -> Interaction:
    review = facts.review
    assert review is not None
    count = review["point_count"]
    lines = [f"{index}. {item.get('name') or 'point'} ({item['lat']:.4f}, {item['lon']:.4f}) "
             f"{offset(item['standard_offset_minutes'])}"
             for index, item in enumerate(review["points"][:25], start=1)]
    if count > 25:
        lines.append(f"... and {count - 25} more")
    lines.append(review["standard_time"])
    return Interaction(
        kind="location_review", gate="review_location",
        prompt="Are these the right locations?" if count > 1 else "Is this the right location?",
        summary="\n".join(lines), data={**review, "several": count > 1, "rows": facts.place_rows})


def product_form(facts: Facts) -> Interaction:
    return Interaction(
        kind="product_choice", gate="choose_products", multi=True, prompt="Which weather products?",
        summary="Listed means eligible to try retrieval, not quality assured.",
        options=[Option(id=offer["id"], label=offer["label"], detail=offer.get("detail"))
                 for offer in facts.offers],
        data={"availability": facts.offer_availability})


def years_form() -> Interaction:
    return Interaction(kind="text", gate="years", prompt="Which actual year or years?",
                       summary="Actual-year products need calendar years.",
                       data={"hint": "e.g. 2018 or 2016-2018"})


def plan_form(facts: Facts) -> Interaction:
    lines = []
    for plan in facts.plans:
        heading = "Actual year" if plan["product"] == "historical" else "Typical year"
        started = f" (already started as job {plan['job_id'][:8]})" if plan.get("job_id") else ""
        lines.append(f"{heading}{started}: {plan['summary']}")
        lines.extend(f"Warning: {warning}" for warning in plan.get("warnings", [])[:5])
    if any(plan["product"] == "historical" for plan in facts.plans) and facts.review:
        lines.append(facts.review["standard_time"])
    lines.append("Listed sources are eligible to try; retrieved weather is checked by QC afterwards.")
    return Interaction(kind="plan_review", gate="review_plan",
                       prompt="Review the plan, then run it to start retrieval.",
                       # A copy: the run guard compares what was shown with the current plans.
                       summary="\n".join(lines), data={"plans": [dict(plan) for plan in facts.plans]})


def next_steps_form(facts: Facts) -> Interaction:
    options = [Option(id=choice, label=label) for choice, label in VIEWS] if facts.artifact_ids else []
    if facts.finished_job_ids:
        options.append(Option(id="export", label="Compact ZIP of the outputs"))
    options.append(Option(id="new", label="Start a new weather request"))
    return Interaction(kind="choice", gate="next_steps", prompt="What next?", options=options)


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
        s.emit("assistant", f"Compact ZIP ready: artifact {data['artifact_id']} ({data['bytes']} bytes).",
               artifact_id=data["artifact_id"])
