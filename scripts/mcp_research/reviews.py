"""Apply explicitly accepted, checksum-pinned research judgments only."""

import json
from collections import defaultdict
from pathlib import Path


def load_registry():
    return json.loads(
        (Path(__file__).parent / "data" / "onebuilding_reviews.json").read_text(encoding="utf-8")
    )


def annotate(matches, published, checksums, registry):
    decisions = {}
    for decision in registry["reviews"]:
        if decision["catalog_url"] in decisions:
            raise ValueError("Duplicate reviewed product")
        decisions[decision["catalog_url"]] = decision
    by_url = defaultdict(list)
    for row in published:
        by_url[row["url"]].append(row)
    output = []
    for original in matches:
        result = dict(original)
        decision = decisions.get(original["url"])
        if decision:
            review = {k: v for k, v in decision.items() if k not in ("lat", "lon", "catalog_url")}
            review.update(
                accepted_on=registry["accepted_on"],
                epw_coordinates_verified=False,
                weather_equivalence_verified=False,
            )
            ids = decision["evidence_ids"]
            if not ids or any(
                not registry["source_checksums"].get(k)
                or checksums.get(k) != registry["source_checksums"][k]
                for k in ids
            ):
                review["status"] = "stale_evidence"
            elif decision["status"] == "reviewed_metadata_match":
                candidates = [
                    r for r in by_url.get(decision["published_url"], []) if r["evidence_id"] in ids
                ]
                points = {(r["lat"], r["lon"], r.get("elevation_m")) for r in candidates}
                if len(points) == 1:
                    review["coordinates"] = dict(
                        zip(("lat", "lon", "elevation_m"), next(iter(points)))
                    )
                else:
                    review["status"] = "unresolved_evidence"
            elif decision["status"] == "approximate_locality":
                review["approximate_location"] = {
                    "lat": decision["lat"],
                    "lon": decision["lon"],
                    "precision": "locality_only",
                    "elevation_m": None,
                }
            elif decision["status"] != "name_code_conflict":
                raise ValueError("Unknown review status")
            result["review"] = review
        output.append(result)
    return output
