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

`analyze` records the ledger checksum and saved raw-source checksums inside local
`analysis.json`. Full catalog import verifies these fingerprints and requires a
fingerprinted analysis. If an older analysis lacks them, preserve a local copy,
then rerun `analyze` offline; this does not recollect metadata. If no local
analysis is available, ordinary availability queries use bundled source contracts
and leave inventory-dependent answers unknown.

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

Limits are those in the approved Stage 1 plan, plus a later owner-authorized 20 MB
exception for the exact NOAA `www.ncei.noaa.gov/pub/data/noaa/isd-inventory.csv`
inventory endpoint. The 200 MB overall ceiling and all prior charges remain unchanged.
This is not a general NOAA limit increase. Per-provider caps include redirect
hops. One timeout covers a selected request and its redirects/host-spacing waits;
individual HTTP operations also have a 30-second timeout. Rate limits persist as
provider blocks, with numeric Retry-After retained when supplied. Exceptions and
HTTP error bodies are not persisted. Only bounded successful bodies are snapshots.

The owner also approved a 7 MB cumulative extension for each exact OEDI scenario
archive URL (RCP4.5_v1.1.zip / RCP8.5_v1.1.zip at data.openei.org/files/5974), giving
17 MB per archive including earlier failed transfers. Other archives keep 10 MB;
the overall 200 MB limit is unchanged. Revised requests retain If-Match/Range checks.

Coordinate research parses the source's linked XLSX first sheet using the standard
library with a 40 MB expanded-workbook bound. It never executes formulas or follows
external relationships. Exact product URL matches use published index coordinates;
NOAA fallback matches require station identifier, country and name agreement.
Ambiguities remain unknown. No EPW header verification or place geocoding is implied.

Byte budgets measure application-consumed response bytes, not TCP/TLS overhead or
transport prefetch. Unknown-length responses exactly at the allowance are rejected
conservatively rather than reading beyond the cap to distinguish EOF. Interrupted
requests may leave pessimistic charges. Never edit the ledger to reclaim them.

The offline ZIP helper parses classic/ZIP64 directory locations and central
directory names. It never reads or decompresses an EPW member. Use the tail's ETag
in the explicit directory request's `If-Match`; reject ignored or changed ranges.

The default analysis computes seven-variable coherent CMIP6 intersections for the
four SSP scenarios accepted by the current adapter. It also joins the saved WCRP
registry by model once and records effective-license allow-list status for every
listed combination. A missing or unrecognized registry license stays unknown.
This does not verify original terms in unsampled stores, actual time coordinates,
numeric data, or all upstream experiments. See the [offline license-scope
addendum](../../docs/validation/mcp-stage-1/cmip6-license-scope.md). Normalized
inventories remain local; `report` emits counts, selected metadata and a
sanitized ledger without station dumps/hourly tables.

Run offline safeguards with:

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_mcp_availability_research.py -q
.venv/Scripts/python.exe -m ruff check scripts/mcp_research scripts/probe_mcp_availability.py tests/unit/test_mcp_availability_research.py
```

See the [findings](../../docs/validation/mcp-stage-1/README.md) for the actual
investigation, limitations and Stage 2 contract.

The 2026-09-24 approval permits cumulative OneBuilding attempts 13–15 only for the
three exact coordinate-index IDs/URLs in the approved follow-up manifest. Ordinary
responses remain 5 MB; redirects count against the same allowance. No other
OneBuilding URL receives this extension. `plan` displays the exception.

Coordinate records distinguish horizontal position, elevation and NOAA identity.
Exact-coordinate consensus never selects an arbitrary WBAN or averages elevations.
Raw AU codes remain ambiguous; published product URLs provide independent evidence.
`coordinate-baseline.json` under the local research root stores the prior metadata
matcher output and source checksums for reproducible transition accounting. Retain
it with snapshots; do not overwrite it with weather runs or newer analysis. Without
that file current coordinates can still be analyzed, but no before/after claims
are generated. Full unresolved rows and transition details stay local.

Accepted individual judgments live in `data/onebuilding_reviews.json`. `reviews.py`
attaches them only to explicitly listed product URLs with matching source checksums.
The original automatic record is preserved. Reviewed metadata coordinates,
approximate locality points and name/code conflicts are distinct statuses. No
annotation claims verified EPW coordinates, archive-byte equivalence or permission
to substitute weather. New/changed metadata requires renewed review, not automatic
reuse of a previous judgment. Missing evidence leaves annotations stale/unresolved.
