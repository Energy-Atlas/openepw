# Stage 6 local pilot scorecard

Frozen before pilot journeys on 2026-09-25. The target is a building-energy
researcher or EnergyPlus user on the current Windows host. Scripted reference
agent and actual MCP SDK client sessions count as this pilot; human
participants and another desktop host do not.

## Passing rule

Every critical scientific/identity check must pass: explicit geography for an
ambiguous name; no fabricated source availability, implicit provider switch or
unsupported future method; unchanged submitted plan hash; requested
occurrence/output/artifact IDs kept distinct; NOAA sentinel EPW never called
simulation-ready; no secret or local-path leak in run records. A no-output
case must not be described as completed weather. `simulation_ready=false`
is reported for emitted outputs.

At least 8 of the 9 matrix rows below must pass offline through the actual
stdio client, with any failed row documented and fixed before local release
if it is material. The reference agent must pass A, C1/C2, G and uncertainty
explanations through either a real MCP session or fixed synthetic transcript;
the client must cover every row directly. A complete journey should finish
within 120 seconds on the tested local fixture and use no more than 30 MCP
tool calls; polling frequency is bounded. Billable live API usage remains
below US$10 cumulative, with no new calls at US$8 projected.

| Row | Observable result |
| --- | --- |
| A | Actual-year point with alternative; exact year, plan hash, EPW/QC and provenance |
| B | Published exact-product batch; duplicate occurrences, shared source, unsupported row and compact map |
| C1 | User-uploaded EPW ID, morph plan/job, baseline origin and windows |
| C2 | Fetched weather EPW ID reused for morph; separate hourly-profile source/window contrast |
| C3 | Unsupported SSP/RCP, site or window blocked without substitution |
| G warn | NOAA gap emits sentinel EPW, linked QC and false readiness |
| G error | NOAA gap fails row and emits no EPW |
| Recovery | Disconnect/reconnect, cancellation/retry/invalid artifact or input preserve completed work |
| Merged evidence | Unprobed NSRDB selector/location and CMIP6 license/window remain unknown |

Record client/SDK/OS, result and tool identities, elapsed time, QC language,
cost, and any fixture versus live distinction in the final acceptance file.
An offline synthetic pass is never promoted to provider live acceptance.
