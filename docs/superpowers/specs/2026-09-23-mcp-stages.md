# Production MCP — staged design discussion

Date: 2026-09-23. Branch: `feature/mcp`.

Status updated 2026-09-24: the owner explicitly accepted MCP Stage 1 as finished
and agreed to advance to Stage 2. The next deliverable is the detailed Stage 2
design and implementation plan, as discussed immediately before that acceptance.
This authorizes the transition and planning; no detailed Stage 2 implementation
plan or new public API has yet been approved. Stages 3–6 remain proposals. These
MCP stages are separate from the completed v0.1 implementation stages.

Read the [Stage 2 agent handoff](../../handoffs/2026-09-24-mcp-stage-2.md),
[accepted decisions](../../decisions/0003-mcp-availability-and-batches.md), and
[Stage 1 findings](../../validation/mcp-stage-1/README.md). Research and accepted
case annotations are complete; production catalog integration is the next phase.

## Intended outcome

An LLM client can explain suitable datasets, discover actual alternatives, plan and
retrieve EPWs, generate future weather from local or retrieved baselines, and manage
batches with useful partial results. Local deployment is validated first; self-hosted
team deployment follows successful local acceptance. Scientific provenance, QC and
limitations remain visible throughout. Python is canonical; MCP is a thin adapter.

## Stage 1 — map availability with bounded investigation (accepted scope)

Use footprints, station/site inventories, operating periods, published-product
reference periods, and future scenario/model/window metadata. Download catalogs
once where practical; select a small set of strategic location/year probes only
to answer documented uncertainties. No exhaustive API sampling. Previous-run
results and QC summaries are excluded; advanced cross-run reuse is deferred.

Deliverables: an availability matrix and source register; evidence dates and
versions; a bounded probe ledger; explicit unknowns; and a local metadata catalog
and refresh proposal. The exit condition is enough defensible evidence to implement
eligibility checks, with remaining uncertainty represented explicitly rather than
an assertion of comprehensive live coverage.

## Stage 2 — shared availability and recommendation services (design/planning authorized)

Build the local metadata catalog and provider-specific import/refresh paths from
Stage 1 findings. Support local filtering before remote calls, freshness reporting,
and bounded refresh for missing/stale information. Unknown or stale data must not
be treated as definitive absence. Keep credentials and transient outages separate
from scientific availability.

Return typed eligibility and suitability evidence by location, period and dataset:
compatible products/variables, source resolution/distance, exclusions, uncertainties,
access requirements and recommendation reasons. The LLM explains these facts in
the context of the user's purpose; it does not invent availability or a universal
quality score. Future method capabilities belong in the same discovery workflow.

Primary areas: a focused availability package, provider discovery, domain models,
WeatherService and provider/method documentation. Avoid a broad service refactor.

Acceptance: deterministic synthetic inventories cover geographical boundaries,
station date gaps/overlaps, stale catalogs, variable omissions and unsupported
future combinations. Fresh local metadata avoids unnecessary provider calls;
unknown cases remain visible. Python and adapter callers receive the same facts.

## Stage 3 — complete planning, batch and artifact workflows (proposed)

Resolve all requested sites, preserve the full request-to-source mapping, group
scientifically equivalent retrievals, and continue supported locations. Report
unsupported, shared-source, failed and successful results distinctly. Preserve
per-location output identities and add explicit compact export with a mapping table.
Do not silently truncate periods or relocate native station metadata.

Complete baseline ingestion for local EPWs and retrieved artifacts, using bounded
file access and the shared artifact store. Define plan references so clients can
execute the inspected plan without repeatedly transmitting a large plan document.
Keep existing plan integrity, durable jobs, cancellation and failed-output retry.

Primary areas: planning, service, artifacts, jobs and shared wire contracts.

Acceptance: many sites sharing a source retrieve it once when equivalence is known;
every input occurrence remains traceable. Different adjustments do not collapse.
Partial coverage, restart/retry and both baseline paths work with synthetic data.
Compact export and per-site export express the same scientific mappings.

## Stage 4 — deliver the local MCP contract (proposed)

Expose the shared services with useful input/output schemas, concise descriptions,
machine-readable errors, compact summaries and artifact references. Cover guidance,
discovery, plan creation/execution, baseline ingestion, job inspection/cancellation/
retry and exports. Decide final tool boundaries during design; do not assume the
existing six names or untyped dictionaries are the complete production interface.

Use stdio for the first local rollout. Define local file-access boundaries,
configuration, lifecycle and logs that do not corrupt protocol output. Keep bulk
EPW bytes out of ordinary tool results. Inspect current official SDK/protocol
documentation before selecting protocol-specific features. Preserve WeatherJob as
the canonical job model, including when clients disconnect.

Primary areas: mcp/server.py and focused MCP support modules, CLI launch/configuration,
installation/client examples and transport tests. No weather algorithms in MCP.

Acceptance: an actual MCP client session negotiates and lists tools/resources,
performs the selected workflows, reads structured failures and accesses artifacts.
Test protocol behavior, not only direct Python tool calls. Exercise invalid input,
path confinement, bounded output, process shutdown and credential redaction.

## Stage 5 — local pilot and release acceptance (proposed)

Run the selected user stories through the first target LLM client: purpose-based
dataset guidance, native and actual-year EPWs, both baseline-to-future paths, and
batches with shared sources/unsupported locations/partial failures. Check whether
tool results let the LLM explain choices, geographical/temporal limits and QC.

Use deterministic offline tests for breadth and a small opt-in live acceptance
matrix for representative integrations. Do not repeat Stage 1 as an exhaustive
network test. Record real client/platform/provider results and outstanding limits.
Verify package extras, startup instructions and shared-service parity.

Exit condition: the agreed local workflows pass, material defects are resolved,
and residual limitations are documented. This evidence is a prerequisite for the
self-hosted team release; local success alone is not remote security acceptance.

## Stage 6 — self-hosted team MCP (proposed, after local acceptance)

Add authenticated Streamable HTTP and deployment documentation. Define team access
to jobs/artifacts and provider credentials, transport security, request/workload
limits, concurrency and process ownership, logging and storage/retention behavior.
Do not assume the existing REST bearer token alone satisfies the selected MCP
clients' authentication requirements. Verify compatibility against current official
protocol/client documentation when this stage is designed.

Prefer the existing SQLite/filesystem service within its single-process limits.
Avoid introducing distributed services unless requirements demonstrate a need.
Decide whether local clients connect to a shared running service to prevent multiple
workers competing for one data root.

Acceptance: selected remote clients authenticate successfully; unauthorized access
is rejected; the agreed sharing/isolation policy is enforced; concurrent users,
disconnects and restart recovery respect resource limits and preserve jobs.

## Future feature — accelerate requests using previous runs

Index verified prior outputs and QC summaries for safe cross-run reuse. This is
advanced work outside Stage 1 and is not a prerequisite for the initial local
release. Define identity, freshness, invalidation and user-visible reuse evidence
before implementing it. Preserve existing raw caches and durable job recovery.

## Design questions to settle while refining later stages

- Stage 2: which study-purpose preferences should recommendations accept explicitly?
- Stage 3: which local directories and export destinations may the MCP server access?
- Stages 4–5: which LLM client(s) and operating systems define first acceptance?
- Stage 6: shared trusted-team workspace, or per-user job/artifact isolation; shared
  or per-user provider credentials; and compatible authentication approach?

Resolve these in the stage designs before producing executable task-level plans.
Routine implementation choices follow the repository's existing autonomy rules.
