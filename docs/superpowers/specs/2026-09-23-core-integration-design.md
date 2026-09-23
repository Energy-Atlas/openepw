# Core Integration and Output Identity Design

**Status:** Proposed for owner review on 2026-09-23.

## Purpose

Extract reusable Python, planning, provider and durable-job improvements from
`feature/webui` into `main` without treating the frontend branch as the source of
truth for the package. Correct the output-identity defect before multi-dataset
planning becomes a stable shared contract, give generated EPWs meaningful names,
then reconcile the UI branch and start future MCP work from the corrected `main`.

Success means:

- provider fetch tasks may still be deduplicated across requested locations;
- every planned output mapping has a distinct stable identity;
- every emitted EPW has a deterministic, human-readable, collision-safe filename;
- job totals, retries, manifests and artifacts use output identity rather than
  assuming filenames or fetch-task identities are output identities;
- selecting a station-backed dataset resolves the appropriate station per point
  instead of applying every discovered station ID to every point;
- independent correctness fixes are available to Python, CLI, REST and MCP through
  the canonical service layer;
- `feature/webui` consumes the corrected core after `main` is merged into it; and
- `feature/mcp` starts from the corrected `main`, not from the UI feature branch.

## Scope

### Included independent fixes

The main-based integration keeps these behaviorally independent improvements from
`feature/webui`, with their tests:

1. close SQLite connections after every transaction;
2. persist completed and failed output counts while a job is running;
3. recover and expose weather/future job kind from the stored plan;
4. allow bounded provider-specific HTTP retry overrides so NSRDB discovery does
   not sleep through repeated rate-limit retries;
5. expose the full ranked candidate list per requested location; and
6. allow sampled area points to use an explicit longitude-based nominal standard
   offset while retaining UTC as the Python/API default.

Failed-output retry is included only after the new output identity is in place.
Retrying must select missing output identities, retain prior successful artifacts,
and never use a filename as the authoritative key.

### Deferred UI-specific work

Static UI hosting, browser CI, generated TypeScript contracts, map coverage
overlays, frontend workflow state and UI documentation remain on `feature/webui`.
The current hard-coded world coverage polygons are not promoted to `main` as
factual data availability.

Artifact preview/visualization and REST job pagination are useful general
capabilities, but they are not prerequisites for output identity or MCP work. They
remain on `feature/webui` for a later deliberate integration unless required by a
corrected shared contract during implementation.

## Output identity

`FetchTask.id` identifies one provider retrieval and remains reusable by several
requested locations. It must not identify an output.

`OutputSpec` gains an optional `id` field. New plans always set it to a deterministic
digest of the complete output mapping:

- requested location ID;
- ordered task IDs;
- selected provider, dataset and product when applicable;
- requested period; and
- output transformation/profile identity where applicable.

The field is optional only for persisted legacy plans. Legacy plans continue to use
their filename as their internal job-item key so their existing hashes validate and
their completed items remain resumable. New plans require unique output IDs and
unique filenames.

Job storage may retain the existing SQLite `items.name` column for compatibility,
but its application-level meaning becomes `output_key`: `OutputSpec.id` for new
plans and `OutputSpec.name` for legacy plans. Job totals, worker deduplication,
resume, progress, failed-output retry and bundle assembly all use that key.

## Semantic EPW filenames

Filename generation belongs in a small Python planning module and is shared by
historical and future planning. Names remain deterministic, ASCII, filesystem-safe,
and within `OutputSpec`'s 100-character limit.

Historical names contain:

```text
openepw-{location}-{provider}-{dataset}-{product-or-source}-{period}-{suffix}.epw
```

Future names contain:

```text
openepw-{location}-{method}-{scenario}-{profile}-{window}-{member}-{suffix}.epw
```

Rules:

- a named location uses a normalized name plus a compact coordinate token;
- an unnamed sampled location uses the coordinate token;
- a full requested year uses `YYYY`; a date interval uses
  `YYYYMMDD-YYYYMMDD`; published products use their explicit product label;
