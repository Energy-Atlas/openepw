"""CLI resolves a stored weather plan without a second plan file."""

import importlib
import json

from test_batch import StationProvider

from openepw.config import RuntimeConfig
from openepw.models import Location, WeatherRequest
from openepw.service import WeatherService


def test_cli_execute_accepts_plan_hash(tmp_path, monkeypatch, capsys):
    service = WeatherService(RuntimeConfig(data_root=tmp_path), providers=[StationProvider()])
    plan = service.plan(WeatherRequest(locations=Location(lat=1, lon=0),
                                       start="2024-01-01", end="2024-01-01"))
    cli = importlib.import_module("openepw.cli.main")
    monkeypatch.setattr(cli, "WeatherService", lambda config: service)
    code = cli.main(["--data-root", str(tmp_path), "execute", plan.plan_hash])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["weather"]) == 1
    assert result["plan"]["role"] == "plan"
    assert "dry_bulb" not in result
