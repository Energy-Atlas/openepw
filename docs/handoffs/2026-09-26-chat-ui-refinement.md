# Chat UI refinement handoff

**Branch:** `feature/chat-ui` in `C:\github\Energy-Atlas\openepw` (normal checkout, no worktree). **Handoff point:** `2573a5e`. The branch was created from `feature/mcp` at `516e0ed`; inspect status and recent commits before editing because other work may have landed. The owner authorized the map-first UI on this branch. Do not edit the ignored root `.env` unless the owner explicitly changes that instruction.

## Read first

- Repository `AGENTS.md`, [human brief](../20260920-openepw-brief.md), [architecture](../../ARCHITECTURE.md), [features](../../FEATURES.md), and the [current Stage 2 plan](../plans/2026-09-20-stage-2.md), as required for broad work.
- [Approved map-first UI plan](../plans/2026-09-26-guided-weather-chat-ui.md), [UI validation and acceptance limits](../validation/2026-09-26-chat-ui.md), [local setup](../../web/chat-ui/README.md), and [map-scene ADR](../decisions/0004-map-first-chat-scene.md). These contain the feature contract, test evidence, and rendering limitations; avoid restating them in new docs.
- [Visualization contract](../design/2026-09-26-weather-visualization.md) and [post-download conversation plan](../plans/2026-09-26-post-download-conversations.md) when changing chart or artifact conversations.

## Current state and immediate continuation

The optional React client lives in `web/chat-ui`; Python REST/chat code remains authoritative. The latest commits added a single UTC solar scene time, geography toolbar only in map-input mode, a composer attachment button in place of header uploads, conversation-style tool/choice messages, and faint documented catalog scope layers. See `7ee5a85`, `ea0e4e0`, and `2573a5e` for those changes. Future-weather UI remains suspended. Browser weather retrieval still requires explicit review and **Run**; map gestures do not start provider jobs.

The owner's latest question was how to start over messaging. There is currently no visible **New chat** control. `web/chat-ui/src/App.tsx` stores only the session ID under `openepw-chat-session` in `sessionStorage` and resumes it on reload. I gave a temporary browser-console workaround: remove that key and reload. A first-class new-chat/reset action is a likely next refinement, but the owner has not explicitly requested implementation of that control. Preserve old jobs and artifacts if adding it.

The newest `/v1/catalog/scopes` route was checked through service and component tests. The local API process predating the route was still running during the browser check, so the actual initial map overlay needs a live check after restarting the API. The active snapshot yielded two mapped CDS rectangles and nine unmapped source datasets; unmapped products must remain unplotted rather than be given invented coverage. Availability polygons are documentary scope, not point-level eligibility or retrieved-weather quality.

One optional clarification was sent about whether globe movement should change the UTC clock or only recompute local sun angle. No answer had arrived at handoff; implementation holds UTC fixed and recomputes local solar elevation from the map center, matching physical global time. Do not silently reinterpret the clock if the owner responds later.

Open acceptance limits, especially shadow alignment and GPU coverage, map-service failures, accessibility, and broad conversation phrasing, are recorded in the validation document. Use the concrete next request to choose the refinement; do not declare the entire UI accepted based on the current local smoke checks.

## Working and verification notes

- Start API from repo root: `.venv\Scripts\openepw.exe --data-root .local/openepw --env-file .env serve --host 127.0.0.1 --port 8000`. Start Vite with `cd web/chat-ui; npm ci; npm run dev`, then open `http://127.0.0.1:5173`. Existing user-started processes may already occupy ports; inspect before replacing anything.
- Browser code entry points: `web/chat-ui/src/App.tsx`, `api.ts`, `app.css`, `map/MapCanvas.tsx`, `map/evidence.ts`, and `views/ViewPanel.tsx`. Shared Python endpoints are in `src/openepw/api/app.py`; the catalog-scope service is in `src/openepw/service.py`.
- Last focused verification: 20 availability/API Python tests passed, 32 browser tests passed, Vite build passed, and focused Ruff passed. The earlier full Python run was 442 passed/17 skipped before the final refinement. Re-run checks appropriate to new changes; report fresh evidence. The current validation file lists commands and limits.
- Preserve normal configured human Git authorship and `fix(topic): ...` commits. Do not alter `.env`, `.local` data, contributor work, or `feature/mcp` while refining `feature/chat-ui`.

## Suggested skills

- `superpowers:brainstorming` for new behavior or UI features; use the owner's latest instructions as the design boundary.
- `frontend-design:frontend-design` for visual changes to the map/chat composition.
- `superpowers:systematic-debugging` or `diagnosing-bugs` for a reproducible UI/runtime failure.
- `superpowers:verification-before-completion` before claiming a fix and committing it.
