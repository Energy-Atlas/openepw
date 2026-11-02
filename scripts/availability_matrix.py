"""Compare named-product availability at fixed points between two catalog data roots.

Research tooling for availability rounds: both roots are read under the current code, so the
differences are the catalog's (data, footprints), not the code's. Offline.

    python scripts/availability_matrix.py <before data root> <after data root> --out matrix.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openepw.config import RuntimeConfig
from openepw.service import WeatherService

# The 2026-10-27 matrix's 22 places, then places this round's changes reach.
POINTS = {
    "Singapore": (1.29, 103.85), "Sapporo": (43.06, 141.35), "Auckland": (-36.85, 174.76),
    "Honolulu": (21.31, -157.86), "Cape Town": (-33.925, 18.424), "Lisbon": (38.72, -9.14),
    "North Pole region": (89.6, 0.0), "Oslo": (59.91, 10.75), "Toronto": (43.65, -79.38),
    "Sao Paulo": (-23.55, -46.63), "Tokyo": (35.68, 139.69), "Ankara": (39.93, 32.86),
    "Warsaw": (52.23, 21.01), "Seoul": (37.57, 126.98), "Wellington": (-41.29, 174.78),
    "Buenos Aires": (-34.60, -58.38), "Montevideo": (-34.90, -56.19), "Tel Aviv": (32.09, 34.78),
    "Hong Kong": (22.32, 114.17), "Berlin": (52.52, 13.40), "Fresno": (36.74, -119.79),
    "Ithaca": (42.44, -76.50),
    # Phase 6 (2026-11-01): LuxTMY, the CTZ files, a new TMY row, near-shore PVGIS.
    "Luxembourg": (49.61, 6.13), "Alturas CA": (41.49, -120.56), "Kwajalein": (8.73, 167.73),
    "Venice": (45.44, 12.33), "Table Bay": (-33.89, 18.45),
}


def table(root: Path) -> dict[str, dict[str, str]]:
    service = WeatherService(RuntimeConfig(data_root=root))
    rows = {}
    for name, (lat, lon) in POINTS.items():
        for label, years in (("2018", [2018]), ("typical", [])):
            found = service.point_availability(lat, lon, years)
            rows[f"{name} {label}"] = {row["id"]: row["status"] for row in found["products"]}
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before, after = table(args.before), table(args.after)
    changes = {key: {product: [before[key].get(product), status]
                     for product, status in sorted(after[key].items()) if before[key].get(product) != status}
               for key in after}
    changes = {key: value for key, value in changes.items() if value}
    counts = {key: [sum(s != "none" for s in before[key].values()), sum(s != "none" for s in after[key].values())]
              for key in after}
    args.out.write_text(json.dumps({"changes": changes, "counts": counts}, indent=1), encoding="utf-8")
    for key, value in changes.items():
        print(key, value)
    print(f"{len(changes)} of {len(after)} queries changed")


if __name__ == "__main__":
    main()
