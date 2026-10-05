"""Offline reading of chat text: written years, product words, the place part, future requests."""

from __future__ import annotations

import re

# Scenario and pathway names in their usual spellings: SSP585, SSP5-8.5, RCP8.5, RCP 4.5, rcp85.
FUTURE = re.compile(r"\b(?:future|ssp\d{3}|ssp\d(?:-\d\.?\d)?|rcp\s?\d\.?\d|cmip\d"
                    r"|projected|projections?|climate scenarios?)\b", re.I)

_PRODUCTS = (
    ("tmyx", r"\btmyx\b"),
    ("tmy", r"\btmy\d?\b|\btypical (?:meteorological )?year\b"),
    ("published", r"\bpublished\b"),
    ("historical", r"\b(?:historical|amy|actual[- ]year)\b"),
)

# Years, product words, question words and filler removed so the rest is the place text.
# Upper-case IN and AT stay: they are state or country codes ("Fort Wayne, IN", "Graz, AT").
_PLACE_NOISE = re.compile(
    r"\b(?:(?:18|19|20|21)\d{2}(?:\s*(?:-|–|—|to|through)\s*(?:(?:18|19|20|21)\d{2}|\d{2}))?"
    r"|(?:the\s+)?(?:18|19|20|21)\d0s|historical|amy|actual[- ]year|tmyx|tmy\d?"
    r"|typical(?:\s+meteorological)?\s+year|published|epw|weather|data|files?|please"
    r"|get|give me|i need|i want|for|from|between|(?!(?-i:IN|AT)\b)(?:in|at)|near|what(?:'s|\s+is|\s+are)?|which|available"
    r"|options?|sources?|products?|do you have|is there|show me|instead|only|just|use"
    r"|change(?:\s+it)?\s+to|switch to)\b", re.I)


def explicit_weather_years(text: str) -> set[int]:
    """A building count must not turn into a weather year, even if a model proposes it."""
    years = set()
    for match in re.finditer(r"\b(?:18|19|20|21)\d{2}\b", text):
        if not re.match(r"\s+(?:buildings?|people|persons|residents|inhabitants|population)\b",
                        text[match.end():], re.I):
            years.add(int(match.group()))
    for match in re.finditer(r"\b((?:18|19|20|21)\d{2})\s*(?:-|–|—|to|through)\s*"
                             r"((?:18|19|20|21)\d{2}|\d{2})\b", text, re.I):
        start, tail = int(match.group(1)), match.group(2)
        end = int(tail)
        if len(tail) == 2:                 # "2012-18" and "1998-02" abbreviate the end year
            end += start // 100 * 100
            end += 100 if end < start else 0
        if 0 <= end - start <= 30:
            years.update(range(start, end + 1))
    for match in re.finditer(r"\b((?:18|19|20|21)\d)0s\b", text):     # "the 2010s"
        years.update(range(int(match.group(1)) * 10, int(match.group(1)) * 10 + 10))
    return years


def read_product(text: str) -> str | None:
    """The weather product a message names, if any; TMYx wins over TMY."""
    for product, pattern in _PRODUCTS:
        if re.search(pattern, text, re.I):
            return product
    return None


def place_part(text: str) -> str:
    """The place part of a message; newlines are kept because they separate list items."""
    stripped = re.sub(r"[ \t]+", " ", _PLACE_NOISE.sub(" ", text))
    return "\n".join(line.strip(" ,.;:!?") for line in stripped.splitlines()).strip()


def safe_prompt(text: str, *, limit: int = 1000) -> str:
    """Remove credential assignments and absolute paths before model input."""
    text = re.sub(
        r"(?i)\b(?:[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)|"
        r"api[_-]?key|bearer[_-]?token|access[_-]?token|secret|password)"
        r"[\"']?\s*[=:]\s*[\"']?\S+|\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}\b",
        "[redacted]", text,
    )
    text = re.sub(r"[A-Za-z]:\\[^\s]+|/(?:home|Users)/[^\s]+",
                  "[local path]", text)
    return text[:limit]
