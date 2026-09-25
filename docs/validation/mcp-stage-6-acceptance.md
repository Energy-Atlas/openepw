# MCP Stage 6 — local agent and real-client pilot acceptance

Date: 2026-09-25. Branch: `feature/mcp`. Scope: the owner-approved Windows
local pilot and release check for the production MCP stages. The
[predefined scorecard](../pilot/scorecard.md) and [observed results](../pilot/results.md)
are the detailed evidence. No Stage 1 inventory collection or annotation
review was restarted. The original ignored snapshot and `.env` were not
modified or committed.

## Decision and evidence

The scripted reference agent and real MCP Python SDK stdio client met the
predefined threshold: eight of nine offline scorecard rows passed; the
published batch row was partial because the far location remained
`unresolved` without evidence for a hard `unsupported` exclusion. The client
negotiated protocol 2025-11-25,
listed 18 tools and one resource template, and read checksummed EPW/manifest/QC
resources. A fresh Windows/Python 3.13.9 environment installed only the
documented optional harness extra and passed startup and artifact inspection.
The agent explained source alternatives, exact published product, different
future baseline origins, partial batch rows, uncertainty and NOAA sentinel
gaps. No emitted output was claimed simulation-ready.

| Verification | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest -q` | 330 passed, 15 opt-in live/snapshot tests skipped, 2 dependency deprecation warnings, before the active-cancellation pilot test was added |
| Focused `tests/pilot` and `tests/harness` | 19 passed after the active-cancellation journey and final pilot assertions |
| Ruff `src tests` and mypy `src/openepw` | Passed; mypy checked 62 source files |
| `.venv/Scripts/python.exe -m build` | Wheel and sdist built successfully |
| Fresh `.[harness]` install, SDK stdio smoke | Python 3.13.9, MCP SDK 1.30.0, protocol 2025-11-25; 18 tools, 1 template, checksum artifact passed |
| Open-Meteo 2024 via MCP | One full-year output, 7 tool calls, 2.36 s, no QC issue codes; `simulation_ready=false` |
| OneBuilding named TMYx via MCP | One output, 5 tool calls, 1.31 s, `NATIVE_MINUTE_ZERO`; `simulation_ready=false` |
| Bounded optional model run | Eight cumulative `gpt-6-luna` calls, 3,161 input and 1,568 output tokens, estimated US$0.0011001; no LangSmith trace |

The provider downloads and run ledgers are local ignored files. The two new
public-source retrieves add no billable API charge. Provider terms and output
attribution remain those in the existing manifests; no downloaded weather is
bundled or redistributed. Earlier v0.1 live acceptance for other providers
and future methods is separate evidence, not a new Stage 6 live check.

## Findings and corrections

The model initially parsed a named TMYx batch as generic `published` and
capitalized OneBuilding, leaving zero planned output. Intent guidance now
pins explicit TMYx language and lowercase provider IDs; agent request
construction normalizes provider casing. A bounded rerun completed three
outputs and reported the unresolved fourth location. The real MCP client
also verified that a returned no-output plan is described as such rather
than as completed weather. This is a tested case, not a general guarantee
for arbitrary prompts.

The pilot found no core EPW/QC defect. Unsupported method/period errors and
missing/corrupt artifact errors used the existing typed contract; assertions
were corrected to its exact codes. A mixed NOAA batch retained a valid EPW
while the gapped output failed under `missing_policy=error`; the `warn`
variant emitted field-specific missing sentinels and linked QC. The agent
never promoted either to simulation-ready. The fresh install showed a
pre-existing local pip `~penepw` invalid-distribution warning but completed.
An active cancellation can let an in-flight output finish; the client test
verified that artifact remains readable and a linked retry emits only the
missing output. The published batch's far point was honestly unresolved,
not falsely excluded, which is the one partial scorecard row.

## Remaining limits

This acceptance is for the tested Windows MCP SDK stdio client and scripted
reference agent. Human comprehension, another desktop client, Linux/macOS
execution, remote/team deployment, and EnergyPlus consumption were not
tested. The local pilot does not certify any EPW for simulation. Live
provider success applies only to the exact tested location, period and
product. Availability remains eligibility to attempt retrieval; it cannot
promise complete hours or variables. The accepted Stage 1 annotations and
local snapshot keep their prior scope. Publication, team hosting and
cross-run weather reuse remain outside this completed local program.
