"""Guided mode: rule-based forms in the gate order, reading text offline."""

from __future__ import annotations

import re
from typing import Any

from ..models import OpenEPWError
from ..places.parse import POPULATION, apply_edit, describe_place_set
from .gates import build_requests, needs_years, next_need
from .interactions import Answer, Interaction, Option
from .mcp_port import ToolFailure
from .session import AgentSession
from .text import FUTURE, explicit_weather_years, place_part, read_product

SUSPENDED = ("Future-weather planning is temporarily unavailable; ask for actual-year (historical) "
             "or typical-year weather instead.")
UNREAD = "Guided mode reads places, coordinates, years and product names. Use the form."
APPROVE = re.compile(r"a|approve|approved|yes|y|ok|okay|correct|looks good", re.I)
RUN = re.compile(r"run|r|yes|go|start|approve", re.I)
PLACE_GATES = {None, "where", "choose_location", "review_location", "place_set", "review_plan",
               "next_steps"}
_HEADCOUNT = re.compile(r"\b(?:top|largest|biggest|first)\s+\d+", re.I)
REFERENCE_LABELS = {"tmy": "TMY", "tmyx": "TMYx", "published": "A published EPW"}
VIEWS = (("view:monthly_series", "Monthly dry-bulb temperature chart"),
         ("view:histogram", "Dry-bulb temperature distribution"))


def _offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    return f"UTC{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _point(candidate: dict[str, Any]) -> dict[str, Any]:
    """A geocoder candidate as a request point; its default offset (0) must not be kept."""
    return {key: candidate[key] for key in ("lat", "lon", "name", "id", "elevation")
            if candidate.get(key) is not None}


