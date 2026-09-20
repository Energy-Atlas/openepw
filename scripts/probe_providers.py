"""Stage 1 disposable, bounded HTTP probes; not a provider implementation.

Standard library only. No credentials are read. Raw bodies remain in ignored
.local/; the shareable report stores structural observations and checksums.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def url(base: str, **params: object) -> str:
    return base + "?" + urllib.parse.urlencode(params)


PROBES = {
    "openmeteo_era5": url("https://archive-api.open-meteo.com/v1/archive", latitude=42.44, longitude=-76.50, start_date="2024-01-01", end_date="2024-01-02", models="era5", timezone="GMT", wind_speed_unit="ms", hourly="temperature_2m,relative_humidity_2m,dew_point_2m,surface_pressure,shortwave_radiation,direct_normal_irradiance,diffuse_radiation,wind_speed_10m,wind_direction_10m"),
    "openmeteo_era5land": url("https://archive-api.open-meteo.com/v1/archive", latitude=42.44, longitude=-76.50, start_date="2024-01-01", end_date="2024-01-01", models="era5_land", timezone="GMT", hourly="temperature_2m,relative_humidity_2m,shortwave_radiation,direct_normal_irradiance,wind_speed_10m"),
    "geocoding": url("https://geocoding-api.open-meteo.com/v1/search", name="Ithaca", count=2, language="en", format="json"),
    "nsrdb_query": url("https://developer.nlr.gov/api/solar/nsrdb_data_query.json", api_key="DEMO_KEY", wkt="POINT(-76.50 42.44)"),
    "nsrdb_no_key": url("https://developer.nlr.gov/api/solar/nsrdb_data_query.json", wkt="POINT(-76.50 42.44)"),
    "pvgis_tmy": url("https://re.jrc.ec.europa.eu/api/v5_3/tmy", lat=45, lon=8, outputformat="json"),
    "pvgis_epw": url("https://re.jrc.ec.europa.eu/api/v5_3/tmy", lat=45, lon=8, outputformat="epw"),
    "onebuilding_catalog": "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/USA_NY_New_York.html",
    "onebuilding_about": "https://climate.onebuilding.org/about.html",
    "noaa_isd": url("https://www.ncei.noaa.gov/access/services/data/v1", dataset="global-hourly", stations="72515094761", startDate="2024-01-01", endDate="2024-01-01", format="json", dataTypes="TMP,DEW,SLP,WND", units="metric"),
    "noaa_station_history": "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv",
    "cds_catalog": "https://cds.climate.copernicus.eu/api/catalogue/v1/collections/reanalysis-era5-single-levels",
    "cds_process": "https://cds.climate.copernicus.eu/api/retrieve/v1/processes/reanalysis-era5-single-levels",
    "openmeteo_climate": url("https://climate-api.open-meteo.com/v1/climate", latitude=42.44, longitude=-76.50, start_date="2050-07-01", end_date="2050-07-03", models="MRI_AGCM3_2_S", daily="temperature_2m_max,temperature_2m_min,temperature_2m_mean,relative_humidity_2m_mean,shortwave_radiation_sum,wind_speed_10m_mean"),
    "onebuilding_catalog_corrected": "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/index.html",
    "onebuilding_about_corrected": "https://climate.onebuilding.org/about/default.html",
    "noaa_isd_corrected": url("https://www.ncei.noaa.gov/access/services/data/v1", dataset="global-hourly", stations="72515004725", startDate="2024-01-01", endDate="2024-01-01", format="json", dataTypes="TMP,DEW,SLP,WND", units="metric"),
    "noaa_csv": "https://www.ncei.noaa.gov/data/global-hourly/access/2024/72515004725.csv",
    "oedi_locations": "https://data.openei.org/files/5974/PUMA%20information%20%281%29.csv",
    "fwg_download": "https://future-weather-generator.adai.pt/download/",
    "onebuilding_epw": "https://climate.onebuilding.org/WMO_Region_4_North_and_Central_America/USA_United_States_of_America/NY_New_York/USA_NY_Ithaca.Tompkins.Rgnl.AP.725155_TMYx.2011-2025.zip",
    "nsrdb_csv_no_email": url("https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-aggregated-v4-0-0-download.csv", api_key="DEMO_KEY", names="2024", wkt="POINT(-76.50 42.44)", interval=60, attributes="air_temperature,ghi,dni,dhi", utc="true", leap_day="true"),
    "nsrdb_legacy_query": url("https://developer.nrel.gov/api/solar/nsrdb_data_query.json", api_key="DEMO_KEY", wkt="POINT(-76.50 42.44)"),
}


def summarize(body: bytes, content_type: str) -> dict:
    result: dict = {}
    decoded = body.decode("utf-8", errors="replace")
    if "json" in content_type or decoded.startswith(("{", "[")):
        try:
            data = json.loads(decoded)
            result["json_type"] = type(data).__name__
            if isinstance(data, list):
                result["records"] = len(data)
                result["fields"] = list(data[0]) if data else []
            elif isinstance(data, dict):
                result["keys"] = list(data)
                for key in ("latitude", "longitude", "elevation", "utc_offset_seconds", "timezone", "hourly_units", "daily_units", "error", "reason", "errors", "inputs"):
                    if key in data and not (key == "inputs" and "id" in data):
                        result[key] = data[key]
                if "inputs" in data and "id" in data:
                    result["input_names"] = list(data["inputs"])
                for key in ("hourly", "daily"):
                    if key in data:
                        table = data[key]
                        result[key] = {"rows": len(table.get("time", [])), "fields": list(table), "nulls": {k: sum(v is None for v in values) for k, values in table.items()}, "first": {k: v[0] if v else None for k, v in table.items()}}
                if isinstance(data.get("outputs"), dict):
                    out = data["outputs"]
                    result["output_keys"] = list(out)
                    if "tmy_hourly" in out:
                        result["tmy_rows"] = len(out["tmy_hourly"])
                        result["tmy_fields"] = list(out["tmy_hourly"][0])
                        result["months_selected"] = out.get("months_selected")
                elif isinstance(data.get("outputs"), list):
                    result["output_count"] = len(data["outputs"])
                    result["datasets"] = [{k: v for k, v in row.items() if k in ("name", "displayName", "availableYears", "metadataLink")} for row in data["outputs"]]
        except (ValueError, TypeError, KeyError) as exc:
            result["parse_error"] = str(exc)
    if decoded.startswith("LOCATION,"):
        rows = list(csv.reader(io.StringIO(decoded)))
        result["epw"] = {"headers": [r[0] for r in rows[:8]], "rows": len(rows) - 8, "field_counts": sorted(set(len(r) for r in rows[8:])), "location": rows[0], "first_timestamp": rows[8][:5], "last_timestamp": rows[-1][:5]}
    if body.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            result["zip_members"] = archive.namelist()
            for name in archive.namelist():
                if name.lower().endswith(".epw"):
                    result["epw"] = summarize(archive.read(name), "text/plain").get("epw")
    return result


def probe(item: tuple[str, str]) -> dict:
    name, endpoint = item
    started = time.monotonic()
    record = {"id": name, "url": endpoint, "observed_at_utc": datetime.now(timezone.utc).isoformat(), "method": "GET"}
    request = urllib.request.Request(endpoint, headers={"User-Agent": "openepw-stage1/0.1 (bounded research probe)"})
    try:
        try:
            response = urllib.request.urlopen(request, timeout=35)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read(5_000_001)
            record.update(status=response.status, final_url=response.url, content_type=response.headers.get("Content-Type", ""), bytes_read=len(body), truncated=len(body) > 5_000_000, sha256=hashlib.sha256(body).hexdigest())
            Path(".local/probes").mkdir(parents=True, exist_ok=True)
            Path(f".local/probes/{name}.body").write_bytes(body)
            record["observations"] = summarize(body, record["content_type"])
    except Exception as exc:
        record["transport_error"] = f"{type(exc).__name__}: {exc}"
    record["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", choices=PROBES)
    parser.add_argument("--output", type=Path, default=Path(".local/probe-report.json"))
    args = parser.parse_args()
    selected = {k: v for k, v in PROBES.items() if not args.only or k in args.only}
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(probe, selected.items()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    for record in records:
        print(record["id"], record.get("status", record.get("transport_error")), record.get("bytes_read"), record["elapsed_seconds"])
