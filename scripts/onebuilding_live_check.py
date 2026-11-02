"""Download published OneBuilding files through the service and compare each EPW with its workbook row.

Research tooling for availability rounds (phase 6, 2026-11-01): one file per family or file-name
shape, never a guessed path. Writes a JSON record of rows, header position and QC codes; the EPW
files stay in the given data root. OneBuilding needs no credentials.

    python scripts/onebuilding_live_check.py --data-root .local/o6 --out record.json checks.json

``checks.json`` lists ``{"family", "url", "lat", "lon"}`` (the workbook point).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from openepw.config import RuntimeConfig
from openepw.epw import read_epw
from openepw.models import OpenEPWError, WeatherRequest
from openepw.service import WeatherService


def check(service: WeatherService, item: dict) -> dict:
    record = {"family": item["family"], "url": item["url"], "workbook_point": [item["lat"], item["lon"]]}
    path = urlsplit(item["url"]).path.lstrip("/")
    try:
        bundle = service.fetch(WeatherRequest.model_validate({
            "locations": {"lat": item["lat"], "lon": item["lon"], "name": item["family"]},
            "product": "tmy", "providers": ["onebuilding"], "product_id": path}))
    except OpenEPWError as error:
        return {**record, "outcome": error.issue.code, "message": error.issue.message[:200]}
    if not bundle.weather:
        return {**record, "outcome": "NO_EPW", "issues": [issue.code for issue in bundle.issues]}
    qc = json.loads((service.config.data_root / bundle.qc.path).read_text(encoding="utf-8"))
    epw = read_epw(service.config.data_root / bundle.weather[0].path)
    lat, lon = epw.location.lat, epw.location.lon
    return {**record, "outcome": "ok", "epw_rows": len(epw.data), "epw_header_point": [lat, lon],
            "header_vs_workbook_degrees": round(math.hypot(lat - item["lat"], lon - item["lon"]), 4),
            "qc_codes": sorted({issue["code"] for output in (qc if isinstance(qc, list) else [qc])
                                for issue in output.get("issues", [])})}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("checks", type=Path)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    service = WeatherService(RuntimeConfig(data_root=args.data_root))
    results = []
    for item in json.loads(args.checks.read_text(encoding="utf-8")):
        results.append(check(service, item))
        print(json.dumps({key: results[-1].get(key) for key in
                          ("family", "outcome", "epw_rows", "header_vs_workbook_degrees", "qc_codes")}))
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
