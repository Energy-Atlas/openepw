"""The CLI emits visualization spec and prepared data as JSON only."""

import json

from test_epw import synthetic

from openepw.artifacts.store import ArtifactStore
from openepw.cli.main import main
from openepw.epw.writer import epw_bytes


def test_cli_visualize_and_page_print_json_without_chart_markup(tmp_path, capsys):
    ref = ArtifactStore(tmp_path).write("a" * 32, "weather.epw",
                                        epw_bytes(synthetic(2023, 24)), "weather")
    request = tmp_path / "view-request.json"
    request.write_text(json.dumps({"artifact_ids": [ref.id], "family": "time_series",
                                   "variable": "dry_bulb"}))
    assert main(["--data-root", str(tmp_path), "visualize", str(request)]) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["specs"][0]["family"] == "time_series"
    assert prepared["rows"][0]["value"] == 20.0
    assert main(["--data-root", str(tmp_path), "view-page", prepared["view_id"]]) == 0
    page = json.loads(capsys.readouterr().out)
    assert page["view_id"] == prepared["view_id"]
    assert page["rows"][0]["value"] == 20.0
