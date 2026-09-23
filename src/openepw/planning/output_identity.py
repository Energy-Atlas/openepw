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
    stem = "openepw-" + "-".join(slug(part) for part in parts if part is not None)
    stem = stem[: 100 - len(suffix) - len("-.epw")].rstrip("-")
    return f"{stem}-{suffix}.epw"


def period_label(start: str, end: str, product: str, product_id: str | None) -> str:
    if start.endswith("-01-01") and end == f"{start[:4]}-12-31":
        return start[:4]
    if start and end:
        return f"{start.replace('-', '')}-{end.replace('-', '')}"
    return product_id or product
