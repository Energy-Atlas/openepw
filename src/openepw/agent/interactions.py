"""Renderer-neutral forms the agent shows, the answers people give, and conversation events."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field

from ..models import Model

FormKind = Literal["text", "choice", "location_review", "product_choice", "map_input", "upload",
                   "plan_review"]
EventType = Literal["user", "assistant", "tool", "form", "job", "view", "notice", "error"]


class Option(Model):
    id: str
    label: str
    detail: str | None = None


class Interaction(Model):
    """One open form. ``gate`` names the step it answers; ``summary`` is its plain-text body."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    revision: int = 0
    kind: FormKind
    gate: str | None = None
    prompt: str
    summary: str = ""
    options: list[Option] = Field(default_factory=list)
    multi: bool = False
    data: dict[str, Any] = Field(default_factory=dict)
    allow_text: bool = True


class Answer(Model):
    """An answer to the open form: chosen options, an approval, free text or a value."""

    interaction_id: str
    revision: int
    choice_ids: list[str] = Field(default_factory=list)
    approve: bool = False
    text: str | None = None
    value: Any = None


class Event(Model):
    seq: int
    type: EventType
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
