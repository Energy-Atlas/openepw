"""Security profiles for the agent chat: committed YAML policy, validated, with safe fallbacks.

A profile names behaviour, never credentials. ``hosted`` is the strictest shipped profile:
an unknown key, a bad value or a missing file falls back to its value, with a warning. An
override file names the profile it changes (``extends: hosted``) and sets only some keys.
Rules fixed in code (approvals, redaction, input clean-up and so on) are not settings.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger("openepw.security")
PROFILE_NAMES = ("hosted", "local")
STRICTEST = "hosted"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

StrikeSource = Literal["out_of_scope", "offtopic_clamp", "moderation", "host_tool_attempt"]
ModerationCheck = Literal["input", "form_text", "upload_text", "model_output"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfftopicClamp(_Section):
    enabled: bool = True
    min_chars: int = Field(280, ge=50, le=4000)


class ScopeSettings(_Section):
    knowledge_answers: bool = True
    knowledge_answer_words: int = Field(120, ge=20, le=400)
    offtopic_clamp: OfftopicClamp = OfftopicClamp()
    extra_domain_terms: list[str] = []


class StrikeSettings(_Section):
    limit: int = Field(3, ge=1, le=20)
    warn_at: int = Field(2, ge=0, le=20)
    counting: Literal["session", "consecutive"] = "session"
    action: Literal["end_session", "guided", "warn"] = "end_session"
    reopen: Literal["allow", "deny"] = "deny"
    show_count: bool = True
    sources: list[StrikeSource] = ["out_of_scope", "offtopic_clamp", "moderation", "host_tool_attempt"]


class ModerationSettings(_Section):
    enabled: bool = True
    model: str = Field("omni-moderation-latest", min_length=1, max_length=64)
    check: list[ModerationCheck] = ["input", "form_text", "upload_text"]
    on_error: Literal["block", "allow"] = "block"


class ExternalTextSettings(_Section):
    max_chars: int = Field(120, ge=20, le=1000)


class LinkSettings(_Section):
    policy: Literal["allowlist", "strip_all", "keep"] = "allowlist"
    allowlist: list[str] = []


class SecurityPolicy(_Section):
    version: Literal[1] = 1
    profile: str = Field(min_length=1, max_length=40)
    scope: ScopeSettings = ScopeSettings()
    strikes: StrikeSettings = StrikeSettings()
    moderation: ModerationSettings = ModerationSettings()
    external_text: ExternalTextSettings = ExternalTextSettings()
    links: LinkSettings = LinkSettings()
    limits: dict[str, Any] = {}
    # Where the policy came from and a short hash of its effective settings (not settings).
    source: str = Field("", exclude=True)
    digest: str = Field("", exclude=True)

    def settings(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _packaged(name: str) -> tuple[dict[str, Any], str]:
    if name not in PROFILE_NAMES:
        raise ValueError(f"Unknown security profile {name!r}; use one of {', '.join(PROFILE_NAMES)}")
    resource = resources.files("openepw.agent.profiles").joinpath(f"{name}.yaml")
    return _parse(resource.read_text(encoding="utf-8")), f"openepw/agent/profiles/{name}.yaml"


def _parse(text: str) -> dict[str, Any]:
    import yaml

    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("A security profile must be a mapping")
    return data


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _get(data: dict[str, Any], path: tuple[Any, ...]) -> Any:
    for key in path:
        data = data[key]
    return data


def _repair(data: dict[str, Any], strict: dict[str, Any], error: dict[str, Any]) -> str:
    """Replace one invalid value with the strict value (or drop an unknown key); describe it."""
    path = tuple(part for part in error["loc"] if not isinstance(part, int))
    dotted = ".".join(map(str, path))
    parent = _get(data, path[:-1]) if len(path) > 1 else data
    if error["type"] == "extra_forbidden":
        parent.pop(path[-1], None)
        return f"unknown setting {dotted} ignored"
    try:
        parent[path[-1]] = copy.deepcopy(_get(strict, path))
    except (KeyError, TypeError):
        parent.pop(path[-1], None)
    return f"invalid {dotted}; using the {STRICTEST} value"


def _validate(data: dict[str, Any], source: str) -> SecurityPolicy:
    strict, _ = _packaged(STRICTEST)
    data = copy.deepcopy(data)
    data.pop("extends", None)
    for _ in range(50):
        try:
            policy = SecurityPolicy.model_validate(data)
            break
        except ValidationError as error:
            for item in error.errors():
                logger.warning("Security profile %s: %s", source, _repair(data, strict, item))
    else:                                                     # pragma: no cover - defensive
        policy = SecurityPolicy.model_validate(strict)
    canonical = json.dumps(policy.settings(), sort_keys=True)
    policy.source = source
    policy.digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    return policy


def load_policy(profile: str | None = None, *, file: str | Path | None = None,
                default: str = "local") -> SecurityPolicy:
    """The effective policy: a packaged profile, or a file that may extend one."""
    if file is None:
        data, source = _packaged(profile or default)
        return _validate(data, source)
    path = Path(file)
    if not path.is_file():
        logger.warning("Security profile %s not found; using the %s profile", path, STRICTEST)
        data, _ = _packaged(STRICTEST)
        return _validate(data, f"{STRICTEST} (fallback for missing {path.name})")
    try:
        override = _parse(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Security profile %s is not valid YAML; using the %s profile", path, STRICTEST)
        data, _ = _packaged(STRICTEST)
        return _validate(data, f"{STRICTEST} (fallback for unreadable {path.name})")
    base_name = override.get("extends") or override.get("profile") or STRICTEST
    if base_name not in PROFILE_NAMES:
        logger.warning("Security profile %s extends unknown %r; using %s", path, base_name, STRICTEST)
        base_name = STRICTEST
    base, _ = _packaged(str(base_name))
    merged = _merge(base, override)
    merged["profile"] = merged.get("profile") if merged.get("profile") in PROFILE_NAMES else base_name
    return _validate(merged, str(path))


def profile_for_serve(host: str) -> str:
    """`openepw serve` defaults: local on localhost, hosted when serving remotely."""
    return "local" if host in LOCAL_HOSTS else "hosted"


def weakened(policy: SecurityPolicy) -> list[str]:
    """How a policy is weaker than the hosted profile, for a start-up warning (empty if not)."""
    notes = []
    if not policy.moderation.enabled:
        notes.append("moderation is off")
    elif policy.moderation.on_error == "allow":
        notes.append("moderation.on_error is allow")
    if policy.moderation.enabled and "input" not in policy.moderation.check:
        notes.append("messages are not moderated")
    if policy.strikes.action != "end_session":
        notes.append(f"strikes.action is {policy.strikes.action}")
    if policy.strikes.reopen == "allow":
        notes.append("ended sessions can be reopened")
    if not policy.scope.offtopic_clamp.enabled:
        notes.append("the off-topic clamp is off")
    if policy.links.policy == "keep":
        notes.append("links are kept")
    return notes


def requires_moderation_key(policy: SecurityPolicy) -> bool:
    """A policy that must refuse input when moderation cannot run needs an OpenAI key at start-up."""
    return policy.moderation.enabled and policy.moderation.on_error == "block"


def describe(policy: SecurityPolicy) -> str:
    return f"Security profile: {policy.profile} ({policy.source}, digest {policy.digest})"
