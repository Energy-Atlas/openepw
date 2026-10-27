# Agent request steps as separate lookups and slots — proposal (draft)

**Status:** proposal recorded 2026-10-12 at the owner's request. The owner answered §6 on
2026-10-13: (1) yes, (2) yes with a label, (3) always reset, (4) **as now** (text at an open form
stays its answer, so phase (c) is Back per slot only), (5) phase (a) first, (6) spec and plan first.
Phase (a): [agent request lookups design](2026-10-13-agent-request-lookups-design.md), approved
2026-10-26. Phases (b)–(d) are not designed.

## 1. The owner's observation

Location geocoding, choosing among place candidates, the product list and the years feel coupled:
the agent runs them as one chain with nothing in between. The owner asked whether each step can be
its own tool call that sends a form for structured input and records the answer in the context.

## 2. What exists now

Each step is already a host ask-tool that opens a form, and answers are stored as structured facts
the model sees on every call (the state block):

| Step | Ask-tool | Form | Stored as |
| --- | --- | --- | --- |
| Pick among place candidates | `ask_choice` | choice | (the chosen point, passed on) |
| Review and approve locations | `review_location` | location review | `facts.review`, `facts.approved_key` |
| Choose products | `choose_products` | product choice | `facts.offers`, `facts.chosen` |
| Years | `ask_text` (purpose `years`) | text | `facts.years` |
| Review and run the plan | `review_plan` | plan review | `facts.plans`, then jobs |

## 3. Where the coupling comes from

1. **Looking and asking are one step.** `weather_locations_review` and `weather_product_offers` are
   reachable only through the ask-tools, which open a form and suspend the model until the person
   answers. The model never sees the offers before the form, so it cannot answer "does NSRDB have
   2023?" (the 2026-10-12 label misses G09–G16; the product-form availability line is a stopgap).
2. **The order is fixed end to end.** Products need an approved location; a plan needs location,
   products and years; years are asked only when planning needs them, although years change what is
   available.
3. **Invalidation is coarse.** A new place resets offers, chosen products and plans
   (`Facts.set_geography`). There is no "change only the years" or "keep my product preference".
4. **No in-between.** While a form is open, typed text becomes that form's answer (only small talk is
   intercepted), so the person cannot ask a question and come back to the form.
5. **Facts are one object,** not slots with their own status ("proposed", "confirmed", "stale") and
   origin.

## 4. Proposal

- **Read-only lookups as model tools,** returning data without a form: place candidates, a location
  preview with standard-time offsets, and product offers with availability for the place and years.
  They change nothing, so they need no gate; the gates stay on planning and submitting.
- **One ask-tool per slot,** each opening its form and recording the answer: place (candidate choice,
  then approval), product preference (actual or typical year, provider), chosen offers, years. Years
  and product preference may come before the place; concrete offers still need an approved place.
- **Slot memory:** each slot holds a value, its origin (typed by the person, a form answer, or derived
  by the host), a status (proposed, confirmed, stale) and the event it came from. The model sees a
  slot table instead of one facts object.
- **Targeted invalidation:** a new place marks the chosen offers "to recheck" but keeps years and
  preferences; new years recheck availability; the plan and its approval always reset. Back works per
  slot ("change only the years").
- **Forms that do not block:** a question asked while a form is open is answered and the form stays
  open.
- **Unchanged guarantees:** plans are built only from confirmed slots; each approval answers one
  submission; host-only tools stay host-only; guided mode keeps the same slots (deterministic filler).

## 5. Costs, risks and phasing

- ADR 0005 changes (forms and gates); most work is in `policy_model`, `gates`, `state` and `guided`.
- Eval tasks that check a strict form order move towards outcome checks.
- A few more model steps per request (lookups before asks); a small cost increase.
- The P4 web chat gains natural per-step cards and an editable request summary.

| Phase | Content |
| --- | --- |
| (a) | Read-only lookups as model tools; availability answered in words from offers |
| (b) | Slots with status, origin and targeted invalidation; years and preferences in any order |
| (c) | Forms that do not block; Back per slot |
| (d) | Guided-mode parity |

## 6. Open questions for the owner

1. May product preference (actual or typical year, provider) and years be given before the location
   is approved? (Proposed: yes; concrete offers still only after approval.)
2. May the model look up offers for a place that is not yet approved, to answer availability questions
   (read-only)? (Proposed: yes for answering; choosing still after approval.)
3. Should a slot change keep or reset the plan review's approval? (Proposed: any slot change resets the
   plan and its approval, as now.)
4. Forms that do not block: should a typed question at an open form always go to the model, with the
   form kept, or should text still default to answering the form, as now?
5. Phasing: start with (a) only, then decide (b)–(d)?
6. Write this up as a spec and plan for approval before any implementation?
