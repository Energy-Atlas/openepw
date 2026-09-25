# Production MCP — staged design discussion

Date: 2026-09-23. Branch: `feature/mcp`.

Historical design discussion. Its earlier Stage 2 approval wording and proposed
real-user/LangSmith pilot details are superseded by the [owner-clarified coordinated
plan for Stages 3a–6](../plans/2026-09-25-mcp-remaining-stages.md). Stage 2 has been
implemented; the remaining plans await one final approval. This document is
retained as design history, not as the current execution contract.

Status updated 2026-09-24: the owner explicitly accepted MCP Stage 1 as finished
and agreed to advance to Stage 2. A detailed Stage 2 design and implementation
plan have since been drafted for review; no new public API or Stage 2 implementation
has been approved. The owner also inserted an agent-harnessing stage before the
local pilot and removed self-hosted team deployment from this roadmap. Stages 3–6
remain proposals. These MCP stages are separate from the completed v0.1 stages.

Read the [Stage 2 agent handoff](../../handoffs/2026-09-24-mcp-stage-2.md),
[accepted decisions](../../decisions/0003-mcp-availability-and-batches.md), and
[Stage 1 findings](../../validation/mcp-stage-1/README.md). Research and accepted
case annotations are complete; production catalog integration is the next phase.
The [program plan](../../plans/2026-09-24-production-mcp-program.md) is the current
cross-stage allocation draft; this document retains the earlier stage discussion.

## Intended outcome

An LLM client can explain suitable datasets, discover actual alternatives, plan and
retrieve EPWs, generate future weather from local or retrieved baselines, and manage
batches with useful partial results. A purpose-built agent harness then helps the
client carry out and explain those workflows; a local pilot tests the result with
users. Scientific provenance, QC and limitations remain visible throughout. Python
is canonical; MCP is a thin adapter; the harness sits above the MCP contract.

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

The accepted Stage 1 baseline is sufficient for current planning. Another agent is
improving NSRDB and other availability evidence on a separate branch and worktree.
Treat that as a later reviewed snapshot, not a restart of this stage or a reason to
discard the accepted annotations and local evidence. Stage 2 can import a new
accepted snapshot generation when that work is ready.

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
Evaluate geographic and temporal coverage together. Show when multiple input
locations may resolve to one station/source, but leave scientific retrieval
equivalence and output mapping to Stage 3a.

Primary areas: a focused availability package, provider discovery, domain models,
WeatherService and provider/method documentation. Avoid a broad service refactor.

Acceptance: deterministic synthetic inventories cover geographical boundaries,
station date gaps/overlaps, stale catalogs, variable omissions and unsupported
future combinations. Fresh local metadata avoids unnecessary provider calls;
unknown cases remain visible. Python and adapter callers receive the same facts.

## Stage 3a — complete weather-fetch planning, batch and artifact workflows (proposed)

Use the program plan's two weather-fetch anchor requests, each using one or a few
sources, to exercise product, geography, temporal and batch differences. Track
which combinations they cover; use offline variants for additional cases rather
than an exhaustive live matrix. Resolve all requested sites, preserve the full
request-to-source mapping, group
scientifically equivalent retrievals, and continue supported locations. Report
unsupported, shared-source, failed and successful results distinctly. Preserve
per-location output identities and add explicit compact export with a mapping table.
Do not silently truncate periods or relocate native station metadata.

Define plan references so clients can execute the inspected plan without repeatedly
transmitting a large plan document. Keep existing plan integrity, durable jobs,
cancellation and failed-output retry.

Primary areas: planning, service, artifacts, jobs and shared wire contracts.

Acceptance: many sites sharing a source retrieve it once when equivalence is known;
every input occurrence remains traceable. Different adjustments do not collapse.
Partial coverage and restart/retry work with synthetic data. Compact export and
per-site export express the same scientific mappings.

## Stage 3b — complete future-weather workflows (proposed)

Complete baseline ingestion for both a user-provided local EPW and an EPW fetched
through OpenEPW. Carry each through inspectable future plans, execution and
artifacts while retaining baseline identity, scenario/window meaning, provenance,
warnings and QC. Both distinct future methods keep their source-dependent limits.
Use the program plan's third anchor request to exercise both baseline paths and a
supported versus unsupported scenario/window choice.

Primary areas: future planning, baseline/artifact handling, service and job
integration. Acceptance: both baseline paths produce traceable outputs; unsupported
combinations and partial failures remain explicit. Stage 4 can expose the same
workflows without implementing future-weather logic inside MCP.

## Stage 4 — deliver the local MCP contract (proposed)

Expose the shared services with useful input/output schemas, concise descriptions,
machine-readable errors, compact summaries and artifact references. Cover guidance,
geography parsing/geocoding and guided discovery, plan creation/execution,
baseline ingestion, job inspection/cancellation/
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

## Stage 5 — agent harnessing design and reference implementation (proposed)

Design an agent layer that makes the MCP workflows usable from a natural-language
request. It should choose and sequence tools, preserve the user's study intent,
explain alternatives and uncertainty, track long-running jobs and artifacts, and
ask for clarification when a scientific or operational choice materially changes
the result. Keep provider and weather science in the Python service, not in prompts
or agent-specific tools.

Build a small reference harness, even if its first role is testing and evaluation.
Evaluate a lightweight implementation against frameworks such as LangChain and
LangGraph; LangSmith or another tracing/evaluation system may help inspect runs.
Those are candidates, not required dependencies or settled architecture. Keep the
harness optional so direct Python and MCP clients remain usable. Define test tasks,
trace/redaction rules and measures for correct tool choice, explanation, recovery
and bounded resource use before selecting a stack.

Exit condition: the reference harness can drive the main local workflows through
MCP with inspectable traces and deterministic evaluations, including ambiguity,
unsupported locations, provider failures and QC/provenance explanations. This
provides a concrete client for the pilot without claiming general agent reliability.
Reuse Stage 3's representative request families as evaluation anchors.

## Stage 6 — local pilot and release acceptance (proposed)

Run the Stage 3 representative requests and selected variants through the reference
harness and target LLM client: purpose-based dataset guidance, geography interpretation,
native and actual-year EPWs, both baseline-to-future paths, and
batches with shared sources/unsupported locations/partial failures. Check whether
tool results let the LLM explain choices, geographical/temporal limits and QC.

Use deterministic offline tests for breadth and a small opt-in live acceptance
matrix for representative integrations. Do not repeat Stage 1 as an exhaustive
network test. Record real client/platform/provider results and outstanding limits.
Verify package extras, startup instructions and shared-service parity.

Exit condition: the agreed local workflows pass, material defects are resolved,
and residual limitations are documented. The current staged roadmap ends at local
acceptance. A team-deployment stage would require a separate future owner decision.

## Future feature — accelerate requests using previous runs

Index verified prior outputs and QC summaries for safe cross-run reuse. This is
advanced work outside Stage 1 and is not a prerequisite for the initial local
release. Define identity, freshness, invalidation and user-visible reuse evidence
before implementing it. Preserve existing raw caches and durable job recovery.

## Design questions to settle while refining later stages

- Stage 2: which study-purpose preferences should recommendations accept explicitly?
- Stage 3: which local directories and export destinations may the MCP server access?
- Stage 5: which harness tasks and evaluation criteria best represent intended users,
  and does a framework improve them enough to justify the added dependency?
- Stage 6: which LLM client(s), users and operating systems define local acceptance?

Resolve these in the stage designs before producing executable task-level plans.
Routine implementation choices follow the repository's existing autonomy rules.
