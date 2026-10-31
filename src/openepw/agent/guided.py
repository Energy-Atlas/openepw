"""Guided mode: rule-based forms in the gate order, reading text offline."""

from __future__ import annotations

import re
from typing import Any

from ..models import OpenEPWError
from ..places.parse import apply_edit, describe_place_set
from . import host
from .gates import build_requests, needs_years, next_need
from .guard import clean_external
from .interactions import Answer, Interaction, Option
from .session import AgentSession
from .slots import request_form
from .text import FUTURE, place_part, read_product, reads_as_question, written_years

SUSPENDED = ("Future-weather planning is temporarily unavailable; ask for actual-year (historical) "
             "or typical-year weather instead.")
UNREAD = ("Guided mode reads places, coordinates, years and product names for weather files and "
          "cannot answer other questions. Use the form.")
# Text that cannot be a place name: formula characters, or a question or instruction verb first.
_NOT_A_PLACE = re.compile(r"[=^*{}<>|\\]|^(?:how|why|who|when|explain|solve|write|tell|define|calculate|"
                          r"compute|translate|summari[sz]e|can you|could you|please)\b", re.I)


def not_a_place(place: str) -> bool:
    """Place text guided mode should not send to the geocoder (a sentence, not a place list)."""
    one_line = "\n" not in place and "," not in place and ";" not in place
    return bool(place) and one_line and (len(place.split()) > 6 or bool(_NOT_A_PLACE.search(place)))
APPROVE = re.compile(r"a|approve|approved|yes|y|ok|okay|correct|looks good", re.I)
RUN = re.compile(r"run|r|yes|go|start|approve", re.I)
# Asking to see the request summary (the CLI's /request does the same).
SHOW_REQUEST = re.compile(r"(?:show|see|review)(?: me)? (?:my|the) request|what (?:have i|did i) (?:chosen|choose)"
                          r"|my request", re.I)
PLACE_GATES = {None, "where", "choose_location", "review_location", "place_set", "review_plan",
               "next_steps"}
REFERENCE_LABELS = {"tmy": "TMY", "tmyx": "TMYx", "published": "A published EPW"}


