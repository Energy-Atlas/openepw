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


# Data gaps (planning/gaps.py): "fill solar from Open-Meteo", "leave pressure missing", "ok".
_GAP_GROUPS = (
    ("solar", r"solar|radiation|irradiance|irradiation|insolation|ghi|dni|dhi|sun(?:light|shine)?"),
    ("pressure", r"(?:station |air |atmospheric |barometric )?pressure"),
    ("humidity", r"humidity|dew[\s-]?point|moisture"),
    ("temperature", r"(?:dry[\s-]?bulb\s+)?temperature"),
    ("wind", r"wind"),
    ("short_gaps", r"short gaps?|(?:missing|gap) hours?|hour(?:ly)? gaps?|gaps? (?:inside|in) the (?:station'?s? )?records?"),
)
_GAP_OK = re.compile(r"(?:ok|okay|yes|y|approve[d]?|accept|fine|go|sounds good|looks good|"
                     r"(?:use |take |go with )?(?:the )?recommended(?: ones?| options?| choices?)?)", re.I)
_GAP_LEAVE = re.compile(r"\b(?:leave|keep|skip|ignore|without|no fill|don'?t fill|do not fill)\b|\bmissing\b", re.I)
_GAP_STATION = re.compile(r"\bstation'?s?\b.*\b(?:reports?|pressure|own)\b|\bown (?:pressure )?reports?\b"
                          r"|\baltimeter\b", re.I)
_GAP_CDS = re.compile(r"\b(?:cds|copernicus)\b", re.I)
_GAP_INTERPOLATE = re.compile(r"\binterpolat\w*\b", re.I)
_GAP_OPENMETEO = re.compile(r"open[\s-]?meteo|\bera\s?5|\breanalysis\b", re.I)
_GAP_LAND = re.compile(r"era\s?5[\s-]?land|\bland\b", re.I)
_GAP_SPLIT = re.compile(r"\s*[;,]\s*|\s+and\s+(?=(?:then\s+)?(?:fill|use|leave|take|get|keep|skip|from|interpolat\w*)\b)", re.I)


def read_fill(text: str, *, need_group: bool = False) -> list[tuple[str | None, str]] | None:
    """Gap choices in the person's words: (group or None for every gap, option id), where the
    id is ``recommended``, ``leave_missing``, ``station_reports``, ``interpolate`` (short gaps
    only) or ``source:provider:dataset``.
    None when the text says no such choice. ``need_group`` (on the plan review) requires a group
    word, so "use ERA5 instead" stays a product change."""
    text = _POLITE.sub("", text.strip().strip(" .!")).strip()
    if not text or reads_as_question(text):
        return None
    if _GAP_OK.fullmatch(text):
        return None if need_group else [(None, "recommended")]
    found: list[tuple[str | None, str]] = []
    for clause in _GAP_SPLIT.split(text):
        groups = [group for group, pattern in _GAP_GROUPS if re.search(rf"\b(?:{pattern})\b", clause, re.I)]
        if _GAP_INTERPOLATE.search(clause):          # before "missing": "interpolate the missing hours"
            choice = "interpolate"
            groups = ["short_gaps"]                     # one row covers every non-solar variable
        elif _GAP_STATION.search(clause):
            choice = "station_reports"
            groups = groups or ["pressure"]
        elif _GAP_CDS.search(clause):
            choice = "source:cds:" + ("reanalysis-era5-land" if _GAP_LAND.search(clause)
                                      else "reanalysis-era5-single-levels")
        elif _GAP_OPENMETEO.search(clause):
            choice = "source:openmeteo:" + ("era5_land" if _GAP_LAND.search(clause) else "era5")
        elif _GAP_LEAVE.search(clause):
            choice = "leave_missing"
        else:
            continue
        if need_group and not groups:
            continue
        found += [(group, choice) for group in groups] if groups else [(None, choice)]
    return found or None
