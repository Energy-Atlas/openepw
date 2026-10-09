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
