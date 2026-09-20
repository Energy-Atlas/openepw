# MCP API

Run `openepw mcp` for stdio; `openepw mcp --transport streamable-http` is loopback-only.
The web UI uses REST; both adapters delegate to the Python service.

| Tool | Purpose |
| --- | --- |
| weather_geocode | Resolve explicit location candidates |
| weather_discover | Inspect source alternatives |
| weather_plan | Prepare weather or future plans |
| weather_fetch | Submit an existing-weather plan as a durable job |
| weather_inspect | Inspect a job or artifact reference |
| weather_generate_future | Submit a future request or plan |

`weather://artifacts/{artifact_id}` reads a checksummed artifact. Future inputs
use registered artifact IDs, never arbitrary server paths. Tool failures carry an
`error` object; job completion must be polled. Hourly rows are not returned inline.
Exact input schemas/descriptions are generated from the running SDK tool catalog
into `ui/public/api-catalog.json` and verified by a parity test.
