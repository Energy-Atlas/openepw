"""Write each installed NSRDB mask's ``gates`` from ``REVIEWED_SOURCES`` (offline).

Gates are recorded in a mask's manifest when it is acquired. When a reviewed source gains a gate
without new data (2026-10-27: the Himawari-7 mask also gates Himawari-8), this updates the
installed manifests; the masks and their checksums are untouched.

    python -m scripts.mcp_availability_map.sync_gates <footprints root>
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.mcp_availability_map.nsrdb_coverage import REVIEWED_SOURCES


def sync(footprints: Path) -> list[str]:
    changed = []
    for path in sorted(Path(footprints).glob("nsrdb/*/*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        updated = False
        for entry in manifest.get("entries", []):
            reviewed = REVIEWED_SOURCES.get((entry.get("product_id"), entry.get("selector_kind"), entry.get("selector")))
            if reviewed and reviewed.gates and entry.get("gates") != list(reviewed.gates):
                entry["gates"] = list(reviewed.gates)
                updated = True
        if updated:
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            changed.append(str(path))
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("footprints", type=Path)
    print(json.dumps({"changed": sync(parser.parse_args().footprints)}))


if __name__ == "__main__":
    main()
