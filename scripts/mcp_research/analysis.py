"""Offline inventory normalization. Outputs are research evidence, not availability promises."""

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .archives import directory_location, member_names, membership_summary, site_years
from .collector import atomic_json
from .coordinates import coordinate_matches, spreadsheet_rows
from .reviews import annotate, load_registry
from .sources import LOCATIONS, PROVIDERS, VARIABLES


def coordinate_diagnostics(matches, history):
    """Account for product rows, keeping rejected candidate evidence local."""
    by_id = defaultdict(list)
    for site in history:
        by_id[site["id"][:6]].append(site)
    unknown, reasons, families = [], Counter(), Counter()
    for row in sorted(matches, key=lambda r: r["url"]):
        product = row.get("product", "unknown")
        family = next(
            (
                f
                for f in ("US.Normals", "TMY3", "TMYx", "TMY2", "TMY")
                if product == f or product.startswith(f + ".")
            ),
            product,
        )
        families[family] += 1
        if row["coordinate_basis"] != "unknown":
            continue
        raw = by_id.get(row.get("station_id"), [])
        expected = {"USA": "US", "GBR": "UK", "AUS": "AS"}.get(row.get("country"))
        if row.get("reason") == "conflicting_published_coordinates":
            reason = "conflicting_published_coordinates"
        elif not row.get("station_id"):
            reason = "unrecognized_product_identifier"
        elif not raw:
            reason = "no_coordinate_bearing_identifier"
        elif not any(s.get("country") == expected for s in raw):
            reason = "country_code_ambiguous_or_conflicting"
        elif not row.get("noaa_candidates"):
            reason = "name_not_corroborated"
        else:
            reason = "ambiguous_station_identity"
        reasons[reason] += 1
        unknown.append(
            {
                **row,
                "primary_reason": reason,
                "unresolved_reasons": [reason],
                "identifier_candidates": raw,
            }
        )
    return {
        "product_count": len(matches),
        "coordinate_counts": dict(sorted(Counter(r["coordinate_basis"] for r in matches).items())),
        "unresolved_reason_counts": dict(sorted(reasons.items())),
        "product_family_counts": dict(sorted(families.items())),
        "unresolved_products": unknown,
    }


def coordinate_transitions(before, after):
    def indexed(rows):
        output = {}
        for row in rows:
            if row["url"] in output and output[row["url"]] != row:
                raise ValueError("Conflicting product records")
            output[row["url"]] = row
        return output

    old, new = indexed(before), indexed(after)
    counts, changes = Counter(), []
    for url in sorted(old.keys() & new.keys()):
        previous, current = old[url]["coordinate_basis"], new[url]["coordinate_basis"]
        counts[f"{previous} -> {current}"] += 1
        if previous != current:
            changes.append(
                {
                    "url": url,
                    "previous_basis": previous,
                    "current_basis": current,
                    "previous_reason": old[url].get("reason"),
                    "current_reason": new[url].get("reason"),
                }
            )
    return {
        "counts": dict(sorted(counts.items())),
        "changes": changes,
        "added": sorted(new.keys() - old.keys()),
        "removed": sorted(old.keys() - new.keys()),
    }


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
                "country": r.get("CTRY"),
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


def cmip_license_scope(combinations, model_licenses):
    """Screen catalog models once against the saved WCRP effective-license registry."""
    allowed_ids = {"CC BY 4.0", "CC BY-SA 4.0", "CC0 1.0"}
    counts = Counter(pair["model"] for pair in combinations)
    models = {}
    for model, count in sorted(counts.items()):
        record = model_licenses.get(model)
        info = record if isinstance(record, dict) else {}
        license_id = info.get("id")
        models[model] = {
            "gate": "allowed" if license_id in allowed_ids else "unknown",
            "combination_count": count,
            "effective_license": {
                key: info.get(key)
                for key in ("id", "url", "history", "license", "source_specific_info")
            },
        }
    return {
        "evidence_ids": ["cmip6-catalog", "cmip6-license"],
        "model_counts": dict(sorted(Counter(m["gate"] for m in models.values()).items())),
        "combination_counts": {
            gate: sum(m["combination_count"] for m in models.values() if m["gate"] == gate)
            for gate in ("allowed", "unknown")
        },
        "models": models,
        "meaning": "Effective model-license policy screen only; original store terms and requested windows remain separate",
    }


