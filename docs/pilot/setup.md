# Local pilot setup

The target setup is Windows, Python 3.13.9 and MCP Python SDK 1.30.0.
Install the optional local client and agent in a fresh environment:

```powershell
python -m venv .local/pilot-venv
.local/pilot-venv/Scripts/python.exe -m pip install -e ".[harness]"
.local/pilot-venv/Scripts/openepw.exe --data-root .local/pilot-data mcp
```

The stdio process waits for an MCP client on stdin. In a client host,
configure the full executable path and the `--data-root <private-root> mcp`
arguments instead of starting it in an interactive terminal. The standalone
`openepw-agent` command is installed by the same extra; see
[harness instructions](../harness/README.md). The real SDK session in
`tests/pilot/test_install_smoke.py` lists tools/templates, calls a tool,
reads an artifact and closes cleanly. The fresh local environment actually
reported 18 tools, one resource template and protocol 2025-11-25;
`openepw-agent --help` also passed. One process per data root is supported.

Future climate sources may additionally require `openepw[climate]` or
`openepw[cds]` depending on method/provider. The synthetic morph fixture
uses registered signals and needs no live climate credentials. User EPW
upload is bounded at 5 MB; normal tool results now cap at 160 KB and resource reads
at 10 MB. The tested SDK client can read annual synthetic EPW blobs. Host
limits elsewhere remain unknown. `.env` is never copied into the pilot
environment or modified; approved live smoke reads only needed keys into
the test process. The local cost ledger and fixture data remain ignored.
