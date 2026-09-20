# Contributing

Use Python 3.11+ and a local virtual environment. Install with
`python -m pip install -e ".[dev,api,mcp,climate,cds]"`; tested development versions
are recorded in `requirements-dev.txt`. Domain imports must not require optional
server or climate packages.

1. Read the [brief](docs/20260920-openepw-brief.md), [architecture](ARCHITECTURE.md)
   and [plan](docs/plans/2026-09-20-stage-2.md). Coordinate changes through git docs.
2. Inspect `git status`, branches and recent commits before editing. Preserve
   collaborator changes; use purpose-based branches (`feature/...`, `fix/...`,
   `refactor/...`, `docs/...`) and ordinary commits. Never use an agent/model/name
   or `codex/` prefix. Leave existing branches unchanged unless asked.
3. Keep changes focused and messages `fix(topic): description`. Use your normal
   authorship. Never rewrite published history to resolve a collaboration issue.
4. Record provider/method assumptions, source versions, licenses and limitations.
   Do not check in downloaded data until its redistribution terms are established.
5. Keep credentials in environment variables or ignored local configuration.
   `.env.example` and `config.example.toml` document supported loader fields. Do not send keys in issues, artifacts or test snapshots.
   See [local credential setup](docs/providers/credentials.md) for live tests.

Run before delivery:

```bash
python -m pytest
python -m ruff check .
python -m mypy
python -m build
python -m compileall -q scripts examples
```

Offline tests use synthetic data and injected HTTP transports. `OPENEPW_RUN_LIVE=1`
enables provider acceptance checks in `tests/integration`; credentials load from
ignored `.env` explicitly inside those checks. Expensive climate checks additionally
require `OPENEPW_RUN_CLIMATE=1`. Do not run them merely to test unrelated changes.
Stage 1 disposable probe scripts are excluded from production lint; compile checks
cover them. Windows/Linux/macOS CI is configured for Python 3.11 and 3.13. Report
actual local and CI results separately. EnergyPlus smoke validation is optional
and must be identified as not run when no executable is available.

Use test-first fixes for scientific, security and job-state behavior. Never adjust
expected values just to make a test pass. Document material assumptions and deferred
limitations in git-controlled docs, including provider/product distinctions.

Only the owner publishes to PyPI or authorizes equivalent irreversible actions.
