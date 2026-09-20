# Stage 2 execution record

Plan: `docs/plans/2026-09-20-stage-2.md`. Owner approval: 2026-09-20.

## Preflight and decisions

- Clean checkout at `00bdb7e`, branch `feature/stage-1-validation`; preserve it as
  explicitly requested. No product package or tests existed at approval.
- Task 1 schemas feed tasks 2–10; public names and shapes follow ARCHITECTURE.md.
  Task 2 dataset/codec feeds all providers and both generators. Task 3 service
  and artifacts feed batch/jobs/adapters. Future requests use the same plans and
  bundles. No conflicting interfaces found; optional dependencies stay lazy.
- Ruling: keep this tracked ledger instead of a platform-specific shell ledger:
  decisions must survive machine changes and the repository is Windows-native.
- Ruling: use the owner's existing checkout/branch, not a new worktree, following
  the explicit instruction to preserve the current branch and local credentials.
- Credential checks before approval: NSRDB 2024 Ithaca returned 8,784 hourly rows;
  CDS ERA5 and ERA5-Land each returned a one-hour NetCDF after license acceptance.
  Python trust-store verification failed for the CDS object store; Windows curl
  with certificate verification succeeded. Raw files and secrets remain ignored.
  These are access checks, not yet adapter/scientific acceptance.

## Tasks

1. Foundation — in progress.
2. EPW and QC — pending.
3. Open-Meteo/service/artifacts — pending.
4. Native products — pending.
5. NOAA/NSRDB/CDS — pending.
6. Spatial/hybrid/batch — pending.
7. Jobs/REST — pending.
8. CMIP6/morphing — pending.
9. Hourly future profiles — pending.
10. MCP/CLI/examples — pending.
11. Hardening/review/delivery — pending.

## Deferred issues and reminders

None recorded yet. Publication and shared-branch integration are outside this run.

## Empirical findings during implementation

- CMIP6 catalog: 170 complete seven-variable historical/SSP245 model/member pairs.
  ACCESS-CM2 r1i1p1f1 gn numeric access passed for tas/tasmin/tasmax/hurs/ps/
  sfcWind/rsds, 360 monthly values each for 1985�2014 and 2036�2065 at the
  nearest cell to Ithaca. Source calendars retained. Local extracted NetCDFs
  remain ignored. Monthly chunks are large; enforce a byte estimate in planning.
- NSRDB uses an HTTPS redirect to its NLR S3 object-store path; only that exact
  redirect host/path is accepted and authentication headers are not forwarded.
- NOAA global-hourly returned empty across a year boundary; splitting by calendar
  year recovered 99 reports and the requested 48 hourly targets.
- CDS returns a ZIP of separate instantaneous/accumulated NetCDFs even with
  `download_format=unarchived`. Merge matching coordinates before normalization;
  never treat instantaneous fields as accumulated fields.
- Ruling: source modules share wire contracts in `models/__init__.py` for v0.1;
  do not add re-export-only files solely to match the proposed diagram.
