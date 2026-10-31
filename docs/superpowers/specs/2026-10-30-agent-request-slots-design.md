# Agent request slots (slots phases b–d) — design

**Status:** written 2026-10-30 in phase 3 of the
[outstanding work plan](../plans/2026-10-30-outstanding-work.md). **Approved by the owner on
2026-10-31** with the §14 defaults (questions 1–3) and a $1 live check cap; question 4 (P4 as a
phase) was not decided. Built in phase 4 and merged into `main` on 2026-10-31; see the
[plan](../plans/2026-10-30-agent-request-slots.md) §4 for deviations and results.
This covers phases (b), (c) and (d) of the [request slots proposal](2026-10-12-agent-request-slots-design.md).
Phase (a) is the [request lookups design](2026-10-13-agent-request-lookups-design.md), merged on 2026-10-30.

**Scope:** the agent core (`openepw.agent`): agent mode, guided mode, the CLI `openepw chat` and the
evals. The web chat in `web/chat-ui` still runs the legacy `/v1/chat` routes (`chat/coordinator.py`)
and is not changed. Moving it onto the agent core is P4 of the
[agent chat design](2026-10-05-mcp-agent-chat-design.md), which is not built and not one of the
seven phases. §6 defines the form data a P4 web renderer would read. External MCP clients, the MCP
server and `mcp/access.py` are not changed.

## 1. Owner answers this design builds on

From 2026-10-13 (proposal §6):
1. Years and product preference may be given before the location is approved; concrete offers
   come only after approval.
2. Lookups for a place that is not approved are allowed, with a label (built in phase a).
3. Any change to a part of the request resets the plan and its approval.
4. Text typed at an open form stays that form's answer, so phase (c) is Back for each part only.
5. Phase (a) first (done).
6. A spec and plan before code (this document).

From 2026-10-30, at the start of phase 3:
- **A question typed at an open form** still answers the form, but text that reads as a question
  is stored as *proposed*. The model answers it with a lookup and asks for confirmation before
  any plan. Plain answers are confirmed at once, as now.
- **"Can I get …" requests:** the model runs the lookup, says in words what is and isn't
  available, then opens the product form in the same turn if something fits.
- **Changing one part:** a request summary, shown in the plan review and on request, lists each
  part with its status and a Change action. Changing a part opens only that part's form. The
  step-by-step Back stays.

## 2. What this changes, from today's behaviour

| Today (`main`, 2026-10-30) | With this design |
| --- | --- |
| Years in any text count at once (`_note_years`); "What's available for 2018 here?" at the years form plans 2018 straight away (S55, live check 2026-10-27) | Years written in a question are *proposed*. Plans use confirmed years only, so the model must answer and get a confirmation first |
| "Can I get AMY 1950 in Austin?" goes straight to the product form (S50, live 3/3) | The instructions treat it as a lookup first, then the product form |
| A new place drops the chosen products (`Facts.set_geography`) | They are kept *to recheck*: the product form reopens with the ones still offered preselected |
| New years keep chosen products, but nothing rechecks their availability | Products still offered for the new years stay confirmed; products no longer offered become *to recheck* |
| Back undoes one step at a time; changing only the years means going back through every later step | A Change action per part, from the plan review or the request summary, reopens only that part's form |
| The model sees one facts list | It sees a table of parts with value, status and origin |
| Guided mode applies the same gates in a fixed order | It keeps the same parts, statuses, summary and Change actions, still with fixed rules |

## 3. The parts of a request

A request has four parts that the person sets, plus the plan derived from them:

| Part | Value (existing field) | Set by |
| --- | --- | --- |
| `place` | `geography`, `review`, `approved_key` | a place tool, the location review |
| `preference` | `product_type`, `provider` | the person's words ("AMY", "TMYx", "from NSRDB") or a filter the model passes to `choose_products` |
| `products` | `chosen` (offers with their `request`) | the product form only |
| `years` | `years` | the person's words, the years form, the request summary |
| plan (derived) | `plans` | `weather_plan` from confirmed parts only |

### 3.1 Status

Each part has one status, derived where possible so there is one source of truth:

| Status | Meaning | Reaches a plan? |
| --- | --- | --- |
| `empty` | nothing given | no |
| `proposed` | given, but not confirmed (a place not yet approved; years written in a question) | no |
| `confirmed` | approved on a form, or written plainly by the person | yes |
| `recheck` | was confirmed, but a change to another part means it must be shown again | no |

