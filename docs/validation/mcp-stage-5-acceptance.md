# MCP Stage 5 — reference agent acceptance

Date: 2026-09-25. Branch: `feature/mcp`. Scope: optional local reference
agent, fixed offline rubric, real stdio MCP integration, framework comparison
and bounded `gpt-6-luna` smoke. `.env` was read only by ignored local smoke
scripts and was not edited, copied or staged. LangSmith was not called.

## Executed checks

| Check | Observed result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q` | 322 passed, 15 opt-in live/snapshot tests skipped, 2 third-party warnings |
| Focused harness/real stdio tests | 11 passed, including restart, NOAA gap, partial batch, uncertainty and future job |
| `.venv/Scripts/python.exe -m ruff check src tests` | Passed |
| `.venv/Scripts/python.exe -m mypy src/openepw` | Passed for 62 source files |
| `.venv/Scripts/python.exe -m build` | Wheel and sdist built |
| Editable `.[harness]` install and `openepw-agent --help` | Passed on Windows/Python 3.13.9 |

The fixed [rubric](../harness/evaluation.md) blocks changed plan hashes,
false readiness, unsupported method substitution, wrong geography,
fabricated availability, source switching and secret/path leakage. The
deterministic stub tests checked clarify → discover → plan → submit → inspect
and scored the NOAA-gap explanation. They also verified that a published
partial batch names the unsupported occurrence without automatic retry,
unprobed NSRDB actual-year 2023 remains unknown, and an allowed CMIP6
license does not hide an unverified climate window. One real stdio test
uploaded a complete user EPW, ran a future morph job and resumed by job ID
after reconnect. The local record contained only IDs and tool names.

## Bounded model run

Official [GPT-6 Luna model/pricing documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)
was checked before calls: standard short-context text prices were US$0.10
per million input and US$0.50 per million output tokens. Five Responses API
calls used 1,463 input and 736 output tokens, for an estimated US$0.0005143
in the ignored cumulative ledger. The parser used low reasoning effort,
`store=false`, no hosted tools and a bounded output cap. A 2024 actual-year
Ithaca prompt was parsed as AMY, which retains actual-year meaning but shows
that the natural-language product label can vary. The final real-model plus
real-MCP run used a directly uploaded synthetic EPW and local signals ID;
it selected morph/SSP245, reference 1985–2014, climate 2036–2065, kept
`user_provided` baseline origin, completed one job and reported
`simulation_ready=false`.

An initial freeform JSON parser produced invalid future fields; a structured
schema and literal scenario validation corrected it. One intermediate
future-plan call then returned typed `INVALID_REQUEST` before the scenario
constraint was tightened. All three attempts were counted in the ledger.
The final run passed without changing source or method to evade the error.
These are local model observations, not a guarantee for arbitrary prompts.

## Stack and limits

The [isolated LangGraph comparison](../harness/stack-decision.md) completed
the same A/G checks, but brought a second MCP SDK era, beta adapter,
additional result parsing and nonpersistent default checkpoints. The direct
MCP SDK harness is the chosen optional stack; no graph or LangSmith package
was added to OpenEPW dependencies. The command and privacy boundary are in
[harness setup](../harness/README.md).

The offline cases use synthetic transcripts/data. The model smoke exercised
intent and a synthetic future job, not a live weather provider, participant
session or EnergyPlus run. The integrated provider/client pilot is Stage 6.
Run records are local and redacted; the model API did receive sanitized task
text. Natural-language quality and client host behavior outside the tested
Windows SDK remain open limits.
