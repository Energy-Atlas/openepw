"""Guards fixed in code: input normalisation and cleaning of outside text the model reads.

Outside text (place and station names, EPW header fields, filenames, provider messages) can
carry instructions or links planted by whoever wrote it. Before the model sees it, links,
email addresses and hidden characters are removed and each value is cut to a length limit.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

# Control, format (zero-width, bidirectional overrides), private-use and surrogate characters.
# Zero-width joiners and non-joiners stay: emoji sequences and several scripts need them.
_HIDDEN = {"Cc", "Cf", "Co", "Cs"}
_KEEP = {"\n", "\t", "\u200c", "\u200d"}
# Links with a scheme, a protocol-relative // or www (any case); any domain followed by a path
# (any case, any top-level domain, e.g. EVIL.COM/fix or goo.gl/x); and bare lowercase domains on
# common top-level domains (evil.com). Station and file names such as Denver.CO or
# Ithaca.Tompkins.Co.725155 have no path and are not lowercase domains, so they stay.
# Full-width and ideographic dots count as dots: browsers read evil。com as evil.com.
_DOTS = "\u3002\uff0e\uff61"
_DOT = "[." + _DOTS + "]"
_LINK = re.compile(
    r"(?i:\b(?:https?|ftp)://\S+|(?<![\w:/])//[\w-]+" + _DOT + r"\S+|\bwww" + _DOT + r"\S+)"
    r"|(?i:(?<![\w.@/" + _DOTS + r"])[a-z0-9-]+(?:" + _DOT + r"[a-z0-9-]+)*" + _DOT
    + r"[a-z][a-z0-9-]{1,23}[/\\]\S*)"
    r"|(?<![\w.@" + _DOTS + r"])[a-z0-9-]+(?:" + _DOT + r"[a-z0-9-]+)*" + _DOT
    + r"(?:com|net|org|io|xyz|ru|cn|info|biz|co|app|dev|me|ly|"
    r"ai|gl|gd|link|click|top|site|online|example)\b(?:/\S*)?")
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
# Whole words (plurals allowed); a trailing * marks a stem. Acronyms match in capitals only, so
# "Amy" or "Gandhi" do not count. Generic words (load, quality, location, cloud) are left out.
DOMAIN_TERMS = (
    "weather", "climat*", "meteorolog*", "actual year", "actual-year", "typical year", "solar",
    "irradian*", "radiation", "insolation", "temperature", "dry-bulb", "dry bulb", "wet-bulb", "wet bulb",
    "dew point", "humidity", "psychrometric", "enthalpy", "wind speed", "wind direction", "air pressure",
    "atmospheric pressure", "barometric", "precipitation", "rainfall", "snowfall", "cloud cover",
    "sky cover", "clear sky", "albedo", "degree day", "degree-day", "design day", "design condition",
    "energyplus", "openstudio", "doe-2", "trnsys", "esp-r", "building energy", "energy model*",
    "energy simulation", "building simulation", "hvac", "heating", "cooling", "ashrae", "iwec", "cwec",
    "reanalysis", "weather station", "latitude", "longitude", "time zone", "timezone", "standard time",
    "utc offset", "hourly", "missing hours", "photovoltaic",
)
ACRONYMS = ("EPW", "TMY", "TMY3", "AMY", "XMY", "DNI", "GHI", "DHI", "HDD", "CDD", "ERA5", "NSRDB", "NOAA",
            "PVGIS", "QC", "UTC", "PV")
NAMED_SOURCES = ("onebuilding", "open-meteo", "copernicus", "nrel", "pvgis", "nsrdb", "noaa")
_DOMAIN = re.compile(
    r"(?i:\b(?:" + "|".join(re.escape(term[:-1]) + r"\w*" if term.endswith("*") else re.escape(term) + "(?:e?s)?"
                           for term in [*DOMAIN_TERMS, *NAMED_SOURCES]) + r")\b)"
    r"|\b(?:" + "|".join(ACRONYMS) + r")s?\b")
DOMAIN_HITS = 2                         # distinct domain words a long reply needs to stay


def _terms(text: str, terms: list[str]) -> set[str]:
    found = {match.group(0).lower() for match in _DOMAIN.finditer(text)}
    for term in terms:
        if len(term) >= 3 and not term.isdigit() and re.search(
                r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I):
            found.add(term.lower())
    return found


def off_topic(text: str, *, enabled: bool, min_chars: int, extra_terms: list[str],
              names: list[str]) -> bool:
    """True for a long reply with fewer than DOMAIN_HITS distinct weather or modelling words.

    Profile terms and the session's place and product names count too (whole words; numbers such
    as years do not).
    """
    if not enabled or len(text) <= min_chars:
        return False
    return len(_terms(text, [*extra_terms, *names])) < DOMAIN_HITS


def link_host(link: str) -> str:
    """The host a browser would open for a link, or "" when it cannot be trusted (userinfo,
    unparsable or non-IDNA hosts). Backslashes count as slashes, as browsers treat them."""
    link = link.replace("\\", "/").translate({ord(dot): "." for dot in _DOTS})
    if not re.match(r"[a-z][a-z0-9+.-]*://", link, re.I):
        link = "//" + link.lstrip("/")
    try:
        parts = urlsplit(link)
        host = parts.hostname or ""
    except ValueError:
        return ""
    if "@" in parts.netloc or not host:
        return ""
    try:
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return ""
    return host[4:] if host.startswith("www.") else host


def link_allowed(link: str, allowlist: list[str]) -> bool:
    host = link_host(link)
    return bool(host) and any(host == domain or host.endswith("." + domain) for domain in allowlist)


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
        if links.policy == "allowlist" and link_allowed(core, links.allowlist):
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


# Small talk the host answers itself, in both modes, without a model call or a strike: greetings,
# thanks, "help" or "what can you do", and "what's next". Whole messages only.
_GREET = r"(?:hi|hello|hey|hiya|howdy|greetings|good (?:morning|afternoon|evening|day))(?: there)?"
_THANKS = r"(?:thanks|thank you|thx|ty|cheers|many thanks)(?: (?:a lot|so much|very much))?"
_HELP = (r"(?:help|help me|what can you do|what do you do|what can i do|who are you|what are you|"
         r"how does (?:this|it) work|how do i (?:use (?:this|it)|start|begin)|how can you help|what is this)")
_NEXT = (r"(?:next|what next|whats next|what is next|what now|now what|what should i do next|"
         r"what do i do next|then what)")
_BYE = (r"(?:bye|goodbye|good bye|see you|thats all|that is all|thats it|nothing else|im done|all done)"
        r"(?: for now| for today)?")
_SMALL_TALK = re.compile(rf"(?:(?P<greet>{_GREET}) ?)?(?:(?P<help>{_HELP})|(?P<next>{_NEXT})|"
                         rf"(?:(?P<thanks>{_THANKS}) ?)?(?P<bye>{_BYE})|(?P<thanks_only>{_THANKS}))?(?: ?please)?")


def small_talk(text: str) -> str | None:
    """'greet', 'thanks', 'bye', 'help' or 'next' when the whole message is small talk, else None."""
    words = " ".join(re.sub(r"[^a-z\s]", " ", re.sub(r"['\u2019]", "", text.lower())).split())
    match = _SMALL_TALK.fullmatch(words) if words else None
    if match is None:
        return None
    if match.group("thanks_only"):
        return "thanks"
    return next((kind for kind in ("help", "next", "bye", "greet") if match.group(kind)), None)
