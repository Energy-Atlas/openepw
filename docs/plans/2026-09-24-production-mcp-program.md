# Production MCP program plan

Status: draft for owner discussion, 2026-09-24. This allocates features, work areas and deliverables across the production MCP stages. It is not an implementation design or authorization to begin Stage 2 implementation. These stage numbers are separate from the completed v0.1 stages.

## Program outcome

A local user can ask for suitable weather data, understand the alternatives and their limits, retrieve or generate an EPW, and manage a batch through an MCP-connected agent. The result remains traceable to source evidence, request choices, QC and artifacts. The current program ends with a validated local pilot. Team deployment and previous-run weather/QC reuse are outside it.

## Stage allocation

### Stage 1 — availability evidence (accepted baseline)

- **Work area:** Document provider/product footprints, stations and sites, temporal availability, future scenarios/windows, access requirements and unresolved cases from bounded authoritative evidence.
- **Deliverables:** Versioned source register, sanitized evidence ledger, local metadata snapshots, availability matrix, accepted OneBuilding case annotations and catalog handoff.
- **Completion:** The 2026-09-24 baseline is accepted and sufficient for Stage 2. Its uncertainties remain explicit; availability evidence does not certify complete weather or EPW quality.
- **Parallel follow-up:** Another agent is improving NSRDB and other evidence on a separate branch/worktree. Review those findings separately and add accepted changes as a new snapshot. This does not reopen Stage 1 or block Stage 2 planning.

### Stage 2 — shared availability and recommendation services (plan under review)

- **Work area:** Turn the accepted evidence into a local catalog and shared service that answers where, when and for what purpose a product or future method is an eligible choice.
- **Features:** Show supported, excluded and unknown outcomes with reasons; keep source coverage, current adapter support, access requirements and provider health distinct; explain recommendations while retaining alternatives.
- **Deliverables:** Typed Python service results, locally usable metadata snapshots and refresh behavior, provider/method limitations, and deterministic evidence-based acceptance tests. REST/MCP adapters may expose shared facts, while Stage 4 owns the final client-facing tool contract.
- **Handoff to Stage 3:** A request can inspect credible candidate choices before planning. Catalog evidence is never treated as proof of complete hourly data or simulation fitness. The detailed [Stage 2 design](../superpowers/specs/2026-09-24-mcp-stage-2-availability-design.md) and [implementation plan](../superpowers/plans/2026-09-24-mcp-stage-2-availability.md) remain proposals for review after this program allocation is settled.

### Stage 3 — complete planning, batches and artifacts (proposed)

- **Work area:** Carry a selected source through an inspectable plan, execution, jobs and artifacts for one location or many, including future generation from a local or retrieved baseline.
- **Features:** Preserve every requested occurrence and its source/output mapping; reuse only scientifically equivalent retrievals; continue supported locations while reporting unsupported and failed ones; offer explicit compact export alongside the existing per-location default.
- **Deliverables:** End-to-end batch and baseline workflows, clear partial-result summaries, artifact references and mapping records, plus offline tests for retry, restart, missing coverage and shared sources.
- **Handoff to Stage 4:** The service can complete the user workflows without an MCP-specific algorithm or a manually reconstructed plan.

### Stage 4 — local MCP contract (proposed)

- **Work area:** Present the Stage 2–3 services to a local MCP client through understandable tools, resources and errors.
- **Features:** Guidance, discovery, planning, execution, future generation and job/artifact inspection have compact, typed results; long-running work remains inspectable after a client disconnects.
- **Deliverables:** A local stdio MCP server contract, client setup examples, protocol-level tests and a documented list of supported workflows and limits. This stage decides final tool boundaries and names.
- **Handoff to Stage 5:** A real MCP client can run the core workflows and retrieve artifacts without receiving bulk hourly data in ordinary tool responses.

### Stage 5 — agent harnessing and evaluations (proposed)

- **Work area:** Design an agent layer above MCP that turns user intent into sensible tool sequences and explains choices, uncertainty, failures and QC.
- **Features:** A reference agent handles clarification, plan review, job progress, artifact follow-up and recovery across representative workflows. It does not reimplement provider selection or weather science.
- **Deliverables:** Harness design, a runnable reference agent, representative evaluation tasks, redacted traces and a short stack decision. Compare a small direct implementation with LangChain/LangGraph; consider LangSmith or another evaluation tool only if it improves the work. None is a required core dependency by default.
- **Handoff to Stage 6:** The reference agent reliably completes the selected local tasks under deterministic evaluation and exposes its decisions for review. Direct Python and MCP use remain available without it.

### Stage 6 — local pilot and release acceptance (proposed)

- **Work area:** Exercise the integrated product with the target LLM client, reference harness and representative users on realistic local tasks.
- **Features:** Pilot dataset guidance, actual and published EPWs, both future-baseline paths, and batches with shared sources, unsupported locations and partial failures. Check whether users can understand provenance, uncertainty and QC from the returned evidence.
- **Deliverables:** Recorded client/platform/provider results, a small opt-in live acceptance matrix, resolved material defects, installation guidance and an honest limitations/release report.
- **Completion:** The agreed local stories work end to end and remaining limitations are documented. No remote team-service acceptance is implied.

## Workload boundaries and sequence

The main path is **evidence → shared guidance → complete workflows → MCP interface → agent harness → local pilot**. Stage 1's separate evidence follow-up may proceed alongside Stage 2; it joins only after review and should not cause broad recollection or overwrite accepted annotations. Stages 2–3 carry the main Python service and workflow workload. Stage 4 concentrates on protocol and client usability, Stage 5 on agent behavior and evaluation, and Stage 6 on user acceptance and documentation. Each later stage receives its own scoped design and implementation plan when it is ready; this program plan does not choose implementation strategies or framework dependencies.

Across stages, the Python package remains canonical, and MCP and the harness consume its facts. Preserve actual-year, TMY-reference and future-window meanings, per-variable provenance, requested-location identity, source coordinates and visible uncertainty. Do not silently switch providers, shorten periods, claim that availability proves weather quality, or promote a syntax-valid EPW to simulation-ready.

After owner review of this allocation, revisit the existing detailed Stage 2 plan against the agreed Stage 2 boundary. Stage 2 implementation still requires its plan review.
