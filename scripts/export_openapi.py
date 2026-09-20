"""Export deterministic public HTTP contracts without credentials/network."""

import json
import sys
import tempfile
from pathlib import Path

from openepw.api.app import create_app
from openepw.config import RuntimeConfig
from openepw.service import WeatherService

with tempfile.TemporaryDirectory() as root:
    app = create_app(WeatherService(RuntimeConfig(data_root=root)))
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "ui/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    app.state.runner.close()
