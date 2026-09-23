"""Offline inventory normalization. Outputs are research evidence, not availability promises."""

import csv
import hashlib
import io
import json
import math
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .archives import directory_location, member_names, site_years
from .collector import atomic_json
from .sources import LOCATIONS, PROVIDERS, VARIABLES


def date(value):
    value = str(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if re.fullmatch(r"\d{8}", value) else None


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def station_history(raw):
    sites = []
    for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        lat, lon = number(r.get("LAT")), number(r.get("LON"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        sites.append(
            {
                "id": r["USAF"] + r["WBAN"],
                "name": r.get("STATION NAME"),
                "lat": lat,
                "lon": lon,
                "elevation_m": number(r.get("ELEV(M)")),
                "start": date(r.get("BEGIN")),
                "end": date(r.get("END")),
                "temporal_kind": "station_operating_interval",
                "completeness": "unknown",
            }
        )
    return sites


def cmip_intersections(rows):
    groups = {}
    for row in rows:
        if row.get("table_id") != "Amon" or row.get("variable_id") not in VARIABLES:
            continue
        experiment = row.get("experiment_id")
        if experiment not in ("historical", "ssp126", "ssp245", "ssp370", "ssp585"):
            continue
        key = (row["source_id"], row["member_id"], row["grid_label"])
        entries = groups.setdefault(key, {})
        pair = (experiment, row["variable_id"])
        if pair not in entries or row["zstore"] > entries[pair]:
            entries[pair] = row["zstore"]
    result = []
    for (model, member, grid), entries in sorted(groups.items()):
        for scenario in ("ssp126", "ssp245", "ssp370", "ssp585"):
            keys = [(e, v) for e in ("historical", scenario) for v in VARIABLES]
            if all(k in entries for k in keys):
                result.append(
                    {
                        "model": model,
                        "member": member,
                        "grid": grid,
                        "scenario": scenario,
                        "variables": list(VARIABLES),
                        "temporal_coverage": "unknown",
                        "evidence_basis": "inventory",
                        "stores": {f"{e}/{v}": entries[e, v] for e, v in keys},
                    }
                )
    return result


def distance(point, site):
    lat, lon = map(math.radians, point)
    other, olon = math.radians(site["lat"]), math.radians(site["lon"])
    a = (
        math.sin((other - lat) / 2) ** 2
        + math.cos(lat) * math.cos(other) * math.sin((olon - lon) / 2) ** 2
    )
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def map_sites(points, sites, day, radius=100):
    mappings = []
    for occurrence, point in enumerate(points):
        eligible = [
            s
            for s in sites
            if s.get("start")
            and s.get("end")
            and s["start"] <= day <= s["end"]
            and distance(point, s) <= radius
        ]
        chosen = min(eligible, key=lambda s: (distance(point, s), s["id"])) if eligible else None
        mappings.append(
            {
                "occurrence": occurrence,
                "requested": list(point),
                "source_id": chosen["id"] if chosen else None,
                "distance_km": round(distance(point, chosen), 3) if chosen else None,
                "eligibility": "supported" if chosen else "unknown",
                "evidence_basis": "inventory",
                "hourly_completeness": "unknown",
            }
        )
    return {
        "mappings": mappings,
        "unique_sources": len({m["source_id"] for m in mappings if m["source_id"]}),
        "meaning": "Inventory eligibility only; no weather fetched or output equivalence asserted",
    }


def links(raw, base):
    result = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    url = urljoin(base, href)
                    if (
                        urlsplit(url).scheme == "https"
                        and urlsplit(url).hostname == urlsplit(base).hostname
                    ):
                        result.append(url)

    Parser().feed(raw.decode("utf-8", errors="replace"))
    return sorted(set(result))


def read_snapshot(root, record):
    if record["outcome"] != "saved":
        return None
    path = root / "raw" / (record["id"] + ".body")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record.get("sha256"):
        raise ValueError("Snapshot checksum mismatch")
    return raw


def analyze(root):
    path = root / "ledger.json"
    ledger = json.loads(path.read_text()) if path.exists() else {"records": []}
    result = {
        "schema_version": "mcp-research-1",
        "providers": [],
        "inventories": {},
        "errors": [],
        "limitations": [
            "No previous weather runs or QC summaries used",
            "Inventory presence is not hourly completeness",
        ],
    }
    for provider, description in PROVIDERS.items():
        evidence = [r for r in ledger["records"] if r["provider"] == provider]
        result["providers"].append(
            {
                "provider": provider,
                **description,
                "eligibility": "unknown",
                "evidence_ids": [r["id"] for r in evidence if r["outcome"] == "saved"],
                "meaning": "No location/period query evaluated at provider level",
            }
        )
    for r in ledger["records"]:
        try:
            raw = read_snapshot(root, r)
            if raw is None:
                continue
            if r["id"] == "noaa-history":
                sites = station_history(raw)
                result["inventories"][r["id"]] = {"count": len(sites), "sites": sites}
                result["batch_example"] = map_sites(
                    [
                        LOCATIONS["ithaca"],
                        LOCATIONS["ithaca"],
                        LOCATIONS["phoenix"],
                        LOCATIONS["london"],
                        LOCATIONS["sydney"],
                    ],
                    sites,
                    "2024-01-01",
                )
            elif r["id"] == "noaa-inventory":
                rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                result["inventories"][r["id"]] = {
                    "count": len(rows),
                    "columns": list(rows[0]) if rows else [],
                    "meaning": "Report counts are not complete hourly coverage",
                }
            elif r["id"] == "cmip6-catalog":
                pairs = cmip_intersections(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
                result["inventories"][r["id"]] = {"count": len(pairs), "combinations": pairs}
                result["inventories"][r["id"]].update(
                    model_count=len({p["model"] for p in pairs}),
                    scenario_counts={
                        s: sum(p["scenario"] == s for p in pairs)
                        for s in ("ssp126", "ssp245", "ssp370", "ssp585")
                    },
                )
            elif r["id"] == "oedi-sites":
                rows = list(csv.DictReader(io.StringIO(raw.decode("latin-1"))))
                sites = [
                    {
                        "id": row.get("PUMA Number"),
                        "name": row.get("PUMA Name"),
                        "lat": number(row.get("Latitude")),
                        "lon": number(row.get("Longitude")),
                        "elevation_m": number(row.get("Elevation")),
                        "temporal_coverage": "unknown",
                    }
                    for row in rows
                ]
                result["inventories"][r["id"]] = {"count": len(sites), "sites": sites}
            elif r["provider"] == "oedi" and r["id"].endswith("-directory"):
                names = member_names(raw)
                membership = site_years(names)
                result["inventories"][r["id"]] = {
                    "member_count": len(names),
                    "site_count": len(membership),
                    "site_years": membership,
                    "completeness": "unknown",
                    "meaning": "Archive-listed membership only; no EPW content retrieved",
                }
            elif r["provider"] == "oedi" and r["id"].endswith("-tail"):
                total = int(r["headers"]["content-range"].split("/")[-1])
                result["inventories"][r["id"]] = {
                    **directory_location(raw, total),
                    "archive_bytes": total,
                    "membership": "unknown until complete directory parsed",
                }
            elif r["provider"] == "onebuilding":
                urls = links(raw, r["url"])
                result["inventories"][r["id"]] = {
                    "links": urls,
                    "count": len(urls),
                    "zip_product_count": sum(u.endswith(".zip") for u in urls),
                    "reference_periods": sorted(
                        set(re.findall(r"TMYx\.(\d{4}-\d{4})", " ".join(urls)))
                    ),
                    "coordinates": "unknown; selected HTML catalogs expose product names/links",
                    "temporal_kind": "published_product_reference_period",
                }
            elif r["provider"] == "cds":
                data = json.loads(raw)
                if "extent" in data:
                    result["inventories"][r["id"]] = {
                        "dataset": data.get("id"),
                        "extent": data["extent"],
                        "license": data.get("license"),
                        "evidence_basis": "inventory",
                        "caveat": "Catalog bbox and time interval preserved verbatim; not completeness or land-mask proof",
                    }
                elif "inputs" in data:
                    year_schema = data["inputs"]["year"]["schema"]
                    result["inventories"][r["id"]] = {
                        "allowed_years": year_schema.get("items", year_schema).get("enum"),
                        "variables": data["inputs"]["variable"]["schema"]["items"]["enum"],
                        "caveat": "Allowed request values do not prove data for every combination",
                    }
            elif r["provider"] == "pvgis" and r["kind"] == "probe":
                data = json.loads(raw)
                result["inventories"][r["id"]] = {
                    "meteo_data": data.get("inputs", {}).get("meteo_data", {}),
                    "months_selected": data.get("outputs", {}).get("months_selected", []),
                    "temporal_kind": "tmy_reference_period",
                    "evidence_basis": "targeted probe",
                    "location": data.get("inputs", {}).get("location"),
                    "hourly_rows_not_exported": len(data.get("outputs", {}).get("tmy_hourly", [])),
                }
            elif r["provider"] == "cmip6" and r["url"].endswith("/.zmetadata"):
                data = json.loads(raw)["metadata"]
                attrs = data.get(".zattrs", {})
                result["inventories"][r["id"]] = {
                    "attributes": {
                        k: attrs.get(k)
                        for k in (
                            "source_id",
                            "variant_label",
                            "grid_label",
                            "experiment_id",
                            "variable_id",
                            "nominal_resolution",
                            "version_id",
                            "license",
                        )
                    },
                    "time_array": data.get("time/.zarray"),
                    "time_attributes": data.get("time/.zattrs"),
                    "temporal_coverage": "unknown",
                    "caveat": "Array shape/units do not establish actual first/last coordinates or continuity",
                }
            elif r["id"] == "cmip6-license":
                data = json.loads(raw).get("source_id", {})
                result["inventories"][r["id"]] = {
                    "licenses": {
                        model: {
                            k: info.get("license_info", {}).get(k) for k in ("id", "url", "history")
                        }
                        for model, info in data.items()
                    }
                }
            elif r["provider"] == "nsrdb" and r["kind"] == "probe":
                data = json.loads(raw)
                result["inventories"][r["id"]] = {
                    "products": [
                        {
                            "name": row.get("name"),
                            "available_years_or_products": row.get("availableYears"),
                            "intervals": row.get("availableIntervals"),
                        }
                        for row in data.get("outputs", [])
                    ],
                    "evidence_basis": "targeted probe",
                }
        except (ValueError, KeyError, OSError, TypeError):
            result["errors"].append({"id": r["id"], "outcome": "parse_or_checksum_failure"})
    atomic_json(root / "analysis.json", result)
    return result


def report(root):
    result = analyze(root)
    ledger_path = root / "ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"records": []}
    summary = {
        **result,
        "inventories": {
            key: {
                k: v
                for k, v in value.items()
                if k not in ("sites", "combinations", "links", "site_years")
            }
            for key, value in result["inventories"].items()
        },
        "ledger": ledger,
    }
    lines = [
        "# MCP availability research evidence",
        "",
        "Provider-level eligibility remains unknown until a location/period is evaluated.",
        "",
        "| Provider | Products | Evidence snapshots | Adapter boundary |",
        "| --- | --- | --- | --- |",
    ]
    for row in summary["providers"]:
        lines.append(
            f"| {row['provider']} | {row['products']} | {', '.join(row['evidence_ids']) or 'none'} | {row['adapter_boundary']} |"
        )
    lines += [
        "",
        "Raw inventories remain local. No weather completeness is inferred from catalogs.",
        "",
    ]
    atomic_json(root / "evidence.json", summary)
    (root / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