- **place:** `proposed` while the review is not approved; `confirmed` when `approved_key`
  matches the review key. Unchanged from today.
- **preference:** `confirmed` when the person wrote it; `proposed` when the model passed it as a
  filter without the person's words. A preference never reaches a plan directly (only chosen
  offers do), so its status is shown, not gated.
- **products:** `confirmed` when chosen on the product form; `recheck` after a place change, or a
  years change that removed one of them (§4).
- **years:** each year is confirmed or proposed. New field `Facts.proposed_years` (a subset of
  `years`); confirmed years are `years` minus `proposed_years`. A plan may use confirmed years only.

### 3.2 Origin

New field `Facts.origins: dict[part, {"by": "text" | "form" | "host", "seq": int}]`, the event that
last set the part. `text` means the person's own message; `form`, a form answer; `host`, derived
from the person's input by a tool, such as a single geocoder match for a typed name. The summary
shows it in words ("from your message", "chosen on the form"); the model sees it in the state
block. Origins are for display and audit only; no gate reads them.

### 3.3 Stored sessions

`Facts` gains `proposed_years: list[int] = []`, `origins: dict = {}` and `recheck: bool = False`
(products). Sessions saved before the change load with these defaults, which match today's
meaning: every year and choice confirmed. The `Model` base forbids unknown fields, so a session
saved by the new code cannot be read by older code. Rolling staging back after phase 4 would make
newer sessions unreadable; the agent README records this.

## 4. Changing one part resets only what depends on it

| Change | place | preference | products | years | plan and approval |
| --- | --- | --- | --- | --- | --- |
| New place | proposed (new review) | kept | `recheck`; offers refetched after approval; chosen ones still offered are preselected | kept | reset |
| New years | kept | kept | if confirmed: refetched for the new years; still offered → stay confirmed, else `recheck` | new value | reset |
| New preference | kept | new value | chosen ones that don't match → `recheck` | kept (unused if no actual-year product is left) | reset |
| New products | kept | kept | new value | kept | reset |

- "Still offered" means the same offer id is in the new offers. Its availability line comes from the
  new offers, so the plan review and the product form never show stale availability.
- Owner answer 3 is kept: any change resets the plan and its approval, and a new plan review is
  needed before Run.
- A new request (`/new`, "Start a new weather request") clears all parts, as today.
- `Facts.set_geography` stops clearing `chosen`; a new `Facts.change(part, value)` applies the
  table above in one place, and both policies call it.

## 5. Questions typed at a form (owner answer, 2026-10-30)

### 5.1 Reading text as a question

New host function `text.reads_as_question(text) -> bool`, deterministic and shared by both modes. It
is true when the text ends with "?", or starts with a question word or phrase: what, which, is,
are, does, do, can, could, would, will, how, when, where, any, is there, are there, do you have.
"2018", "2016-2018" and "2018 please" are answers; "2018?", "what about 2018" and "is 2018
available" are questions. A question that names no years leaves years unchanged.

### 5.2 Years in a question are proposed

`_note_years` (agent) and `_read_time_and_product` (guided) record years from a question as
proposed and years from other text as confirmed. A year written plainly later confirms it.
Lookups keep using every written year, proposed or not: they never feed a plan.

### 5.3 Agent mode

Text at an open form still closes it and goes to the model as the ask-tool's result (owner answer
4). The result gains the proposed years and a host hint:

```json
{"status": "person_replied", "text": "What's available for 2018 here?",
 "proposed_years": [2018],
 "next": "Answer the question with look_up_products, then confirm with review_request before weather_plan"}
```

If the model plans anyway, `check_plan_request` refuses with `GATE_REQUIRED`, need
`review_request`. This gate, not the hint, is the guarantee.

### 5.4 Confirmation

- **On a form that shows the value.** Answering a form whose text shows a proposed value
  confirms it. The product form's availability line already names the years ("For 2018. Listed:
  …"); choosing products on it confirms the years shown. So "Can I get AMY 1950 in Austin?"
  followed by a product choice needs no extra step.
- **On the request summary** (§6) when no such form follows, as in S55, where products were
  chosen before the question.

### 5.5 Guided mode

