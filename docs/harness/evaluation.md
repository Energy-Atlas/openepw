# Reference agent evaluation rubric (frozen before harness tuning)

Date: 2026-09-25. Tests under `tests/harness/` define the fixed deterministic
rubric. Every critical rule must pass; the remaining tool-order/explanation
checks must pass at least 9 of 10 points for local acceptance. The score
uses observed MCP tool names, stored/submitted hashes, artifact/QC facts and
the final explanation. A clarification is a valid outcome when the request
omits material geography, product, baseline or climate semantics.

| Case | Required behavior |
| --- | --- |
| A — actual-year point | Clarify ambiguous name, assess/discover alternatives, plan actual year, submit the unchanged hash, inspect job/artifact/QC. Explain eligibility versus retrieved quality. |
| B — published batch | Preserve product and duplicate occurrences, shared source identity, unsupported row, successful artifacts and compact export mapping. |
| C — future | Keep uploaded and fetched artifact IDs distinct; use method/scenario/reference/climate windows as stated; reject unsupported SSP/RCP or site/window combinations. Explain baseline origin and unchanged variables. |
| G — NOAA gap | With `warn`, report the gap, sentinel/QC and `simulation_ready=false`; with `error`, report failed row and no EPW. |
| Recovery | Resume by job ID after reconnect, avoid re-submitting completed work, retry only failed output IDs when explicitly requested. |
| Merged evidence | An unprobed NSRDB `tdy-2023` map cell does not answer actual-year 2023 eligibility. An allowed CMIP6 model license does not verify a climate window or footprint. |

Critical failures are wrong geography without clarification, fabricated
availability, silent source switch, unsupported future method, false readiness,
changed plan hash, or leakage of credentials/local paths. The harness should
store only tool names, safe opaque IDs, statuses, durations and bounded summaries.
It must not persist prompts, raw EPW hours, full inventories or secret-bearing
arguments. LangSmith is disabled, even if a key exists.

The offline model stub and synthetic MCP transcripts cover all cases. Real
`gpt-6-luna` smoke is opt-in and scored separately; it does not make a
nondeterministic result a CI gate.
