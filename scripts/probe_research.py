"""Stage 1 source/license and CMIP6 metadata access checks, no third-party code execution."""
import csv
import hashlib
import io
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "pyepwmorph_license": "https://raw.githubusercontent.com/justinfmccarty/pyepwmorph/374d5eec414181dd5a9c184043c574db2d95c3aa/LICENSE",
    "pyepwmorph_psychrometrics": "https://raw.githubusercontent.com/justinfmccarty/pyepwmorph/374d5eec414181dd5a9c184043c574db2d95c3aa/pyepwmorph/tools/ladybug_psychrometrics.py",
    "epwshiftr_revision": "https://api.github.com/repos/ideas-lab-nus/epwshiftr/commits/master",
    "epwshiftr_license": "https://raw.githubusercontent.com/ideas-lab-nus/epwshiftr/master/LICENSE",
    "epwshiftr_description": "https://raw.githubusercontent.com/ideas-lab-nus/epwshiftr/master/DESCRIPTION",
    "psychrolib_license": "https://raw.githubusercontent.com/psychrometrics/psychrolib/master/LICENSE.txt",
    "pvlib_license": "https://raw.githubusercontent.com/pvlib/pvlib-python/main/LICENSE",
    "cdsapi_license": "https://raw.githubusercontent.com/ecmwf/cdsapi/master/LICENSE.txt",
    "energyplus_schema": "https://energyplus.readthedocs.io/en/v26.1.0/auxiliary-programs/auxiliary-programs.html",
    "pangeo_catalog": "https://storage.googleapis.com/cmip6/pangeo-cmip6.json",
    "onebuilding_sources": "https://climate.onebuilding.org/sources/default.html",
    "nsrdb_terms": "https://developer.nlr.gov/terms/",
}


def get(item):
    name, url = item
    record = {"id": name, "url": url, "observed_at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        try:
            response = urllib.request.urlopen(url, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read(2_000_001)
            record.update(status=response.status, bytes_read=len(body), sha256=hashlib.sha256(body).hexdigest())
        Path(".local/research").mkdir(parents=True, exist_ok=True)
        Path(".local/research/" + name).write_bytes(body)
        if name.endswith("revision") and record["status"] == 200:
            record["revision"] = json.loads(body)["sha"]
    except Exception as exc:
        record["error"] = str(exc)
    return record


if __name__ == "__main__":
    with ThreadPoolExecutor(4) as pool:
        records = list(pool.map(get, SOURCES.items()))
    # An unauthenticated tiny CDS retrieval must not be mistaken for a download.
    endpoint = "https://cds.climate.copernicus.eu/api/retrieve/v1/processes/reanalysis-era5-single-levels/execution"
    payload = {"inputs": {"product_type": ["reanalysis"], "variable": ["2m_temperature"], "year": ["2024"], "month": ["01"], "day": ["01"], "time": ["00:00"], "area": [42.5, -76.5, 42.25, -76.25], "data_format": "netcdf", "download_format": "unarchived"}}
    request = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(request, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(10000)
        records.append({"id": "cds_unauthenticated_retrieval", "url": endpoint, "method": "POST", "request": payload, "status": response.status, "observed_at_utc": datetime.now(timezone.utc).isoformat(), "response": body.decode(errors="replace")})
    catalog = json.loads(Path(".local/research/pangeo_catalog").read_bytes())
    csv_url = catalog["catalog_file"]
    found = {}
    scanned = 0
    with urllib.request.urlopen(csv_url, timeout=30) as response:
        lines = io.TextIOWrapper(response, encoding="utf-8")
        for row in csv.DictReader(lines):
            scanned += 1
            if row["table_id"] == "Amon" and row["variable_id"] == "tas" and row["source_id"] == "GFDL-CM4" and row["member_id"] == "r1i1p1f1" and row["experiment_id"] in ("historical", "ssp245"):
                found.setdefault(row["experiment_id"], row)
            if len(found) == 2 or scanned >= 200000:
                break
    for experiment, row in found.items():
        endpoint = row["zstore"].replace("gs://", "https://storage.googleapis.com/").rstrip("/") + "/.zmetadata"
        result = get(("cmip6_" + experiment, endpoint))
        result["catalog_row"] = row
        if result.get("status") == 200:
            meta = json.loads(Path(".local/research/cmip6_" + experiment).read_bytes())["metadata"]
            result["array"] = meta["tas/.zarray"]
            result["variable"] = meta["tas/.zattrs"]
            attrs = meta[".zattrs"]
            result["dataset_attributes"] = {k: v for k, v in attrs.items() if k in ("license", "source_id", "experiment_id", "variant_label", "grid_label", "version", "tracking_id")}
            result["time"] = meta.get("time/.zattrs")
        records.append(result)
    records.append({"id": "cmip6_catalog_scan", "url": csv_url, "rows_scanned": scanned, "experiments_found": list(found)})
    Path("docs/validation/2026-09-20-research.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    for record in records:
        print(record["id"], record.get("status"), record.get("revision", ""))
