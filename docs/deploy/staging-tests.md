# Staging tests

Automated checks of the deployed staging service, signed in as its **tester account**
(owner, 2026-11-16; ADR 0006 tester account). They replace the manual signed-in check for
everything a script can see; judging how the UI feels stays a person's job.

## Set up once

1. On your machine, in the repository: `openepw accounts tester-secret`. It writes a random
   password to your git-ignored `.env` (`OPENEPW_STAGING_TESTER_NAME`,
   `OPENEPW_STAGING_TESTER_PASSWORD`) and prints `OPENEPW_TESTER_NAME` and
   `OPENEPW_TESTER_PASSWORD_HASH`.
2. In Render, on the **staging** service only (it has `OPENEPW_DEBUG_LOG`), set those two and
   redeploy. Production ignores them even if copied.
3. Add `OPENEPW_STAGING_URL=https://openepw-staging.onrender.com` to `.env`.
4. `pip install -e ".[e2e]"` and `python -m playwright install chromium`.

## Run

```bash
pytest tests/staging -m staging
```

| What | When | Cost |
|---|---|---|
| Sign-in, header buttons, place preview and its tick, product dialog, typed plan correction, transcript pinning, no map query next to the chat | Every run (stops at the plan review) | Free; guided mode |
| Stub runs: a full run with the file list, a planned provider failure and its retry (eval task S65), an agent session driven by eval task S1's script, a new request leaving the results | Every run | Free; eval stub providers, separate folder on staging |
| One real retrieval (Open-Meteo, one point, one year) with an EPW download; the results card closing on a new request | `OPENEPW_STAGING_REAL=1` | Free provider, a few minutes |
| An availability question in agent mode on the real model | `OPENEPW_STAGING_AGENT=1` | Model spend, capped at $1 per session and $3 per day for the tester |

Without the settings every staging test is skipped, so the normal `pytest` run and CI are
unchanged.

## The tester's treatment (security profile `tester`)

- Its own limits: 30 sessions an hour, 60 inputs a minute, 2 running jobs, $1 model spend per
  session and $3 per day; its spend is left out of the site's daily total.
- Its sessions are tagged (`tester:<name>`) and removed after 24 hours. Their jobs and files
  stay until a retention policy exists (phase 7.2).
- Stub sessions (`POST /v2/agent/sessions` with `{"stub": {"task": "S65", "mode": "guided"}}`)
  run on the eval stub providers with that task's setup; `"mode": "agent"` needs a task and
  uses its script as the model. Nobody else may ask for one (403). Stub files live in their own
  folder and cannot be downloaded through `/v1/artifacts`.
- Forms, gates and guard-rails are the same as for everyone; it never sees other people's
  sessions and has no admin actions.

## Rotate or remove

Run `openepw accounts tester-secret` again and update the hash in Render (its sessions end on
the redeploy), or delete the two variables to disable the tester.
