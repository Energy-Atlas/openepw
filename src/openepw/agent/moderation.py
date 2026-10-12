"""Content moderation for the agent chat: OpenAI's moderation endpoint, or a stub for tests.

Only flagged category names are ever logged or recorded, never the text checked.
"""

from __future__ import annotations

import csv
import io
import itertools
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

MODERATION_URL = "https://api.openai.com/v1/moderations"
FLAG_MARKER = "[moderation-test:flag]"           # what StubModeration flags (tests and evals)


class ModerationUnavailable(Exception):
    """Moderation could not run: no key, a timeout, or an API error."""


@dataclass(frozen=True)
class ModerationResult:
    flagged: bool
    categories: tuple[str, ...] = ()


class ModerationPort(Protocol):
    async def check(self, texts: list[str]) -> ModerationResult: ...


class OpenAIModeration:
    """OpenAI's moderation endpoint (free); every text in one request."""

    def __init__(self, api_key: str, *, model: str = "omni-moderation-latest",
                 client: httpx.AsyncClient | None = None):
        self._key = api_key
        self.model = model
        self.client = client or httpx.AsyncClient(timeout=10)

    async def check(self, texts: list[str]) -> ModerationResult:
        if not self._key:
            raise ModerationUnavailable("OPENAI_API_KEY is not set")
        try:
            response = await self.client.post(MODERATION_URL, json={"model": self.model, "input": texts},
                                              headers={"Authorization": "Bearer " + self._key})
        except httpx.HTTPError:
            raise ModerationUnavailable("The moderation request could not complete") from None
        if response.status_code >= 400:
            raise ModerationUnavailable(f"The moderation request returned HTTP {response.status_code}")
        try:
            results = response.json()["results"]
            categories = sorted({name for result in results
                                 for name, hit in (result.get("categories") or {}).items() if hit})
            flagged = any(result.get("flagged") for result in results)
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ModerationUnavailable("The moderation reply was unreadable") from None
        return ModerationResult(flagged, tuple(categories))


class StubModeration:
    """Offline moderation: flags texts containing FLAG_MARKER, or is unavailable on request."""

    def __init__(self, *, unavailable: bool = False):
        self.unavailable = unavailable
        self.calls: list[int] = []                    # number of texts per call (never the texts)

    async def check(self, texts: list[str]) -> ModerationResult:
        self.calls.append(len(texts))
        if self.unavailable:
            raise ModerationUnavailable("Stub moderation is unavailable")
        flagged = any(FLAG_MARKER in text for text in texts)
        return ModerationResult(flagged, ("test",) if flagged else ())


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?")


def epw_text_fields(content: bytes) -> list[str]:
    """The free-text fields of an EPW header (location names, comments) for moderation."""
    # Read the header as openepw.epw.reader does (UTF-8 with an optional BOM, CSV quoting), so the
    # text checked is the text the session shows.
    text = content[:20_000].decode("utf-8-sig", errors="replace")
    fields: list[str] = []
    for row in itertools.islice(csv.reader(io.StringIO(text)), 8):
        for field in row[1:]:
            value = field.strip()
            if value and not _NUMBER.fullmatch(value):
                fields.append(value)
    return fields


def describe(result: Any) -> dict[str, Any]:
    """What a flag records: category names only."""
    return {"categories": list(getattr(result, "categories", ()))}