class GuidedPolicy:
    name = "guided"

    # Text -----------------------------------------------------------------------------
    async def on_text(self, s: AgentSession, text: str) -> None:
        gate = s.form.gate if s.form else None
        if FUTURE.search(text):
            s.emit("assistant", SUSPENDED)
            return
        if SHOW_REQUEST.fullmatch(text.strip(" ?.!")):
            s.open_request_summary()
            return
        if gate == "review_location" and APPROVE.fullmatch(text):
            await self._approve_location(s)
            return
        if gate == "review_request" and APPROVE.fullmatch(text):
            assert s.form is not None
            await host.answer_summary(s, s.form, Answer(interaction_id=s.form.id, revision=s.form.revision,
                                                        approve=True), self.advance)
            return
        if gate == "review_plan" and RUN.fullmatch(text):
            await self._run(s)
            return
        if (not_a_place(place_part(text)) and not written_years(text) and not read_product(text)
                and not describe_place_set(text)):
            s.emit("assistant", UNREAD)                # unrelated text: no geocoding, form kept
            return
        if gate == "next_steps":
            s.facts.new_request()
            gate = "where"
        # A bare number answers a place-set question (a population or limit), never a weather year.
        bare_answer = gate == "place_set" and re.fullmatch(r"[\d,.\s]+[km]?", text, re.I)
        changed = self._read_time_and_product(s, "" if bare_answer else text)
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
        """A product word changes the preference (chosen products that no longer fit are
        rechecked); years replace the years, proposed when written in a question."""
        facts = s.facts
        changed = False
        product = read_product(text)
        if product and product != facts.product_type:
            facts.change("preference", (product, facts.provider), by="text", seq=s.seq)
            changed = True
        # "over 2000 people" and "top 1900" describe a place set, not a weather year.
        years = sorted(written_years(text))
        if not years:
            return changed
        reference = product in REFERENCE_LABELS or (product is None and facts.chosen and not needs_years(facts))
        if reference:
            label = REFERENCE_LABELS.get(product or "", "The chosen product")
            written = ", ".join(map(str, years))
            s.emit("assistant", f"{label} is a reference product, not actual-year weather for {written}. "
                                f"Ask for actual-year weather for {written}, or for it without a year.")
            return True
        proposed = [year for year in years if year not in facts.confirmed_years] if reads_as_question(text) else []
        if years != facts.years or proposed != facts.proposed_years:
            facts.change("years", years, by="text", seq=s.seq, proposed=proposed)
            changed = True
        if facts.product_type is None:
            facts.product_type = "historical"
            facts.origins["preference"] = {"by": "text", "seq": s.seq}
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
            s.facts.change("place", {"lat": lat, "lon": lon}, by="text", seq=s.seq)
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
            s.facts.change("place", host.point(candidates[0]), by="host", seq=s.seq)
        else:
            s.facts.change("place", None, by="host", seq=s.seq)
            s.facts.candidates = candidates[:10]

    async def _preview(self, s: AgentSession, items: list[Any]) -> None:
        self._apply_rows(s, (await s.tool("weather_places_preview", places=items)).data)

    def _apply_rows(self, s: AgentSession, data: dict[str, Any]) -> None:
        rows = data.get("rows", [])
        s.facts.reset_place()
        s.facts.place_rows = rows
        points = [{"lat": row["lat"], "lon": row["lon"], "name": row.get("name")}
                  for row in rows if row.get("status") == "resolved"]
        s.facts.change("place", points or None, by="host", seq=s.seq)
        lines = [f"Previewed {data.get('resolved', len(points))} of {len(rows)} places. Fix anything by text, "
                 "for example 'remove 3' or 'add Reno'."]
        for row in rows[:25]:
            if row.get("status") != "resolved":
                lines.append(f"{row['index']}. '{row['input']}' not found; replace or remove it")
            else:
                note = f"; top of {row['candidate_count']} matches, check it" if row.get("ambiguous") else ""
                name = clean_external(str(row.get("name")), s.security.external_text.max_chars)
                lines.append(f"{row['index']}. {name} ({row['lat']:.4f}, {row['lon']:.4f}){note}")
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
            s.facts.change("place", None, by="text", seq=s.seq)
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
        if gate == "review_request" and answer.approve:
            await host.answer_summary(s, form, answer, self.advance)
            return
        if gate == "where" and answer.value is not None:
            s.facts.reset_place()
            s.facts.change("place", answer.value, by="form", seq=s.seq)
            await self.advance(s)
            return
        known = {option.id for option in form.options}
        if (not answer.choice_ids or not set(answer.choice_ids) <= known
                or (not form.multi and len(answer.choice_ids) != 1)):
            s.emit("error", "Choose one of the listed options.", code="UNKNOWN_CHOICE")
            return
        choice = answer.choice_ids[0]
        if choice.startswith("change:"):                 # plan review or request summary
            await host.change_part(s, choice.split(":", 1)[1], self.advance)
            return
        if gate == "choose_location":
            candidate = next(item for index, item in enumerate(s.facts.candidates)
                             if str(item.get("id", index)) == choice)
            s.facts.candidates = []
            s.facts.change("place", host.point(candidate), by="form", seq=s.seq)
        elif gate == "place_set":
            await self._continue_place_set(s, form.data["answers"][choice])
        elif gate == "choose_products":
            host.choose(s, answer.choice_ids)
            if not needs_years(s.facts):
                s.facts.years, s.facts.proposed_years = [], []
        elif gate == "next_steps":
            await self._next_step(s, choice)
            return
        await self.advance(s)

    async def _approve_location(self, s: AgentSession) -> None:
        if s.facts.review is None:
            s.emit("error", "There is no location review to approve.", code="GATE_REQUIRED")
            return
        s.facts.approved_key = s.facts.review["key"]
        s.facts.origins["place"] = {"by": "form", "seq": s.seq}
        s.emit("assistant", "Location approved.")
        await self.advance(s)

    async def _run(self, s: AgentSession) -> None:
        await host.run_plans(s, self.advance)

    async def _next_step(self, s: AgentSession, choice: str) -> None:
        if choice == "new":
            s.facts.new_request()
        elif choice.startswith("view:"):
            await host.visualize(s, choice.split(":", 1)[1])
        elif choice == "export":
            await host.export(s)
        await self.advance(s)

    # Forms ------------------------------------------------------------------------------
    async def advance(self, s: AgentSession) -> None:
        facts = s.facts
        need = next_need(facts)
        if need == "place_set":
            s.open_form(host.place_set_form(facts.place_set or {}))
        elif need == "choose_location":
            s.open_form(Interaction(
                kind="choice", gate="choose_location", prompt="Which location do you mean?",
                options=[Option(id=str(item.get("id", index)),
                                label=clean_external(str(item.get("name") or "unnamed"),
                                                     s.security.external_text.max_chars),
                                detail=f"{item['lat']:.4f}, {item['lon']:.4f}")
                         for index, item in enumerate(facts.candidates)]))
        elif need == "where":
            s.open_form(host.place_form())
        elif need == "review_location":
            if facts.review is None:
                facts.review = (await s.tool("weather_locations_review", locations=facts.geography)).data
            s.open_form(host.review_form(facts, s.security.external_text.max_chars))
        elif need == "choose_products":
            if not facts.offers:                          # next_need guarantees an approved review
                await host.fetch_offers(s, product=facts.product_type, provider=facts.provider)
            s.open_form(host.product_form(facts))
        elif need == "years":
            s.open_form(host.years_form(facts))
        elif need == "confirm_request":
            s.open_form(request_form(facts, max_chars=s.security.external_text.max_chars))
        elif need == "plan":
            await self._plan(s)
        elif need == "review_plan":
            # The open review must show exactly the plans that "run" submits.
            if not (s.form and s.form.gate == "review_plan" and s.form.data.get("plans") == facts.plans):
                s.open_form(host.plan_form(facts, s.security.external_text.max_chars))
        elif need == "next_steps":
            s.open_form(host.next_steps_form(facts))
        else:                                              # "jobs": retrieval is running
            s.close_form()

    async def _plan(self, s: AgentSession) -> None:
        facts = s.facts
        await host.refresh_offers(s)                     # after new years or a new preference
        if facts.recheck:
            await self.advance(s)                        # the product form, still-offered ones selected
            return
        plans = []
        for request in build_requests(facts):
            result = await s.tool("weather_plan", request=request)
            plans.append(host.plan_entry(request, result.data, result.text))
        facts.plans = plans                              # all or nothing: never a half-built plan set
        if not any(plan["output_count"] for plan in facts.plans):
            s.emit("assistant", "The plan has no executable output for these choices; choose other products.")
            facts.chosen, facts.plans = [], []
        await self.advance(s)
