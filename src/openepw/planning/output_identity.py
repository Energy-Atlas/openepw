"""Deterministic output identity and filesystem-safe display names."""

import re
import unicodedata

from ..models import Location, digest


def output_id(mapping: dict) -> str:
    return digest(mapping)


def slug(value: object) -> str:
    ascii_text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return (
        re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", ascii_text.lower())).strip("-") or "unknown"
    )


def location_label(location: Location) -> str:
    lat = f"{'n' if location.lat >= 0 else 's'}{abs(location.lat):.3f}".replace(".", "p")
    lon = f"{'e' if location.lon >= 0 else 'w'}{abs(location.lon):.3f}".replace(".", "p")
    coordinates = f"{lat}-{lon}"
    return f"{slug(location.name)}-{coordinates}" if location.name else coordinates


def filename(parts: list[object], identity: str) -> str:
    suffix = identity[:12]
    tokens = [slug(part) for part in parts if part is not None]
    limit = 100 - len(suffix) - len("-.epw")

    def length() -> int:
        return len("openepw-") + sum(map(len, tokens)) + len(tokens) - 1

    # Preserve coordinates and all trailing source/period fields when a place name is long.
    coordinates = re.search(r"-([ns]\d+p\d+-[ew]\d+p\d+)$", tokens[0])
    if coordinates and length() > limit:
        place = tokens[0][: coordinates.start()]
        coordinates_token = tokens[0][coordinates.start() :]
        place = place[: max(3, len(place) - (length() - limit))].rstrip("-")
        tokens[0] = place + coordinates_token
    while length() > limit:
        candidates = [i for i in range(1, len(tokens)) if len(tokens[i]) > 4]
        if not candidates:
            raise ValueError("Too many filename components for semantic output name")
        longest = max(candidates, key=lambda i: len(tokens[i]))
        tokens[longest] = tokens[longest][:-1].rstrip("-")
    stem = "openepw-" + "-".join(tokens)
    return f"{stem}-{suffix}.epw"


def period_label(start: str, end: str, product: str, product_id: str | None) -> str:
    if start in ("", "None") or end in ("", "None"):
        return product_id or product
    if start.endswith("-01-01") and end == f"{start[:4]}-12-31":
        return start[:4]
    if start and end:
        return f"{start.replace('-', '')}-{end.replace('-', '')}"
    return product_id or product