class GuidedPolicy:
    name = "guided"

    # Text -----------------------------------------------------------------------------
    async def on_text(self, s: AgentSession, text: str) -> None:
        gate = s.form.gate if s.form else None
        if FUTURE.search(text):
            s.emit("assistant", SUSPENDED)
            return
        if gate == "review_location" and APPROVE.fullmatch(text):
            await self._approve_location(s)
            return
        if gate == "review_plan" and RUN.fullmatch(text):
            await self._run(s)
            return
        if gate == "next_steps":
            s.facts.new_request()
            gate = "where"
        # Place-set answers are populations and limits, never weather years.
        changed = self._read_time_and_product(s, text if gate != "place_set" else "")
        place = place_part(text) if gate in PLACE_GATES else ""
        if gate == "place_set" and place and s.facts.place_set:
            await self._continue_place_set(s, place)
        elif gate == "review_location" and s.facts.place_rows and await self._edit_list(s, text):
            pass
        elif place:
            await self._read_place(s, text, place)
        elif not changed:
            s.emit("assistant", UNREAD)
            return
        await self.advance(s)

    def _read_time_and_product(self, s: AgentSession, text: str) -> bool:
        facts = s.facts
        changed = False
        product = read_product(text)
        if product and product != facts.product_type:
            facts.product_type = product
            facts.offers, facts.offer_availability, facts.chosen, facts.plans = [], None, [], []
            changed = True
        # "over 2000 people" and "top 1900" describe a place set, not a weather year.
        years = sorted(explicit_weather_years(_HEADCOUNT.sub(" ", POPULATION.sub(" ", text))))
        if not years:
            return changed
        reference = product in REFERENCE_LABELS or (product is None and facts.chosen and not needs_years(facts))
        if reference:
            label = REFERENCE_LABELS.get(product or "", "The chosen product")
            written = ", ".join(map(str, years))
            s.emit("assistant", f"{label} is a reference product, not actual-year weather for {written}. "
                                f"Ask for actual-year weather for {written}, or for it without a year.")
            return True
        if years != facts.years:
            facts.years = years
            facts.plans = []
            if not facts.chosen:                 # the offers' availability is per year
                facts.offers, facts.offer_availability = [], None
            changed = True
        if facts.product_type is None:
            facts.product_type = "historical"
        return changed

    async def _read_place(self, s: AgentSession, text: str, place: str) -> None:
        if describe_place_set(text):
            result = (await s.tool("weather_places_interpret", text=text)).data
            await self._place_set_result(s, result)
            return
        result = (await s.tool("weather_places_interpret", text=place)).data
        kind = result.get("kind")
        if kind == "invalid":
            s.emit("assistant", (result.get("issue") or {}).get("message", "That place text is not valid."))
        elif kind == "descriptive":
            await self._place_set_result(s, result)
        elif kind == "coordinates" and len(result.get("points", [])) == 1:
            lat, lon = result["points"][0]
            s.facts.reset_place()
            s.facts.set_geography({"lat": lat, "lon": lon})
        elif kind == "single":
            await self._geocode(s, result["items"][0])
        else:
            items = (result.get("items") if kind == "list"
                     else [f"{lat}, {lon}" for lat, lon in result.get("points", [])])
            await self._preview(s, items or [])

    async def _geocode(self, s: AgentSession, name: str) -> None:
        candidates = (await s.tool("weather_geocode", query=name)).data.get("candidates", [])
        match = re.fullmatch(r"\s*(.+?)[\s,]+([A-Za-z]{2})\s*", name)
        if not candidates and match:
            normalized = f"{match.group(1).rstrip(', ')}, {match.group(2).upper()}"
            if normalized != name:
                candidates = (await s.tool("weather_geocode", query=normalized)).data.get("candidates", [])
        s.facts.reset_place()
        if not candidates:
            s.emit("assistant", f"No location matched '{name}'. Give coordinates or a more specific place.")
        elif len(candidates) == 1:
            s.facts.set_geography(_point(candidates[0]))
        else:
            s.facts.set_geography(None)
            s.facts.candidates = candidates[:10]

    async def _preview(self, s: AgentSession, items: list[Any]) -> None:
        self._apply_rows(s, (await s.tool("weather_places_preview", places=items)).data)

    def _apply_rows(self, s: AgentSession, data: dict[str, Any]) -> None:
        rows = data.get("rows", [])
        s.facts.reset_place()
        s.facts.place_rows = rows
        points = [{"lat": row["lat"], "lon": row["lon"], "name": row.get("name")}
                  for row in rows if row.get("status") == "resolved"]
        s.facts.set_geography(points or None)
        lines = [f"Previewed {data.get('resolved', len(points))} of {len(rows)} places. Fix anything by text, "
                 "for example 'remove 3' or 'add Reno'."]
        for row in rows[:25]:
            if row.get("status") != "resolved":
                lines.append(f"{row['index']}. '{row['input']}' not found; replace or remove it")
            else:
                note = f"; top of {row['candidate_count']} matches, check it" if row.get("ambiguous") else ""
                lines.append(f"{row['index']}. {row.get('name')} ({row['lat']:.4f}, {row['lon']:.4f}){note}")
        if len(rows) > 25:
            lines.append(f"... and {len(rows) - 25} more")
        s.emit("assistant", "\n".join(lines + list(data.get("attribution") or [])))
        if not points:
            s.emit("assistant", "None of those places resolved; give places or coordinates.")

    async def _edit_list(self, s: AgentSession, text: str) -> bool:
        rows = s.facts.place_rows
        labels = [row.get("name") or row["input"] for row in rows]
        try:
            edited = apply_edit(labels, text)
        except OpenEPWError as error:
            s.emit("assistant", error.issue.message)
            return True
        if edited is None:
            return False
        if not edited:
            s.facts.reset_place()
            s.facts.set_geography(None)
            s.emit("assistant", "The place list is now empty; give places or coordinates.")
            return True
        by_label = dict(zip(labels, rows))
        await self._preview(s, [by_label.get(label, label) for label in edited])
        return True

    async def _place_set_result(self, s: AgentSession, result: dict[str, Any]) -> None:
        if result.get("questions"):
            s.facts.candidates = []
            s.facts.place_set = {"draft": result["draft"], "questions": result["questions"]}
            return
        if result.get("query"):
            s.facts.place_set = None
            self._apply_rows(s, (await s.tool("weather_place_set", query=result["query"])).data)

    async def _continue_place_set(self, s: AgentSession, reply: str) -> None:
        assert s.facts.place_set is not None
        result = (await s.tool("weather_places_interpret", text=reply, draft=s.facts.place_set["draft"])).data
        await self._place_set_result(s, result)

    # Answers ----------------------------------------------------------------------------
    async def on_answer(self, s: AgentSession, form: Interaction, answer: Answer) -> None:
        gate = form.gate
        if answer.text:
            await self.on_text(s, answer.text)
            return
        if gate == "review_location" and answer.approve:
            await self._approve_location(s)
            return
        if gate == "review_plan" and answer.approve:
            await self._run(s)
            return
        if gate == "where" and answer.value is not None:
            s.facts.reset_place()
            s.facts.set_geography(answer.value)
            await self.advance(s)
            return
        known = {option.id for option in form.options}
        if (not answer.choice_ids or not set(answer.choice_ids) <= known
                or (not form.multi and len(answer.choice_ids) != 1)):
            s.emit("error", "Choose one of the listed options.", code="UNKNOWN_CHOICE")
            return
        choice = answer.choice_ids[0]
        if gate == "choose_location":
            candidate = next(item for index, item in enumerate(s.facts.candidates)
                             if str(item.get("id", index)) == choice)
            s.facts.candidates = []
            s.facts.set_geography(_point(candidate))
        elif gate == "place_set":
            await self._continue_place_set(s, form.data["answers"][choice])
        elif gate == "choose_products":
            s.facts.chosen = [offer for offer in s.facts.offers if offer["id"] in answer.choice_ids]
            s.facts.plans = []
            if not needs_years(s.facts):
                s.facts.years = []
        elif gate == "next_steps":
            await self._next_step(s, choice)
            return
        await self.advance(s)

    async def _approve_location(self, s: AgentSession) -> None:
        if s.facts.review is None:
            s.emit("error", "There is no location review to approve.", code="GATE_REQUIRED")
            return
        s.facts.approved_key = s.facts.review["key"]
        s.emit("assistant", "Location approved.")
        await self.advance(s)

    async def _run(self, s: AgentSession) -> None:
        shown = s.form.data.get("plans", []) if s.form and s.form.gate == "review_plan" else []
        if [plan["plan_hash"] for plan in shown] != [plan["plan_hash"] for plan in s.facts.plans]:
            # "run" approves the plans on the open review, so they must be the plans submitted.
            s.emit("error", "The plan changed since it was shown; review it again before running.",
                   code="GATE_REQUIRED", need="review_plan")
            await self.advance(s)
            return
        plans = [plan for plan in s.facts.plans if plan["output_count"]]
        if not plans:
            s.emit("error", "There is no reviewed plan to run.", code="GATE_REQUIRED")
            return
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
                        await self.advance(s)            # show which plans already started
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
            s.emit("job", f"Weather job {job['id'][:8]} started", job_id=job["id"], state=job.get("state"))
        s.close_form()

    async def _next_step(self, s: AgentSession, choice: str) -> None:
        if choice == "new":
            s.facts.new_request()
        elif choice.startswith("view:"):
            family = choice.split(":", 1)[1]
            result = await s.tool("weather_visualize", request={
                "artifact_ids": s.facts.artifact_ids[-100:], "family": family, "variable": "dry_bulb"})
            s.emit("view", result.text, view_id=result.data["view_id"], family=family, variable="dry_bulb")
        elif choice == "export":
            for job_id in s.facts.finished_job_ids:
                try:
                    data = (await s.tool("weather_export_compact", job_id=job_id)).data
                except ToolFailure as failure:          # one job without a bundle must not stop the rest
                    s.emit("error", f"Job {job_id[:8]}: {failure.code}: {failure.message}",
                           code=failure.code, job_id=job_id)
                    continue
                s.emit("assistant", f"Compact ZIP ready: artifact {data['artifact_id']} ({data['bytes']} bytes).",
                       artifact_id=data["artifact_id"])
        await self.advance(s)

    # Forms ------------------------------------------------------------------------------
    async def advance(self, s: AgentSession) -> None:
        facts = s.facts
        need = next_need(facts)
        if need == "place_set":
            s.open_form(self._place_set_form(facts.place_set or {}))
        elif need == "choose_location":
            s.open_form(Interaction(
                kind="choice", gate="choose_location", prompt="Which location do you mean?",
                options=[Option(id=str(item.get("id", index)), label=item.get("name") or "unnamed",
                                detail=f"{item['lat']:.4f}, {item['lon']:.4f}")
                         for index, item in enumerate(facts.candidates)]))
        elif need == "where":
            s.open_form(Interaction(
                kind="map_input", gate="where", prompt="Where do you need weather?",
                summary="Give a place name, a list of places, or coordinates such as 42.44, -76.50.",
                data={"hint": "e.g. Ithaca, NY · Boston; Denver · 42.44, -76.50"}))
        elif need == "review_location":
            if facts.review is None:
                facts.review = (await s.tool("weather_locations_review", locations=facts.geography)).data
            s.open_form(self._review_form(facts))
        elif need == "choose_products":
            assert facts.review is not None               # next_need guarantees an approved review
            if not facts.offers:
                data = (await s.tool("weather_product_offers", locations=facts.review["geography"],
                                     product=facts.product_type, provider=facts.provider,
                                     years=facts.years or None)).data
                facts.offers = data.get("options", [])
                facts.offer_availability = data.get("availability")
            s.open_form(Interaction(
                kind="product_choice", gate="choose_products", multi=True, prompt="Which weather products?",
                summary="Listed means eligible to try retrieval, not quality assured.",
                options=[Option(id=offer["id"], label=offer["label"], detail=offer.get("detail"))
                         for offer in facts.offers],
                data={"availability": facts.offer_availability}))
        elif need == "years":
            s.open_form(Interaction(kind="text", gate="years", prompt="Which actual year or years?",
                                    summary="Actual-year products need calendar years.",
                                    data={"hint": "e.g. 2018 or 2016-2018"}))
        elif need == "plan":
            await self._plan(s)
        elif need == "review_plan":
            # The open review must show exactly the plans that "run" submits.
            if not (s.form and s.form.gate == "review_plan" and s.form.data.get("plans") == facts.plans):
                s.open_form(self._plan_form(facts))
        elif need == "next_steps":
            s.open_form(self._next_steps_form(facts))
        else:                                              # "jobs": retrieval is running
            s.close_form()

    async def _plan(self, s: AgentSession) -> None:
        facts = s.facts
        plans = []
        for request in build_requests(facts):
            result = await s.tool("weather_plan", request=request)
            plans.append({"plan_hash": result.data["plan_hash"], "product": request["product"],
                          "output_count": result.data.get("output_count", 0), "summary": result.text,
                          "warnings": result.data.get("warnings", [])})
        facts.plans = plans                              # all or nothing: never a half-built plan set
        if not any(plan["output_count"] for plan in facts.plans):
            s.emit("assistant", "The plan has no executable output for these choices; choose other products.")
            facts.chosen, facts.plans = [], []
        await self.advance(s)

    @staticmethod
    def _place_set_form(place_set: dict[str, Any]) -> Interaction:
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

    @staticmethod
    def _review_form(facts: Any) -> Interaction:
        review = facts.review
        count = review["point_count"]
        lines = [f"{index}. {point.get('name') or 'point'} ({point['lat']:.4f}, {point['lon']:.4f}) "
                 f"{_offset(point['standard_offset_minutes'])}"
                 for index, point in enumerate(review["points"][:25], start=1)]
        if count > 25:
            lines.append(f"... and {count - 25} more")
        lines.append(review["standard_time"])
        return Interaction(
            kind="location_review", gate="review_location",
            prompt="Are these the right locations?" if count > 1 else "Is this the right location?",
            summary="\n".join(lines), data={**review, "several": count > 1, "rows": facts.place_rows})

    @staticmethod
    def _plan_form(facts: Any) -> Interaction:
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
                           summary="\n".join(lines), data={"plans": facts.plans})

    @staticmethod
    def _next_steps_form(facts: Any) -> Interaction:
        options = [Option(id=choice, label=label) for choice, label in VIEWS] if facts.artifact_ids else []
        if facts.finished_job_ids:
            options.append(Option(id="export", label="Compact ZIP of the outputs"))
        options.append(Option(id="new", label="Start a new weather request"))
        return Interaction(kind="choice", gate="next_steps", prompt="What next?", options=options)
