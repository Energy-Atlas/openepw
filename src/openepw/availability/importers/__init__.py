"""Source-specific normalization of verified metadata snapshots."""

from __future__ import annotations

import json

from ..models import CatalogBundle, EvidenceRef
from ..store import CatalogImportError
from .climate import normalize_climate
from .contracts import normalize_contracts


def normalize_analysis(
    inventories: dict,
    evidence: list[EvidenceRef],
    *,
    probe_locations: dict | None = None,
) -> CatalogBundle:
    """Normalize known Stage 1 inventory records without broadening probe scope."""
    known = {item.id for item in evidence}
    contracts = normalize_contracts(inventories, known, probe_locations or {})
    climate = normalize_climate(inventories, {item.id: item for item in evidence})
    return CatalogBundle(
        products=contracts.products + climate.products,
        sites=contracts.sites + climate.sites,
        entries=contracts.entries + climate.entries,
    )


def normalize_source(source: str, raw: bytes, evidence: EvidenceRef) -> CatalogBundle:
    """Normalize a bounded JSON inventory response; unsupported formats remain stale."""
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CatalogImportError("Source metadata is not a supported JSON inventory") from exc
    if not isinstance(parsed, dict):
        raise CatalogImportError("Source metadata must be a JSON object")
    normalized = normalize_analysis({source: parsed}, [evidence])
    normalized.evidence = [evidence]
    return normalized
