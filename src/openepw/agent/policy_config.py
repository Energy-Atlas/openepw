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
from functools import lru_cache
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


def _reach(data: Any, path: list[Any]) -> Any:
    try:
        return _get(data, tuple(path))
    except (KeyError, IndexError, TypeError):
        return None


def _repair(data: dict[str, Any], strict: dict[str, Any], error: dict[str, Any]) -> str:
    """Fix one validation error and describe it: a bad mapping key or unknown setting is dropped;
    any other bad value (or a bad list item: the whole list) takes the strict value."""
    path = list(error["loc"])
    bad_key = bool(path) and path[-1] == "[key]"
    if bad_key:
        path = path[:-1]
    for index, part in enumerate(path):
        if isinstance(part, int) and isinstance(_reach(data, path[:index]), list):
            path = path[:index]
            break
    dotted = ".".join(map(str, path))
    parent = _reach(data, path[:-1])
    if not path or not isinstance(parent, dict) or path[-1] not in parent:
        return f"invalid {dotted or 'profile'}"
    if bad_key or error["type"] == "extra_forbidden":
        parent.pop(path[-1])
        return f"unknown setting {dotted} ignored"
    try:
        parent[path[-1]] = copy.deepcopy(_get(strict, tuple(path)))
    except (KeyError, IndexError, TypeError):
        parent.pop(path[-1])
    return f"invalid {dotted}; using the {STRICTEST} value"


def _validate(data: dict[str, Any], source: str) -> SecurityPolicy:
    strict, _ = _packaged(STRICTEST)
    data = copy.deepcopy(data)
    data.pop("extends", None)
    label = data.get("profile") if isinstance(data.get("profile"), str) else STRICTEST
    while True:
        try:
            policy = SecurityPolicy.model_validate(data)
            break
        except ValidationError as error:
            before = repr(data)
            for item in error.errors():
                logger.warning("Security profile %s: %s", source, _repair(data, strict, item))
            if repr(data) == before:                          # nothing left to repair: strict values
                logger.warning("Security profile %s: using the %s values", source, STRICTEST)
                policy = SecurityPolicy.model_validate({**strict, "profile": label})
                break
    canonical = json.dumps(policy.settings(), sort_keys=True)
    policy.source = source
    policy.digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    return policy


@lru_cache(maxsize=None)
def default_policy() -> SecurityPolicy:
    """For a session created without a profile (library use and tests): the local profile with
    moderation off, so nothing is sent anywhere. `openepw chat`, `eval` and `serve` always pass
    the profile they loaded."""
    local = load_policy("local")
    policy = local.model_copy(update={"moderation": local.moderation.model_copy(update={"enabled": False})})
    policy.source, policy.digest = "library default (local profile, moderation off)", local.digest + "-lib"
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
    # An override is always labelled as one: it cannot present itself as a committed profile.
    merged["profile"] = f"{base_name}+override"
    return _validate(merged, str(path))


def profile_for_serve(host: str) -> str:
    """`openepw serve` defaults: local on localhost, hosted when serving remotely."""
    return "local" if host in LOCAL_HOSTS else "hosted"


def weakened(policy: SecurityPolicy) -> list[str]:
    """Every way a policy is weaker than the hosted profile, for a start-up warning (empty if none)."""
    strict = load_policy(STRICTEST)
    notes = []
    moderation, strict_moderation = policy.moderation, strict.moderation
    if not moderation.enabled:
        notes.append("moderation is off")
    else:
        if moderation.on_error != strict_moderation.on_error:
            notes.append(f"moderation.on_error is {moderation.on_error}")
        missing = [item for item in strict_moderation.check if item not in moderation.check]
        if missing:
            notes.append("moderation does not check " + ", ".join(missing))
    strikes, strict_strikes = policy.strikes, strict.strikes
    if strikes.action != strict_strikes.action:
        notes.append(f"strikes.action is {strikes.action}")
    if strikes.reopen != strict_strikes.reopen:
        notes.append("ended sessions can be reopened")
    missing_sources = [item for item in strict_strikes.sources if item not in strikes.sources]
    if missing_sources:
        notes.append("strike sources not counted: " + ", ".join(missing_sources))
    if strikes.limit > strict_strikes.limit:
        notes.append(f"strikes.limit is {strikes.limit}")
    if strikes.counting != strict_strikes.counting:
        notes.append(f"strikes count only when {strikes.counting}")
    if strikes.warn_at >= strikes.limit:
        notes.append("no warning before the strike limit")
    if not strikes.show_count and strict_strikes.show_count:
        notes.append("the strike count is not shown")
    extra_terms = [term for term in policy.scope.extra_domain_terms if term not in strict.scope.extra_domain_terms]
    if extra_terms:
        notes.append("extra domain terms widen the off-topic clamp: " + ", ".join(extra_terms[:5]))
    clamp = policy.scope.offtopic_clamp
    if not clamp.enabled:
        notes.append("the off-topic clamp is off")
    elif clamp.min_chars > strict.scope.offtopic_clamp.min_chars:
        notes.append(f"offtopic_clamp.min_chars is {clamp.min_chars}")
    if policy.scope.knowledge_answer_words > strict.scope.knowledge_answer_words:
        notes.append(f"knowledge_answer_words is {policy.scope.knowledge_answer_words}")
    if policy.external_text.max_chars > strict.external_text.max_chars:
        notes.append(f"external_text.max_chars is {policy.external_text.max_chars}")
    if policy.links.policy == "keep":
        notes.append("links are kept")
    elif policy.links.policy == "allowlist":
        extra = [domain for domain in policy.links.allowlist if domain not in strict.links.allowlist]
        if extra:
            notes.append("links allowed to " + ", ".join(extra))
    return notes


def requires_moderation_key(policy: SecurityPolicy) -> bool:
    """A policy that must refuse input when moderation cannot run needs an OpenAI key at start-up."""
    return policy.moderation.enabled and policy.moderation.on_error == "block"


def describe(policy: SecurityPolicy) -> str:
    return f"Security profile: {policy.profile} ({policy.source}, digest {policy.digest})"
