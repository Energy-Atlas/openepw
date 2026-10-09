"""Guards fixed in code: input normalisation and cleaning of outside text the model reads.

Outside text (place and station names, EPW header fields, filenames, provider messages) can
carry instructions or links planted by whoever wrote it. Before the model sees it, links,
email addresses and hidden characters are removed and each value is cut to a length limit.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Control, format (zero-width, bidirectional overrides), private-use and surrogate characters.
# Zero-width joiners and non-joiners stay: emoji sequences and several scripts need them.
_HIDDEN = {"Cc", "Cf", "Co", "Cs"}
_KEEP = {"\n", "\t", "\u200c", "\u200d"}
# Links with a scheme or www (any case), and bare lowercase domains such as evil.com or bit.ly/x.
# Station and file names such as Denver.CO or Ithaca.Tompkins.Co.725155 are not lowercase domains.
_LINK = re.compile(
    r"(?i:\b(?:https?|ftp)://\S+|\bwww\.\S+)"
    r"|(?<![\w.])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|xyz|ru|cn|info|biz|co|app|dev|me|ly|"
    r"link|click|top|site|online|example)\b(?:/\S*)?")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_IDENTIFIER = re.compile(r"(?:^|_)(?:id|ids|hash|key|sha256|digest|uri)$")
REMOVED = "[removed]"


def normalize_input(text: str) -> str:
    """Remove characters that hide or reorder text (control, zero-width, bidirectional)."""
    return "".join(char for char in text if char in _KEEP or unicodedata.category(char) not in _HIDDEN)


def clean_external(value: str, max_chars: int) -> str:
    """Outside text for the model: no links, emails or hidden characters; at most max_chars."""
    text = _EMAIL.sub(REMOVED, normalize_input(value))
    text = _LINK.sub(REMOVED, text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text if len(text) <= max_chars else text[:max_chars - 1].rstrip() + "…"


def clean_tool_data(value: Any, max_chars: int, key: str = "") -> Any:
    """Clean every string in tool data except identifiers (ids, hashes, keys, URIs)."""
    if isinstance(value, dict):
        return {name: clean_tool_data(item, max_chars, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [clean_tool_data(item, max_chars, key) for item in value]
    if isinstance(value, str):
        if _IDENTIFIER.search(key):
            return normalize_input(value)
        return clean_external(value, max_chars)
    return value


# Vocabulary that marks a reply as about weather, climate data or building energy modelling.
DOMAIN_TERMS = (
    "weather", "climat", "meteorolog", "epw", "tmy", "amy", "actual year", "actual-year", "typical year",
    "historical", "solar", "irradiance", "radiation", "insolation", "dni", "ghi", "dhi", "temperature",
    "dry-bulb", "dry bulb", "dew point", "humidity", "psychrometric", "enthalpy", "wind", "pressure",
    "precipitation", "rain", "snow", "cloud", "sky", "albedo", "degree day", "degree-day", "hdd", "cdd",
    "design day", "design condition", "energyplus", "openstudio", "doe-2", "trnsys", "esp-r",
    "building energy", "energy model", "energy simulation", "simulation", "hvac", "heating", "cooling",
    "load", "ashrae", "iwec", "cwec", "era5", "nsrdb", "noaa", "pvgis", "onebuilding", "open-meteo",
    "copernicus", "reanalysis", "station", "location", "latitude", "longitude", "coordinates",
    "time zone", "timezone", "standard time", "offset", "hourly", "qc", "quality", "missing hours",
)
_DOMAIN = re.compile("|".join(re.escape(term) for term in DOMAIN_TERMS), re.I)


def off_topic(text: str, *, enabled: bool, min_chars: int, extra_terms: list[str],
              names: list[str]) -> bool:
    """True for a long reply with no weather or modelling vocabulary and none of the session's names."""
    if not enabled or len(text) <= min_chars or _DOMAIN.search(text):
        return False
    lowered = text.lower()
    return not any(term.lower() in lowered for term in [*extra_terms, *names] if len(term) >= 3)


def _host(link: str) -> str:
    match = re.match(r"(?:[a-z][a-z0-9+.-]*://)?([^/\s:?#]+)", link, re.I)
    host = (match.group(1) if match else link).lower()
    return host[4:] if host.startswith("www.") else host


def filter_links(text: str, links: Any) -> tuple[str, bool]:
    """Apply a link policy (allowlist, strip_all or keep) to model text; report whether any went."""
    if links.policy == "keep":
        return text, False
    removed = False

    def replace(match: re.Match[str]) -> str:
        nonlocal removed
        link = match.group(0)
        trail = re.search(r"[.,;:!?)\]]+$", link)
        core, tail = (link[:trail.start()], trail.group(0)) if trail else (link, "")
        host = _host(core)
        if links.policy == "allowlist" and any(host == domain or host.endswith("." + domain)
                                               for domain in links.allowlist):
            return link
        removed = True
        return "[link removed]" + tail

    return _LINK.sub(replace, text), removed


# Simulation-ready claims (fixed in code; AGENTS.md: never call an EPW simulation-ready).
_READY = re.compile(r"simulation[-_ ]ready|ready for (?:energy ?plus|energy simulation|simulation)", re.I)
_NEGATED_BEFORE = re.compile(r"\b(?:not|never|isn't|aren't|cannot|can't|no longer)\b(?:\s+[\w-]+){0,2}"
                             r"\s*[(`'\"]*$", re.I)
_NEGATED_AFTER = re.compile(r"[`'\"]?\s*(?:=|:|is)\s*`?false", re.I)
READINESS_CORRECTION = ("(Correction from openepw: EPW files are not certified simulation-ready; every "
                        "output records simulation_ready=false. Review QC before simulation.)")


def claims_ready(text: str) -> bool:
    """True when the text says an EPW is simulation-ready without negating it next to the claim."""
    for match in _READY.finditer(text):
        before = text[max(0, match.start() - 40):match.start()]
        after = text[match.end():match.end() + 12]
        if not (_NEGATED_BEFORE.search(before) or _NEGATED_AFTER.match(after)):
            return True
    return False
