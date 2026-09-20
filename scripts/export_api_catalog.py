"""Generate Python and MCP references from public call signatures and tool schemas."""

import asyncio
import inspect
import json
import tempfile
from pathlib import Path

import openepw
from openepw.config import RuntimeConfig
from openepw.mcp.server import create_server
from openepw.service import WeatherService

DESCRIPTIONS = {
    "geocode": "Resolve a place name into explicitly selectable candidates.",
    "discover": "Find compatible source alternatives and report missing data or credentials.",
    "plan": "Create an inspectable weather plan without retrieving complete weather files.",
    "execute": "Execute a typed plan and return artifacts, provenance and QC; inspect partial failures.",
    "fetch": "Convenience planning and execution for an existing-weather request.",
    "plan_future": "Plan future generation with explicit method, climate period and baseline provenance.",
    "generate_future": "Generate future EPWs; target year represents a climate window, not a forecast.",
}


def catalog():
    with tempfile.TemporaryDirectory() as root:
        server = create_server(WeatherService(RuntimeConfig(data_root=root)))
        return {
            "python": [
                {
                    "name": name,
                    "signature": str(inspect.signature(value)),
                    "description": DESCRIPTIONS[name],
                }
                for name, value in inspect.getmembers(openepw, inspect.isfunction)
                if not name.startswith("_")
            ],
            "mcp": [t.model_dump(mode="json") for t in asyncio.run(server.list_tools())],
            "resources": [
                {
                    "uri": "weather://artifacts/{artifact_id}",
                    "description": "Read a checksummed weather, manifest or QC artifact.",
                }
            ],
        }


if __name__ == "__main__":
    path = Path("ui/public/api-catalog.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog(), indent=2) + "\n", encoding="utf-8")
