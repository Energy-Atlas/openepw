# ADR 0003: Optional same-repository local web UI

Accepted 2026-09-20 by explicit owner direction; supersedes only the original
no-frontend constraint. Keep `ui/` beside the Python package, with an independent
npm build and optional FastAPI `/ui/` static mount. No repository extraction or
publication. Local-first single-user is the deployment scope.

React/TypeScript/Vite, FlexLayout, React Aria, Zustand and MapLibre follow the
owner-selected EnergyAtlas reference. Only appearance definitions and the small
worker-build approach are adapted; no domain datasets, branding, LLM/simulated
engines or reference credentials. Reference-theme redistribution permission remains
a prepublication follow-up. Source provenance lives in `ui/THIRD_PARTY_NOTICES.md`.

TypeScript 5.9.3 is used because openapi-typescript 7.13 declares TS5 compatibility;
forcing the reference TS6 peer conflict would weaken reproducible installation.
Pinned Node 24 tooling and lockfile reproduce the checked build.

Manual and scripted actions share one dispatcher and typed REST client. The browser
never transforms weather or invokes a separate MCP transport. New job-history,
preview and signal-upload routes are additive. Missing data, source years, calendar
semantics and source displacement come from Python responses. Map terrain and
building heights never imply provider resolution.

Reviewed plans expire on reload. Submission-intent keys persist separately by plan
hash, so explicit retry/re-review reconciles rather than duplicates accepted jobs.
An intentional rerun uses a new key. Client abort and server cancellation remain
separate. Bearer tokens stay in memory; provider credentials stay server-side.

Testing separates deterministic synthetic provider/browser fixtures from opt-in
real data. Core Python packaging excludes the frontend and remains independently
installable; there is no mandatory Node runtime or distributed deployment.
