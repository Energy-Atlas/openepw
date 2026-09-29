"""GeoNames city dumps as the source for descriptive place sets.

Files are downloaded once into the data root, recorded with SHA-256, size and retrieval
time, and verified on every read. GeoNames data is CC BY 4.0 and provided as is.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from ..models import OpenEPWError, utcnow
from .models import PlaceRow, PlaceSetQuery, PlaceSetResult, RegionMatch

BASE_URL = "https://download.geonames.org/export/dump/"
MAX_FILE_BYTES = 30_000_000
COUNTRY_ALIASES = {"usa": "US", "u.s.": "US", "u.s.a.": "US", "united states of america": "US",
                   "uk": "GB", "britain": "GB", "great britain": "GB"}


def _cities_file(query: PlaceSetQuery) -> str:
    """The smallest dump that is complete for the request (capitals need first-level seats)."""
    if query.kind == "capital":
        return "cities5000.zip"                         # all PPLA seats are included here
    minimum = query.min_population or 0              # set for every city query
    if minimum >= 15000:
        return "cities15000.zip"
    return "cities5000.zip" if minimum >= 5000 else "cities1000.zip"


class GeoNamesStore:
    def __init__(self, root: str | Path, http):
        self.root = Path(root)
        self.http = http
        self._cities: dict[str, list[list[str]]] = {}

    @property
    def _manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def _manifest(self) -> dict:
        if self._manifest_path.exists():
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        return {"files": {}}

    def _file(self, name: str) -> tuple[bytes, dict]:
        manifest = self._manifest()
        path = self.root / name
        entry = manifest["files"].get(name)
        if entry and path.exists():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise OpenEPWError("SNAPSHOT_CHECKSUM", f"Cached GeoNames {name} does not match its recorded checksum")
            return raw, entry
        raw = self.http.get(BASE_URL + name, limit=MAX_FILE_BYTES)
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(raw)
        temporary.replace(path)
        entry = {"url": BASE_URL + name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
                 "retrieved_at": utcnow()}
        manifest["files"][name] = entry
        self._manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return raw, entry

    def _lines(self, name: str) -> list[list[str]]:
        text = self._file(name)[0].decode("utf-8")
        return [line.split("\t") for line in text.splitlines() if line and not line.startswith("#")]

    def countries(self) -> dict[str, str]:
        return {row[0]: row[4] for row in self._lines("countryInfo.txt") if len(row) > 4}

    def admin1(self) -> dict[str, str]:
        return {row[0]: row[1] for row in self._lines("admin1CodesASCII.txt") if len(row) > 1}

    def resolve_region(self, text: str) -> list[RegionMatch]:
        """Every country or first-level division the text could mean; several means ask."""
        norm = text.strip().casefold().removeprefix("the ").strip()
        countries = self.countries()
        iso3 = {row[1].casefold(): row[0] for row in self._lines("countryInfo.txt") if len(row) > 4}
        matches: list[RegionMatch] = []
        code = COUNTRY_ALIASES.get(norm) or iso3.get(norm) or next(
            (iso for iso, name in countries.items() if name.casefold() == norm or iso.casefold() == norm), None)
        if code:
            matches.append(RegionMatch(country=code, label=countries[code]))
        for key, name in self.admin1().items():
            country, _, admin = key.partition(".")
            if name.casefold() == norm and country in countries:
                matches.append(RegionMatch(country=country, admin1=admin, label=f"{name}, {countries[country]}"))
        return matches

    def _city_rows(self, name: str) -> list[list[str]]:
        if name not in self._cities:
            raw = self._file(name)[0]
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                member = name.replace(".zip", ".txt")
                text = archive.read(member).decode("utf-8")
            self._cities[name] = [line.split("\t") for line in text.splitlines() if line]
        return self._cities[name]

    def query(self, query: PlaceSetQuery) -> PlaceSetResult:
        countries, admin1 = self.countries(), self.admin1()
        if query.country not in countries:
            raise OpenEPWError("UNKNOWN_REGION", f"GeoNames has no country {query.country}")
        if query.admin1 and f"{query.country}.{query.admin1}" not in admin1:
            raise OpenEPWError("UNKNOWN_REGION", f"GeoNames has no division {query.country}.{query.admin1}")
        name = _cities_file(query)
        matching = []
        for row in self._city_rows(name):
            if row[8] != query.country or (query.admin1 and row[10] != query.admin1):
                continue
            population = int(row[14] or 0)
            if query.kind == "capital" and row[7] != "PPLA":
                continue
            if query.kind == "city" and population < (query.min_population or 0):
                continue
            matching.append((population, row))
        matching.sort(key=lambda item: (-item[0], item[1][1]))
        def region(row):
            division = admin1.get(f"{row[8]}.{row[10]}")
            return f"{division}, {countries[row[8]]}" if division else countries[row[8]]

        rows = [PlaceRow(index=index, input=row[1], status="resolved", name=row[1], lat=float(row[4]),
                         lon=float(row[5]), source="geonames", population=population, region=region(row),
                         source_id=row[0])
                for index, (population, row) in enumerate(matching[:query.limit], start=1)]
        entry = self._manifest()["files"][name]
        return PlaceSetResult(rows=rows, total_matching=len(matching), truncated=len(matching) > query.limit,
                              source_file=name, source_sha256=entry["sha256"], retrieved_at=entry["retrieved_at"])
