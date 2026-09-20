import hashlib
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlparse

from ..epw import read_epw
from ..models import Candidate, OpenEPWError, SourceRef, VariableLineage
from .base import ProviderResult
from .openmeteo import VARIABLES

ROOT = "https://climate.onebuilding.org/"


def catalog_links(html, base):
    links = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                url = urljoin(base, dict(attrs).get("href", ""))
                if urlparse(url).netloc == "climate.onebuilding.org" and urlparse(
                    url
                ).path.lower().endswith(".zip"):
                    links.append(url)

    Parser().feed(html)
    return list(dict.fromkeys(links))


def extract_epw(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for item in archive.infolist():
                path = PurePosixPath(item.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or ":" in item.filename:
                    raise ValueError("unsafe member")
            members = [i for i in archive.infolist() if i.filename.lower().endswith(".epw")]
            if len(members) != 1 or members[0].file_size > 5_000_000:
                raise ValueError("ambiguous or oversized")
            return archive.read(members[0])
    except (ValueError, zipfile.BadZipFile, RuntimeError):
        raise OpenEPWError(
            "MALFORMED_RESPONSE", "Native archive has invalid, unsafe or ambiguous EPW members"
        ) from None


class OneBuildingProvider:
    name = "onebuilding"

    def discover(self, request, location, http):
        if request.product not in ("tmy", "tmyx", "published"):
            return []
        if request.product_id:
            urls = [urljoin(ROOT, request.product_id)]
        elif request.dataset and location.name:
            base = urljoin(ROOT, request.dataset)
            if urlparse(base).netloc != "climate.onebuilding.org" or not base.endswith(
                (".html", "/")
            ):
                raise OpenEPWError(
                    "INVALID_REQUEST", "OneBuilding dataset must be a relative country catalog path"
                )
            urls = [
                u
                for u in catalog_links(http.get(base).decode("utf-8", errors="replace"), base)
                if re.sub(r"\W", "", location.name).lower()
                in re.sub(r"\W", "", u.rsplit("/", 1)[-1]).lower()
            ]
        else:
            return []
        candidates = []
        for url in urls:
            parsed = urlparse(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "climate.onebuilding.org"
                or parsed.query
                or parsed.fragment
                or not parsed.path.endswith(".zip")
                or ".." in parsed.path.split("/")
            ):
                raise OpenEPWError(
                    "INVALID_REQUEST",
                    "OneBuilding product must be a published ZIP on climate.onebuilding.org",
                )
            candidates.append(
                Candidate(
                    id="onebuilding:"
                    + hashlib.sha256(url.encode()).hexdigest()[:16]
                    + ":"
                    + location.key,
                    location_id=location.key,
                    product_id=parsed.path.lstrip("/"),
                    source=SourceRef(
                        provider=self.name,
                        dataset="OneBuilding published EPW",
                        identity=parsed.path,
                        license="Redistribution permission unverified; local retrieval only",
                        citation=url,
                    ),
                    weather_types=["tmy", "tmyx", "published"],
                    variables=list(VARIABLES.values()),
                    interval_minutes=60,
                    warnings=[
                        "Original station location preserved; no relocation to requested point",
                        "Redistribution terms unverified; do not mirror downloaded files",
                    ],
                )
            )
        return candidates

    def fetch(self, task, http):
        url = urljoin(ROOT, task.parameters["product_id"])
        if urlparse(url).netloc != "climate.onebuilding.org" or urlparse(url).query:
            raise OpenEPWError("INVALID_REQUEST", "Unapproved OneBuilding endpoint")
        raw = http.get(url)
        native = extract_epw(raw)
        data = read_epw(native)
        source = task.source.model_copy(update={"location": data.location, "provisional": False})
        sha = hashlib.sha256(raw).hexdigest()
        data.lineage = {
            str(name): VariableLineage(
                variable=name, source=source, raw_sha256=sha, transforms=["published native EPW"]
            )
            for name in data.data
            if name != "flags"
        }
        data.metadata = {
            "product_id": task.parameters["product_id"],
            "native_epw_sha256": hashlib.sha256(native).hexdigest(),
            "source_row_years": "Preserved native labels; not actual-year availability",
        }
        return ProviderResult(data, source, raw, native)