def station_counts(raw):
    """NOAA monthly report counts, not distinct hours, variable availability or QC."""
    months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    rows = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"USAF", "WBAN", "YEAR", *months} <= set(rows.fieldnames or []):
        raise ValueError("Missing NOAA inventory fields")
    index, year_counts = {}, {}
    count, zero_months = 0, 0
    for row in rows:
        if not re.fullmatch(r"[A-Z0-9]{6}", row["USAF"]) or not re.fullmatch(r"\d{5}", row["WBAN"]):
            raise ValueError("Invalid NOAA station identity")
        year = str(int(row["YEAR"]))
        values = [int(row[m]) for m in months]
        if not 1800 <= int(year) <= 2200 or any(v < 0 for v in values):
            raise ValueError("Invalid NOAA year/count")
        station = row["USAF"] + row["WBAN"]
        years = index.setdefault(station, {})
        if year in years:
            if years[year] != values:
                raise ValueError("Conflicting station/year inventory entries")
            continue
        years[year] = values
        year_counts[year] = year_counts.get(year, 0) + 1
        count += 1
        zero_months += sum(v == 0 for v in values)
    return {
        "count": count,
        "station_count": len(index),
        "station_years": index,
        "year_counts": dict(sorted(year_counts.items())),
        "months": months,
        "zero_report_months": zero_months,
        "hourly_completeness": "unknown",
        "variable_completeness": "unknown",
        "evidence_basis": "inventory",
        "meaning": "Counts of reports, not distinct valid hours; zero or absent entries are not proof of all-source unavailability",
    }


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
    ledger_bytes = path.read_bytes() if path.exists() else None
    ledger = json.loads(ledger_bytes) if ledger_bytes is not None else {"records": []}
    result = {
        "schema_version": "mcp-research-1",
        "ledger_sha256": hashlib.sha256(ledger_bytes).hexdigest() if ledger_bytes is not None else None,
        "source_checksums": {
            r["id"]: r["sha256"] for r in ledger["records"] if r["outcome"] == "saved"
        },
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
            elif r["provider"] == "noaa" and r["url"].endswith("/isd-inventory.csv"):
                result["inventories"][r["id"]] = station_counts(raw)
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
                    **membership_summary(
                        names,
                        {
                            s["id"]
                            for s in result["inventories"].get("oedi-sites", {}).get("sites", [])
                        },
                        "RCP4.5" if r["archive"] == "rcp45" else "RCP8.5",
                    ),
                }
            elif r["provider"] == "oedi" and r["id"].endswith("-tail"):
                total = int(r["headers"]["content-range"].split("/")[-1])
                result["inventories"][r["id"]] = {
                    **directory_location(raw, total),
                    "archive_bytes": total,
                    "membership": "unknown until complete directory parsed",
                }
            elif r["provider"] == "onebuilding" and r["url"].endswith(".xlsx"):
                result["inventories"][r["id"]] = spreadsheet_rows(raw, r["id"])
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
                            k: info.get("license_info", {}).get(k)
                            for k in ("id", "url", "history", "license", "source_specific_info")
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
    cmip_catalog = result["inventories"].get("cmip6-catalog")
    cmip_registry = result["inventories"].get("cmip6-license")
    if cmip_catalog and cmip_registry:
        cmip_catalog["license_scope"] = cmip_license_scope(
            cmip_catalog["combinations"], cmip_registry["licenses"]
        )
    history = result["inventories"].get("noaa-history", {}).get("sites", [])
    if history:
        coordinate_ids = {site["id"] for site in history}
        for inventory in result["inventories"].values():
            if "station_years" in inventory:
                ids = set(inventory["station_years"])
                inventory["stations_with_history_coordinates"] = len(ids & coordinate_ids)
                inventory["stations_without_history_coordinates"] = len(ids - coordinate_ids)
                inventory["selected_2024_counts"] = {
                    m["source_id"]: inventory["station_years"].get(m["source_id"], {}).get("2024")
                    for m in result.get("batch_example", {}).get("mappings", [])
                    if m["source_id"]
                }
    published = [row for inv in result["inventories"].values() for row in inv.get("rows", [])]
    baseline, baseline_sha = {}, None
    baseline_path = root / "coordinate-baseline.json"
    if baseline_path.exists():
        try:
            raw_baseline = baseline_path.read_bytes()
            baseline_sha = hashlib.sha256(raw_baseline).hexdigest()
            data = json.loads(raw_baseline)
            current_checksums = {
                r["id"]: r.get("sha256") for r in ledger["records"] if r["outcome"] == "saved"
            }
            if any(current_checksums.get(k) != v for k, v in data["source_checksums"].items()):
                raise ValueError("Baseline source mismatch")
            baseline = data["catalogs"]
        except (ValueError, KeyError, TypeError):
            result["errors"].append(
                {"id": "coordinate-baseline", "outcome": "parse_or_checksum_failure"}
            )
    for key in ("onebuilding-us", "onebuilding-uk", "onebuilding-au"):
        inventory = result["inventories"].get(key)
        if not inventory:
            continue
        matches = coordinate_matches(
            [u for u in inventory["links"] if u.endswith(".zip")], history, published
        )
        matches = annotate(
            matches,
            published,
            {
                r["id"]: r.get("sha256")
                for r in ledger["records"]
                if r["outcome"] == "saved" and r["id"] in result["inventories"]
            },
            load_registry(),
        )
        inventory["accepted_review_counts"] = dict(
            sorted(Counter(m["review"]["status"] for m in matches if "review" in m).items())
        )
        inventory["accepted_review_examples"] = []
        for status in inventory["accepted_review_counts"]:
            inventory["accepted_review_examples"].extend(
                {"url": m["url"], "review": m["review"]}
                for m in [m for m in matches if m.get("review", {}).get("status") == status][:2]
            )
        inventory["coordinate_matches"] = matches
        inventory.update(coordinate_diagnostics(matches, history))
        if key in baseline:
            try:
                transitions = coordinate_transitions(baseline[key], matches)
                inventory["coordinate_transition_details"] = transitions
                inventory["coordinate_transition_counts"] = transitions["counts"]
                inventory["added_product_count"] = len(transitions["added"])
                inventory["removed_product_count"] = len(transitions["removed"])
                inventory["coordinate_baseline_sha256"] = baseline_sha
            except (ValueError, KeyError, TypeError):
                result["errors"].append({"id": key, "outcome": "coordinate_baseline_conflict"})
        # Primary reasons partition unresolved products; full candidates remain local.
        inventory["unresolved_examples"] = []
        for reason in inventory["unresolved_reason_counts"]:
            inventory["unresolved_examples"].extend(
                {k: r.get(k) for k in ("url", "name", "station_id", "product", "primary_reason")}
                for r in [
                    r for r in inventory["unresolved_products"] if r["primary_reason"] == reason
                ][:2]
            )
        inventory["coordinate_counts"] = {
            basis: sum(m["coordinate_basis"] == basis for m in matches)
            for basis in (
                "published_product_index",
                "station_identifier_and_name",
                "station_coordinate_consensus",
                "unknown",
            )
        }
        inventory["products_with_coordinate_disagreement"] = sum(
            m["coordinate_disagreement"] for m in matches
        )
        inventory["coordinates"] = (
            "Per-product published-index or identifier/name/country match; unknowns retained; no EPW header verification"
        )
        sample_names = {
            "onebuilding-us": ("Ithaca", "Phoenix"),
            "onebuilding-uk": ("London",),
            "onebuilding-au": ("Sydney",),
        }
        inventory["coordinate_examples"] = [
            next(
                (
                    m
                    for m in matches
                    if name.lower() in m.get("name", "").lower() and m["lat"] is not None
                ),
                None,
            )
            for name in sample_names[key]
        ]
        inventory["coordinate_examples"] = [m for m in inventory["coordinate_examples"] if m]
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
                if k
                not in (
                    "sites",
                    "combinations",
                    "links",
                    "site_years",
                    "station_years",
                    "rows",
                    "coordinate_matches",
                    "unresolved_products",
                    "coordinate_transition_details",
                )
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