- station identity is included when the resolved source is station-backed;
- ensemble/member identity is included for multiple future outputs;
- a short digest suffix guarantees uniqueness after normalization/truncation; and
- filenames are presentation metadata, never job or retry identity.

## Multi-dataset planning

`DatasetSelection` represents a dataset choice for the whole query. Its normal key
is provider plus dataset. `product_id` is an optional provider-wide product variant,
not an instruction to multiply every point by every station discovered elsewhere.

For each requested location and selection, the planner chooses the first candidate
in that location's backend ranking that matches provider, dataset and an explicitly
supplied product variant. With no `product_id`, station-backed providers therefore
resolve their locally ranked station independently at each point. Users who need one
specific NOAA station continue to constrain discovery through the request's explicit
`product_id`; this does not turn station identities from other locations into global
dataset selections.

Every feasible selection x location x period combination becomes one `OutputSpec`.
An unavailable combination produces a structured issue carrying both location and
dataset selection. It is not silently replaced. Fetch tasks are deduplicated only
when their verified source and parameters are identical; outputs remain distinct.

Legacy requests without `dataset_selections` keep their existing single-ranked-source
or explicit-hybrid behavior.

## Interface and compatibility

- Python remains canonical. REST, MCP and CLI receive behavior through
  `WeatherService`; adapters do not duplicate planning, naming or baseline policy.
- New optional fields preserve validation of stored plans and jobs created by
  `main` before this change.
- Existing artifact IDs and files remain readable. No data-root migration deletes
  or rewrites user artifacts.
- New plan hashes change because output IDs and semantic names are intentional plan
  contents. Previously submitted plans retain their recorded hashes.
- OpenAPI and frontend types are regenerated only after corrected `main` is merged
  into `feature/webui`.

## Branch and commit sequence

Work occurs in the isolated main-based branch `fix/core-output-identity`.

1. Port and verify independent fixes in small feature/provider/job commits.
2. Add failing tests for shared-task/multiple-output identity and semantic names.
3. Implement output keys and historical/future filename generation.
4. Add failed-output retry on output identities.
5. Add and evaluate multi-dataset planning with station-backed and gridded fixtures.
6. Update architecture, features, limitations and API usage documentation.
7. Run the full offline suite, Ruff and mypy; merge the branch locally into `main`.
8. Run the full checks again on merged `main`.
9. Merge updated `main` into `feature/webui`, resolve only against the corrected
   core contract, regenerate OpenAPI/TypeScript artifacts and run Python/UI checks.
10. Create `feature/mcp` from updated `main` and leave it checked out without adding
    MCP feature work in this integration task.

Normal human authorship is preserved. No force push, rebase, branch deletion,
publication or remote push is part of this work.

## Test strategy

Tests are written and observed failing before implementation for each new behavior.
The critical cases are:

- two requested points sharing one NOAA station create one fetch task and two unique
  output IDs, filenames, job items and artifacts;
- duplicate location names or normalized filename fragments remain collision-safe;
- long names stay within 100 characters and retain their meaningful prefix;
- historical full-year, date-range, published and future ensemble names expose the
  correct semantic fields;
- new job totals equal planned output mappings even when tasks are shared;
- recovery and retry skip successful output IDs and retry only missing ones;
- a dataset-level NOAA selection resolves the best station per location without a
  station-by-point Cartesian product;
- an explicitly unavailable product produces a structured location/selection issue;
- requests without dataset selections preserve prior behavior; and
- old plans without output IDs retain their hashes and resume by legacy filenames.

Integration verification covers Python unit/integration tests offline, Ruff, mypy,
generated contracts after the UI merge, UI type checking/unit tests/build, and the
repository's existing browser acceptance where dependencies are available.

## Non-goals

- No new MCP tools are designed or implemented here.
- No provider availability is fabricated to make coverage appear complete.
- No artifact-history rewrite or deletion is performed.
- No public package, branch or UI deployment is published.
