# MCP availability research

This is research tooling outside the installed OpenEPW package. It does not alter
production provider discovery or imply live weather acceptance. Use the project's
Python environment (`.venv/Scripts/python.exe` on this Windows checkout).

```powershell
.venv/Scripts/python.exe scripts/probe_mcp_availability.py plan
.venv/Scripts/python.exe scripts/probe_mcp_availability.py collect --only noaa-history
.venv/Scripts/python.exe scripts/probe_mcp_availability.py analyze
.venv/Scripts/python.exe scripts/probe_mcp_availability.py report
```

`plan` does not write or connect. `analyze` and `report` only read local snapshots
and write derived local JSON/Markdown. `collect` requires explicit IDs. Default
root is ignored `.local/mcp-availability/`; preserve it to resume the same study.
Do not change roots to evade the investigation's request budget.

Additional requests are explicit JSON arrays of `Request` fields, supplied through
`--manifest`. The executed follow-up manifest is published with the report. Never
place real credentials in a manifest; the investigation uses public metadata only.
The only allowed extra headers are `Range`, `If-Match`, and `Accept`. A request ID
is immutable. Failed attempts are not automatically repeated. One justified
revision may use a new ID with `revision_of` and `correction`; a rate-limit block
still takes precedence.

The collector holds an OS file lock across a serial collection run. Before network
I/O it atomically reserves one request and the remaining response byte allowance.
A crashed request retains that conservative reservation. Saved metadata can be
reused without network I/O; analysis verifies each snapshot checksum. Do not edit
the ledger or treat a crashed reservation as permission to start over.

Limits are those in the approved Stage 1 plan. Per-provider caps include redirect
hops. One timeout covers a selected request and its redirects/host-spacing waits;
individual HTTP operations also have a 30-second timeout. Rate limits persist as
provider blocks, with numeric Retry-After retained when supplied. Exceptions and
HTTP error bodies are not persisted. Only bounded successful bodies are snapshots.

Byte budgets measure application-consumed response bytes, not TCP/TLS overhead or
transport prefetch. Unknown-length responses exactly at the allowance are rejected
conservatively rather than reading beyond the cap to distinguish EOF. Interrupted
requests may leave pessimistic charges. Never edit the ledger to reclaim them.

The offline ZIP helper parses classic/ZIP64 directory locations and central
directory names. It never reads or decompresses an EPW member. Use the tail's ETag
in the explicit directory request's `If-Match`; reject ignored or changed ranges.

The default analysis computes seven-variable coherent CMIP6 intersections for the
four SSP scenarios accepted by the current adapter. It does not verify actual time
coordinates, numeric data, license eligibility for every combination, or all
upstream experiments. Normalized inventories remain local; `report` emits counts,
selected metadata and a sanitized ledger without station dumps/hourly tables.

Run offline safeguards with:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_availability_research.py -q
.venv/Scripts/python.exe -m ruff check scripts/mcp_research scripts/probe_mcp_availability.py tests/unit/test_mcp_availability_research.py
```

See the [findings](../../docs/validation/mcp-stage-1/README.md) for the actual
investigation, limitations and Stage 2 contract.
