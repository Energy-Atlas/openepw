"""Check the Himawari-8 hourly re-binning against 10-minute NSRDB data (availability research).

ADR 0002 (amended 2026-10-27): the hourly ``himawari`` product's :00 values are instantaneous, so
the adapter takes each hour-ending irradiance value as the mean of the samples at the hour's start
and end. This script measures that against the hour's integral from a 10-minute year of the same
point (trapezoid over the seven samples from start to end) with the thresholds fixed on
2026-10-27: annual GHI within 1% and hourly RMSE at most 10% of mean daylight GHI.

    python scripts/himawari_rebin_check.py download --env-file .env --lat 43.06 --lon 141.35 \
        --year 2019 --out sapporo-2019-10min.csv --log sapporo-2019.json
    python scripts/himawari_rebin_check.py analyze sapporo-2019-10min.csv --out analysis.json

``download`` reads the NLR key and email from the env file through RuntimeConfig and never writes
or prints them; the log keeps hosts, paths and statuses only.
"""

from __future__ import annotations

import argparse
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

ENDPOINT = "https://developer.nlr.gov/api/nsrdb/v2/solar/himawari-download.csv"
ATTRIBUTES = "ghi,dni,dhi,air_temperature,solar_zenith_angle"
LIMIT = 10_000_000


def download(args: argparse.Namespace) -> None:
    from openepw.config import RuntimeConfig

    config = RuntimeConfig.load(env_file=args.env_file)
    if not config.nlr_api_key or not config.nlr_email:
        raise SystemExit("The env file has no NLR key and email")
    params = {"api_key": config.nlr_api_key.get_secret_value(), "email": config.nlr_email.get_secret_value(),
              "wkt": f"POINT({args.lon} {args.lat})", "names": str(args.year), "interval": "10",
              "utc": "true", "leap_day": "true", "mailing_list": "false", "attributes": ATTRIBUTES}
    hops = []
    body = bytearray()
    with httpx.Client(timeout=300, follow_redirects=False) as client:
        url, query = ENDPOINT, params
        for _ in range(4):
            with client.stream("GET", url, params=query) as response:
                hops.append({"host": response.url.host, "path": response.url.path, "status": response.status_code})
                if response.is_redirect:
                    url, query = response.headers["location"], None
                    continue
                if response.status_code == 200:
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > LIMIT:
                            raise SystemExit("Response exceeds the 10 MB cap")
                break
    status = hops[-1]["status"] if hops else None
    if status == 200:
        args.out.write_bytes(bytes(body))
    args.log.write_text(json.dumps({
        "id": args.out.stem, "dataset": "himawari", "names": str(args.year), "interval": 10,
        "point": [args.lat, args.lon], "endpoint": ENDPOINT, "at": datetime.now(timezone.utc).isoformat(),
        "hops": hops, "status": status, "bytes": len(body) if status == 200 else 0}, indent=1), encoding="utf-8")
    print(json.dumps({"status": status, "bytes": len(body)}))


def read(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    frame = pd.read_csv(io.BytesIO(raw), skiprows=2)
    stamps = pd.to_datetime(frame[["Year", "Month", "Day", "Hour", "Minute"]], utc=True)
    return frame.set_index(stamps).sort_index()


def analyze(args: argparse.Namespace) -> None:
    frame = read(args.csv)
    minutes = sorted(frame.index.minute.unique().tolist())
    ghi = frame["GHI"].astype(float)
    # Reference: the hour ending at h is the trapezoid mean of the samples from h-1 to h.
    weights = np.array([0.5, 1, 1, 1, 1, 1, 0.5]) / 6
    samples = np.lib.stride_tricks.sliding_window_view(ghi.to_numpy(), 7)[::6]
    ends = ghi.index[6::6][:len(samples)]
    reference = pd.Series(samples @ weights, index=ends)
    # The adapter's re-binning from the :00 instants only.
    instants = ghi[ghi.index.minute == 0]
    rebinned = ((instants.shift(1) + instants) / 2).reindex(reference.index)
    unshifted = instants.reindex(reference.index)                     # the :00 value used as the hour
    valid = reference.notna() & rebinned.notna()
    daylight = reference[valid] > 0
    mean_daylight = float(reference[valid][daylight].mean())

    def score(series: pd.Series) -> dict:
        error = series[valid] - reference[valid]
        return {"annual_total_error_pct": round(100 * float(series[valid].sum() / reference[valid].sum() - 1), 3),
                "hourly_rmse_pct_of_mean_daylight": round(100 * float(np.sqrt((error ** 2).mean())) / mean_daylight, 2)}

    result = {
        "file": args.csv.name, "rows_10min": len(frame), "minutes": minutes,
        "hours_compared": int(valid.sum()), "mean_daylight_ghi_w_m2": round(mean_daylight, 1),
        "rebinned_vs_reference": score(rebinned), "unshifted_vs_reference": score(unshifted),
        "thresholds": {"annual_total_error_pct": 1.0, "hourly_rmse_pct_of_mean_daylight": 10.0},
    }
    r = result["rebinned_vs_reference"]
    result["passes"] = abs(r["annual_total_error_pct"]) <= 1.0 and r["hourly_rmse_pct_of_mean_daylight"] <= 10.0
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("file", "hours_compared", "rebinned_vs_reference",
                                                   "unshifted_vs_reference", "passes")}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    get = sub.add_parser("download")
    get.add_argument("--env-file", type=Path, required=True)
    get.add_argument("--lat", type=float, required=True)
    get.add_argument("--lon", type=float, required=True)
    get.add_argument("--year", type=int, required=True)
    get.add_argument("--out", type=Path, required=True)
    get.add_argument("--log", type=Path, required=True)
    check = sub.add_parser("analyze")
    check.add_argument("csv", type=Path)
    check.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    download(args) if args.command == "download" else analyze(args)


if __name__ == "__main__":
    main()
