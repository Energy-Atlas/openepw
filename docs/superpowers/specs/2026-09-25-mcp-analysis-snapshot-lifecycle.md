# MCP analysis snapshot lifecycle

Status: revised after owner comments, 2026-09-25. The input check described below is implemented on `feature/mcp`; the full Stage 1 inventory remains local. This is separate from the [program stage allocation](../../plans/2026-09-24-production-mcp-program.md).

## Storage and versioning

`analysis.json` is the local, offline-derived inventory used for a full Stage 1 catalog import. It is about 120 MB for the accepted snapshot and remains under ignored `.local/mcp-availability/`, alongside `ledger.json` and raw snapshots. It is not committed to Git, packaged in the wheel, or represented by Git-tracked generation manifests. Git retains the analyzer/importer code, sanitized Stage 1 findings and accepted OneBuilding review registry. The registry's 61 decisions remain separately pinned to source checksums.

The accepted local snapshot is preserved. Before regenerating its analysis with input fingerprints, the original was copied to ignored `analysis.pre-input-pins-20260925.json`; the regenerated inventories were compared with the original and were identical. No Stage 1 collection was rerun. A later accepted evidence follow-up should use its own ignored local snapshot directory, keep the previous directory or a local backup for rollback, run `analyze` offline against that follow-up's ledger/raw files, review the sanitized findings and annotation changes, and explicitly import the new analysis. Local backup and transfer are subject to the source terms; neither is a Git publication requirement.

## Import behavior

When `analysis.json` is available, explicit catalog import relies on its normalized inventories. The analyzer writes the ledger SHA-256 and a saved-source ID to raw SHA-256 map into the analysis. Before using it, the importer checks the supported analysis schema, confirms the analysis has no parse errors, verifies those input fingerprints against the local ledger, verifies each saved raw file against its ledger checksum, and checks accepted review pins. A missing or mismatched fingerprint fails the import without activating a new catalog generation. An older local analysis can be upgraded with the offline `analyze` command after preserving the original file. These checks catch mismatched or stale local inputs; they do not independently prove that every normalized row was correctly derived from the raw bytes. The local analysis is trusted for that transformation, and no external digest or signed manifest is claimed.

When `analysis.json` is absent, an explicit full-snapshot import reports that it is missing. Normal availability requests still work from the last active catalog, if one exists, or the small bundled source contracts; without a catalog, inventory-dependent outcomes remain unknown until a local analysis is supplied. The service does not silently recollect Stage 1 metadata or fabricate full-index answers. A failed import leaves the last active catalog generation usable.

This local lifecycle does not certify current upstream coverage, complete hourly weather, permission to redistribute inventories, or simulation readiness. New evidence and changed annotation pins enter through review, not automatic promotion.
