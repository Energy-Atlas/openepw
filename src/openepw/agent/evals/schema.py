"""Eval tasks: the YAML schema, loading with file and line in errors, coverage ids and hashes.

A task is one YAML file: the person's messages and form answers, the setup, the graders that
judge each trial, how many live trials it gets, and a scripted solution that proves it can be
solved offline. Unknown keys, unknown graders, bad grader values and unknown coverage ids are
errors that name the file and line.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

Mode = Literal["guided", "agent"]
Profile = Literal["local", "hosted"]
FormKind = Literal["text", "choice", "location_review", "product_choice", "map_input", "upload", "plan_review"]
SAFETY_TRIALS = 5                  # live trials for tasks tagged "safety" (judged by pass^k)
LIVE_TRIALS = 3                    # live trials for other tasks


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Upload(_Strict):
    city: str = "Ithaca"           # the EPW header's city; tasks plant text here
    filename: str = "site.epw"


class Setup(_Strict):
    upload: Upload | None = None
    fail_near: list[tuple[float, float]] = []      # stub provider outages near these points
    # default: the real moderation endpoint in live runs and the stub offline
    moderation: Literal["default", "stub", "unavailable"] = "default"


class User(_Strict):
    """The simulated person: what they type, and how they answer each kind of form.

    An answer is ``approve``/``run`` (reviews), a list of option ids or ``first`` (choices),
    ``say:<text>`` (type text instead of answering), other text (text and place forms), or null
    (stop at that form).
    """

    say: str = Field(min_length=1)
    then: list[str] = []
    answers: dict[FormKind, str | list[str] | None] = {}
    max_interactions: int = Field(10, ge=1, le=50)

    @model_validator(mode="after")
    def _answer_shapes(self) -> User:
        for kind, answer in self.answers.items():
            if answer is None or (isinstance(answer, str) and answer.startswith("say:")):
                continue
            if kind in ("location_review", "plan_review") and answer not in ("approve", "run"):
                raise ValueError(f"answers.{kind} must be approve, run, say:<text> or null, not {answer!r}")
            if kind in ("product_choice", "choice") and not (isinstance(answer, list) or answer == "first"):
                raise ValueError(f"answers.{kind} must be a list of option ids, first, say:<text> or null")
            if kind in ("text", "map_input", "upload") and not isinstance(answer, str):
                raise ValueError(f"answers.{kind} must be text, say:<text> or null")
        return self


class ScriptStep(_Strict):
    call: str | None = None
    args: dict[str, Any] = {}
    say: str | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> ScriptStep:
        if (self.call is None) == (self.say is None):
            raise ValueError("a script step has either call (with args) or say")
        return self


class GraderUse(_Strict):
    grader: str
    value: Any = None
    severity: Literal["hard", "soft"] | None = None   # default: the grader's own
    profile: Profile | None = None                    # only under this profile


class Trials(_Strict):
    live: int | None = Field(None, ge=1, le=20)       # default: 5 for safety tasks, else 3


class Task(_Strict):
    id: str = Field(pattern=r"^S[0-9]+$")
    title: str = Field(min_length=5)
    purpose: str = Field(min_length=10)
    covers: list[str] = []
    suite: Literal["regression", "capability"] = "regression"
    tags: list[str] = []
    modes: list[Mode] = ["guided", "agent"]
    profiles: list[Profile] = ["local", "hosted"]
    setup: Setup = Setup()
    user: User
    graders: list[GraderUse] = []
    trials: Trials = Trials()
    reference: str | None = None                      # a reference answer, for later judges
    script: list[ScriptStep] | None = None            # None: no offline solution

    _source: str = PrivateAttr("")

    @property
    def source(self) -> str:
        return self._source

    def live_trials(self) -> int:
        return self.trials.live or (SAFETY_TRIALS if "safety" in self.tags else LIVE_TRIALS)

    def graders_for(self, profile: str) -> list[GraderUse]:
        base = profile.split("+")[0]
        return [use for use in self.graders if use.profile is None or use.profile == base]


class TaskError(ValueError):
    """A task file that does not validate; the message names the file and line."""


@lru_cache(maxsize=1)
def coverage_items() -> dict[str, dict[str, str]]:
    import yaml

    text = resources.files("openepw.agent.evals").joinpath("coverage.yaml").read_text(encoding="utf-8")
    return dict(yaml.safe_load(text)["items"])


def packaged_tasks_dir() -> Path:
    return Path(str(resources.files("openepw.agent.evals").joinpath("tasks")))


def load_tasks(path: str | Path | None = None) -> list[Task]:
    """The packaged tasks, or the tasks in a folder of YAML files or in one YAML file."""
    root = Path(path) if path is not None else packaged_tasks_dir()
    if not root.exists():
        raise TaskError(f"{root}: no such task file or folder")
    files = sorted(root.glob("*.yaml")) if root.is_dir() else [root]
    if not files:
        raise TaskError(f"{root}: no task files (*.yaml)")
    tasks = [load_task(file) for file in files]
    seen: dict[str, str] = {}
    for task in tasks:
        if task.id in seen:
            raise TaskError(f"{task.source}: task id {task.id} is also used by {seen[task.id]}")
        seen[task.id] = task.source
    return sorted(tasks, key=lambda task: int(task.id[1:]))


def load_task(path: str | Path) -> Task:
    import yaml

    from .graders import REGISTRY

    file = Path(path)
    text = file.read_text(encoding="utf-8")
    try:
        node = yaml.compose(text)
        duplicate = _duplicate_key(node)
        if duplicate:
            raise TaskError(f"{file}:{duplicate[1]}: duplicate key {duplicate[0]!r}")
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise TaskError(f"{file}: not valid YAML: {error}") from None
    if not isinstance(data, dict):
        raise TaskError(f"{file}:1: a task file holds one mapping")
    try:
        task = Task.model_validate(data)
    except ValidationError as error:
        problem = error.errors()[0]
        loc = list(problem["loc"])
        raise TaskError(f"{file}:{_line(node, loc)}: {'.'.join(map(str, loc)) or 'task'}: {problem['msg']}") from None
    for index, use in enumerate(task.graders):
        grader = REGISTRY.get(use.grader)
        where = f"{file}:{_line(node, ['graders', index])}"
        if grader is None:
            raise TaskError(f"{where}: unknown grader {use.grader!r}")
        if grader.always:
            raise TaskError(f"{where}: {use.grader} always runs; do not list it")
        try:
            grader.validate(use.value)
        except (ValidationError, ValueError) as error:
            raise TaskError(f"{where}: {use.grader}: bad value {use.value!r} ({_short(error)})") from None
    unknown = [item for item in task.covers if item not in coverage_items()]
    if unknown:
        raise TaskError(f"{file}:{_line(node, ['covers'])}: unknown coverage id(s) {', '.join(unknown)} "
                        "(see coverage.yaml)")
    task._source = str(file)
    return task


def _duplicate_key(node: Any) -> tuple[str, int] | None:
    """The first mapping key that appears twice in its mapping (YAML keeps the last silently)."""
    import yaml

    if isinstance(node, yaml.MappingNode):
        seen: set[str] = set()
        for key, value in node.value:
            if key.value in seen:
                return key.value, key.start_mark.line + 1
            seen.add(key.value)
            found = _duplicate_key(value)
            if found:
                return found
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            found = _duplicate_key(item)
            if found:
                return found
    return None


def _short(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return error.errors()[0]["msg"]
    return str(error)


def _line(node: Any, loc: list[Any]) -> int:
    """The 1-based line of the YAML node a validation location points at (or its nearest parent)."""
    import yaml

    line = node.start_mark.line + 1 if node is not None else 1
    for part in loc:
        if isinstance(node, yaml.MappingNode):
            match = next((value for key, value in node.value if key.value == str(part)), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value):
            match = node.value[part]
        else:
            match = None
        if match is None:
            break
        node, line = match, match.start_mark.line + 1
    return line


def task_hash(task: Task) -> str:
    canonical = json.dumps(task.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


def tasks_hash(tasks: list[Task]) -> str:
    return hashlib.sha256("".join(task_hash(task) for task in tasks).encode()).hexdigest()[:12]
