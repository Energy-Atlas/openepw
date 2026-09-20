# Contributing

Stage 1 contains documentation and bounded standard-library probes only. Python
3.11+ is the proposed package floor; the Stage 1 probes ran on Windows/Python 3.14.
No dependency environment or product API is shipped yet.

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
   `.env.example` and `config.example.toml` describe proposed names, not a working
   loader. Do not send keys in issues, artifacts or test snapshots.
   See [local credential setup](docs/providers/credentials.md) for live tests.

During Stage 1, verify with:

```powershell
python -m compileall -q scripts
git diff --check
```

Live [probe commands](docs/validation/README.md) are opt-in and contact external
services. Prefer a selected provider to repeating every request. Inspect result
bodies and metadata, not only HTTP status.

Stage 2 will introduce an isolated environment, `pyproject.toml`, pytest, Ruff,
mypy and CI. Planned local verification is `python -m pytest -m "not live"`,
`ruff check .`, `ruff format --check .`, and `mypy src/openepw`.
Core CI must work without credentials/network; live tests use provider markers.
The platform matrix starts with Python 3.11/3.12 on Windows, Linux and macOS.
An installed EnergyPlus smoke test is optional and separately documented.

Only the owner publishes to PyPI or authorizes equivalent irreversible actions.
