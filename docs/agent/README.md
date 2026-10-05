# Agent chat core (guided mode)

`openepw.agent` is one conversation core for the CLI and (from P4) the web chat. It is a real
MCP client of the local openepw server over the SDK's in-memory transport and never calls the
weather service directly.

## Run it

```powershell
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat
.venv/Scripts/openepw.exe --data-root C:\path\to\data chat --session <id>
```

One process runs jobs for a data root: stop `openepw serve` or use another data root
(`DATA_ROOT_BUSY` otherwise). Commands: `/back`, `/new`, `/upload <path>`, `/status`, `/mode`,
`/help`, `/quit`. Sessions are saved in `<data root>/agent/sessions.sqlite`; an unknown
`--session` ID is reported as `SESSION_NOT_FOUND`.

After a run starts, the chat follows the jobs for up to two minutes at a time, then gives the
prompt back (press Enter to keep following; `/status` lists the jobs). Jobs run in this process:
`/quit` or Ctrl-C waits for a running job to finish, and its outputs stay in the data root.
`/upload` refuses files over 5 MB before reading them.

## Forms and gates

Every step is a typed form (`text`, `choice`, `location_review`, `product_choice`, `map_input`,
`upload`, `plan_review`). Guided mode asks them in the gate order: place → location review
(with fixed standard-time offsets) → products → years (actual-year only) → plan review → run →
job progress → next steps (charts, compact ZIP, new request). Plans are built by the host from
the approved review, chosen offers and the years the person wrote; a model-supplied plan request
(P3) is rewritten the same way. "Run" submits only the plans the open review shows: any change
(years, products, place) replans and reopens the review first. Each plan approval answers
exactly one submission confirmation,
and an approval is dropped if the submission fails before the server asks. Future weather stays
suspended (scenario names such as SSP5-8.5, RCP 4.5 or CMIP6 get the suspension message).
Retrieved EPWs are not certified simulation-ready.

Back restores the facts captured when an earlier form was shown, but never crosses a started
job, and keeps uploaded or retrieved EPW artifacts. An unexpected failure during a turn keeps
the open form and shows `INTERNAL_ERROR` with a correlation id that is logged locally; the
exception text is not shown.

## Modes

P2 ships guided mode only (rule-based forms, offline text reading). Agent mode with a
tool-calling model arrives in P3 with the same forms and gates.