Guided mode reads the same function. It cannot answer questions in words, so the product form's
availability line remains its answer (today's S50 path). Proposed years are confirmed on the
product form or the request summary, as in agent mode.

## 6. Request summary and Change (phase c)

### 6.1 The summary form

New form kind `request_summary` (gate `review_request`):
- prompt "Is this your request?";
- `summary` lists one line per part with its value, status and origin;
- `data.parts` gives the same information as a list, for renderers: `{part, label, value, status,
  origin}`;
- answers: **approve** confirms every proposed value shown; choice `change:<part>` changes one
  part.

It opens:
- when a plan needs a part that is only proposed: new gate need `confirm_request`, returned by
  `next_need` after `choose_products` when actual-year products are chosen, no year is confirmed
  and some year is proposed. With no year written at all, the need stays `years`;
- on request: CLI `/request`; in agent mode the model's new ask-tool `review_request` (for "show
  me my request"); in guided mode, text such as "show my request" or "what have I chosen"
  (deterministic phrases).

### 6.2 Change actions on the plan review

The plan review keeps Run and adds the same part list, with `change:<part>` options. Run still
approves exactly the plans shown (`shows_current_plans`).

### 6.3 What Change does

Change is handled by the host in both modes, deterministically and without a model call:
1. The plan and its approval reset (owner answer 3).
2. In agent mode any pending ask-tool call is closed with
   `{"status": "person_changed", "part": "years"}`, so the model knows on its next turn.
3. The part's own form opens, with the current value shown or preselected:

| Part | Form |
| --- | --- |
| place | the "Where do you need weather?" map input, with the current place shown |
| preference | the product form, unfiltered (a typed preference also works) |
| products | the product form with the current choices preselected |
| years | the years form, with the current years in the hint |

4. When it is answered, §4 applies and the host continues in guided order: replan, then show the
   plan review. In agent mode the next typed message goes to the model as usual.

A Change answer also takes a snapshot, so the step-by-step Back still undoes it. Back is
unchanged in every other way. Back and Change are both refused after a job has started from the
current plans (`JOB_STARTED`), as Back is today.

### 6.4 Forms that do not block

Not built (owner answer 4). Text at a form stays its answer; §5 makes a question at a form safe
instead.

### 6.5 Renderers

- **CLI:** `render_form` lists the parts with their status for `request_summary` and
  `plan_review`; it reads "ok" (approve) and "change years" (also place, products, preference).
  New `/request` command; `/help` lists it.
- **Web (P4):** the summary and plan review cards render `data.parts` with a Change button per part.
  The fields are additive, so a renderer that ignores them still works.
- **Product form:** new `data.selected` (preselected offer ids) and `data.recheck` (a note that a
  change needs these chosen again). Renderers that ignore them show an unselected form, which is
  still correct.

## 7. "Can I get …" (owner answer, 2026-10-30)

The scope instructions change from "Do not open a form unless the person asks for files" to: for a
question about availability, *including a request phrased as a question* ("Can I get …", "Is there
… for …"), resolve the place, call `look_up_products`, say in one or two sentences what is and
isn't listed, then, if something fits and the person seems to want files, call `review_location`
in the same turn. Years in such a message are proposed (§5.2) and are confirmed by the product form
that shows them (§5.4).

This is an instruction, not a host gate: the host cannot reliably tell a polite request from a
question, and forcing a lookup could turn real requests into lookups. The phase (a) live check
showed this. The eval tracks the lookup as a soft check and the outcome (no plan from unconfirmed
years; the product form shows the years) as hard checks.

## 8. Guided-mode parity (phase d)

Guided mode keeps its fixed order and rules. It gains:
- the same parts, statuses and origins (it writes them through `Facts.change`);
- the question reading of §5.1 and proposed years;
- the `confirm_request` need and the request summary;
- Change actions on the plan review and the summary, through the same host path (§6.3);
- the targeted resets of §4. Today a typed product word in guided mode clears the chosen products;
  it will mark only the non-matching ones `recheck`.

It does not gain lookups in words or any model call. Guided mode stays deterministic: the same
inputs give the same forms.

## 9. What the model sees

The state block's facts lines become a parts table, for example:

```
Request parts (authoritative; plans use only confirmed parts):
- place: confirmed (key 3f…, 1 point: Ithaca, New York) · from the location review
- preference: actual year · from your message
- products: ERA5 (Open-Meteo) · confirmed on the product form
- years: 2018 proposed (from a question at the years form; confirm with review_request)
- plan: none
```

The `_RULES` text gains one sentence: proposed parts must be confirmed with `review_request` or a
form that shows them before `weather_plan`. `NEED_TOOL` gains `confirm_request → review_request`.

## 10. Unchanged guarantees

- Plans are built only from confirmed parts: the approved review, chosen offers and confirmed
  years (`build_requests`, `check_plan_request`).
- One approval answers one submission; Run approves exactly the plans shown.
- Host-only tools stay host-only; `weather_locations_review` and `weather_product_offers` stay
  hidden from the model.
- Guided mode stays deterministic.
- Lookups stay read-only and never feed a plan.
- Every input is moderated and guarded as today; Change and the summary are host forms with host
  text, so they need no model-output check.

## 11. Evals

- **Runner:** answers `request_summary` forms by the task's policy (`approve`, or `change:<part>`
  followed by that form's answer).
- **Grader:** new `part_status` (code `PART_STATUS`): a part ends with the given status; for
  example years `confirmed`, products `recheck`.
- **Changed tasks:**
  - S55: the summary form appears between the product choice and the plan review; years end
    confirmed; the lookup stays soft.
  - S50: years 1950 end proposed or confirmed only through the product form; no plan.
  - Tasks that check `forms_in_order` keep their checks; the summary appears only when a part is
    proposed, which none of them causes.
- **New tasks, agent and guided unless marked:**
  1. A question at the years form → lookup (agent, soft), summary, years confirmed, plan, Run.
  2. Change years from the plan review → place and products kept, new plan, Run.
  3. Change place from the plan review → years and preference kept, products `recheck`, product
     form preselected.
  4. New years that remove a chosen product → that product `recheck`; one still offered stays.
  5. Years and preference before the place → no product form before approval; the product form
     shows the years.
  6. "Can I get TMYx for Phoenix?" → lookup then location review in the same turn (agent; the
     lookup is soft).
  7. A plan attempt with only proposed years → `GATE_REQUIRED` `review_request`; nothing
     submitted (agent, scripted).
  8. `/request` at any point shows the summary; approving it with nothing proposed changes nothing.
  9. An old saved session (fixture without the new fields) loads and plans as before (unit test).
- **Live check** in phase 4, within the owner's cap (suggested $1): tasks 1, 2, 6, S50 and S55, 3
  trials each under the hosted profile.

## 12. Cost and risk

- Model cost: one more model step when a question at a form leads to a summary, and one lookup
  step for "can I get" requests. In the 2026-10-27 live check a whole task cost about $0.003
  ($0.05 for 18 trials), so an extra step is a fraction of that. Change costs nothing, as the host
  handles it.
- Risk: models may still plan straight away. The gate refuses this, so the worst case is one
  wasted model step and a repair.
- Risk: the question words could misread an answer such as "Is 2018 OK" as a question. The result
  is only an extra confirmation, never a wrong plan.
- Risk: the new `Facts` fields make a staging rollback unable to read newer sessions (§3.3).

## 13. Documentation

ADR 0005 gains a note: the request summary form, the `review_request` ask-tool, the
confirmed-parts rule for plans, and Change as a host path in both modes. The agent README (forms,
gates, CLI commands, evals), ARCHITECTURE, FEATURES, limitations (P4 still needed for the web) and
the proposal's status line are updated in phase 4.

## 14. Open questions for the owner

Each has a default that phase 4 will use unless the owner says otherwise.

1. **Confirmation on a form that shows the value (§5.4).** Default: choosing products on a form
   that shows the proposed years confirms them, so "Can I get AMY 1950 in Austin?" needs no extra
   step. The alternative, always asking on the summary, is stricter but adds a step to a common
   phrasing.
2. **Products still offered after new years (§4).** Default: they stay confirmed and the plan
   review shows their new availability. The alternative is always `recheck`.
3. **Change runs without the model (§6.3).** Default: yes, in both modes. It is deterministic and
   free, and the model learns of it on its next turn.
4. **P4.** The web chat shows none of this until the agent core is hosted in the web chat (P4).
   Should P4 become a phase of the outstanding work plan? This affects scope, not this design.
