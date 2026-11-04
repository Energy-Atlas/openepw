"""Reading a correction typed on the plan review or request summary (owner, 2026-11-04).

The browser no longer shows a Change button per part there; the person writes what to change
("2019 instead", "add NSRDB", "remove CDS", "use Boston instead", "change the years") and the
host reads it here. A revision names the part, the new value in the person's words (empty when
they only named the part) and, for products, whether to add, remove or replace. Text this reader
does not understand is left to the model (agent mode) or the usual guided rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from .state import Part
from .text import read_product, reads_as_question, written_years

Action = Literal["set", "add", "remove"]

_POLITE = re.compile(r"^(?:(?:please|ok|okay|hmm|actually|sorry|so|and|but|then)[,\s]+|(?:can|could|would) you\s+"
                     r"|i(?:'d| would) (?:like|prefer) to\s+|i (?:want|need) to\s+|let'?s\s+)+", re.I)
_LEAD = re.compile(r"^(?:change|switch|swap|set|make|move|use|try|replace|update|edit|revise|correct|fix|pick"
                   r"|choose|go with)\b\s*", re.I)
_ADD = re.compile(r"^(?:also\s+)?(?:add|include)\b\s*(?:also\s+)?", re.I)
_REMOVE = re.compile(r"^(?:remove|drop|exclude|delete|skip|without|leave out)\b\s*", re.I)
_DETERMINER = re.compile(r"^(?:the|my|a|an|it|another|other|different|new|wrong)\b\s*", re.I)
_PARTS: tuple[tuple[Part, str], ...] = (
    ("place", r"places?|locations?|sites?|city|town|points?|coordinates"),
    ("years", r"years?|period|dates?"),
    ("products", r"products?|sources?|datasets?|data sets?|providers?"),
    ("preference", r"(?:weather |product )?(?:type|kind)"),
)
_CONNECTOR = re.compile(r"^(?:to|with|for|as|into|:|=)\s*", re.I)
_TAIL = re.compile(r"\s*\b(?:instead|please|then|thanks|thank you)\b\s*$", re.I)
_INSTEAD_OF = re.compile(r"\s+instead of\b.*$|\s+rather than\b.*$|\s+not\s+\d{4}\b.*$", re.I)

# Source names as people write them, folded onto the words offer ids and labels use.
_ALIASES = ((r"open[\s-]?meteo", "openmeteo"), (r"era\s?5[\s-]?land", "era5land"), (r"\bera\s?5\b", "era5"),
            (r"copernicus", "cds"), (r"\bisd\b", "noaa"), (r"one\s?building", "onebuilding"))
_FILLER = {"and", "or", "the", "on", "from", "via", "with", "data", "actual", "year", "years", "weather",
           "product", "products", "source", "sources", "dataset", "datasets", "too", "also", "a", "an"}


@dataclass(frozen=True)
class Revision:
    part: Part | None          # None: a bare value; the host decides (a product name or a place)
    value: str
    action: Action = "set"
    explicit: bool = False     # the person named the part ("change the years")


def read_revision(text: str) -> Revision | None:
    """The change a short correction asks for, or None for anything else (a question, a
    sentence the host should not guess at)."""
    text = text.strip().strip(" .!")
    if re.match(r"(?:please\s+)?(?:can|could|would) you\b", text, re.I):
        text = text.rstrip(" ?")                       # "can you use 2020 instead?" asks for a change
    rest = _POLITE.sub("", text).strip()
    if not rest or reads_as_question(rest):
        return None
    rest = _INSTEAD_OF.sub("", rest)
    edits: tuple[tuple[re.Pattern[str], Action], ...] = ((_ADD, "add"), (_REMOVE, "remove"))
    for edit, action in edits:
        match = edit.match(rest)
        if match:
            value = _TAIL.sub("", rest[match.end():]).strip(" ,.")
            value = re.sub(r"^(?:the\s+)?(?:products?|sources?)\s*", "", value, flags=re.I)
            return Revision("products", value, action, explicit=True) if value else None
    led = bool(_LEAD.match(rest))
    rest = _LEAD.sub("", rest)
    rest = _DETERMINER.sub("", rest)
    part: Part | None = None
    for name, pattern in _PARTS:
        match = re.match(rf"(?:{pattern})\b\s*", rest, re.I)
        if match:
            part, rest = name, rest[match.end():]
            break
    instead = bool(_TAIL.search(text)) or bool(_INSTEAD_OF.search(text))
    value = _TAIL.sub("", _CONNECTOR.sub("", rest)).strip(" ,.")
    if part is not None:
        return Revision(part, value, explicit=True)
    if not value:
        return None
    leftover = re.sub(r"\b(?:\d{4}|to|and|through|until)\b|[\s,&\-–]", "", value, flags=re.I)
    if written_years(value) and not leftover:
        return Revision("years", value)               # "2019", "2018-2020", "2018 and 2019"
    if read_product(value):
        return Revision("preference", value)
    if led or instead:
        return Revision(None, value)                  # "use NSRDB instead", "use Boston instead"
    return None


def _words(text: str) -> set[str]:
    folded = text.lower()
    for pattern, word in _ALIASES:
        folded = re.sub(pattern, word, folded)
    return {word for word in re.split(r"[^a-z0-9]+", folded) if word} - _FILLER


def match_offers(value: str, offers: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Offers each named source matches, or None when any name matches no offer.

    "NSRDB" matches every NSRDB offer, "ERA5 on CDS" only ERA5 from Copernicus; several names are
    separated by "and" or commas.
    """
    found: list[dict[str, Any]] = []
    for name in re.split(r"\s*(?:,|\band\b|\bplus\b|&)\s*", value, flags=re.I):
        wanted = _words(name)
        if not wanted:
            continue
        matches = [offer for offer in offers if wanted <= _words(f"{offer['id']} {offer['label']}")]
        if not matches:
            return None
        found += [offer for offer in matches if offer not in found]
    return found or None
