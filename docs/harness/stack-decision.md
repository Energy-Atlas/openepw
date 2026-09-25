# Reference harness stack decision

Date: 2026-09-25. Chosen stack: direct MCP Python SDK client plus a small
explicit reference-agent state machine. The harness is an optional package
extra and calls Stage 4 tools only. No LangSmith requests or traces were sent.

## Bounded comparison

The direct implementation passed the same synthetic actual-year, NOAA-gap,
future and restart checks used by the fixed rubric. It uses the repository's
`mcp>=1.20,<2` optional dependency, maintains one stdio session and writes
only safe plan/job/artifact IDs and tool names to a local record. Its real
stdio integration test resumed a completed future job after closing the client.

An ignored isolated prototype installed LangGraph 1.2.12, LangChain 1.4.2,
FastMCP 4.0.9 and MCP SDK 2.2.0 (94 installed distributions). A three-node
`StateGraph` used `MCPAdapter` to plan, submit and inspect a synthetic
actual-year job, and inspected a NOAA-gap artifact. It completed the job,
preserved the hash and detected the gap with `simulation_ready=false`.
The client did connect to the Stage 4 v1 server, but first sent a modern
`server/discover` probe that produced 31 server-side validation diagnostics
before falling back to the legacy handshake. Adapter tool results arrived as
lists of text blocks, requiring another JSON parse to recover the already
structured Stage 4 data.

| Criterion | Direct client | Graph prototype |
| --- | --- | --- |
| A/G correctness | Passed | Passed |
| Restart | Local ID record plus canonical `job_inspect` passed | `InMemorySaver` loses checkpoints on process restart; a persistent checkpointer is another dependency and storage contract |
| Existing SDK compatibility | Uses pinned v1 extra | LangChain MCP extra pulled SDK 2.2 and FastMCP 4; conflicts with the installed `mcp<2` boundary |
| Result shape | Native structured MCP JSON | Adapter wrapped results as text blocks |
| Hosted tracing | None | LangSmith installed transitively; disabled, no calls |
| Complexity for this workflow | One state machine and one MCP session | Graph nodes, checkpointer, adapter and protocol-era handling |

The graph adds little to the current short linear workflows. Keeping it would
introduce a second MCP SDK era and a persistence mechanism while jobs already
persist in OpenEPW. The direct path therefore remains the reference harness.
Reconsider a graph only if later user tasks need branching multi-agent state
or long conversations that cannot be represented by stored IDs. The prototype
environment and scripts are ignored local files; no graph dependency is
bundled in OpenEPW.

References: [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[LangChain MCP adapter](https://docs.langchain.com/oss/python/langchain/mcp),
[connection lifecycle and protocol eras](https://docs.langchain.com/oss/python/langchain/mcp/connections).
