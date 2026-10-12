"""Trial records: what was tested (pins), the trace ending in the outcome, and the grades.

A record is plain JSON so graders, reports and stored fixtures share one shape:

    {"run_id", "task_id", "task_hash", "trial", "mode", "profile", "pins": {...},
     "trace": [event entries..., model entries..., {"type": "outcome", "data": {...}}],
     "grades": [...], "passed", "metrics": {...}}

Event entries are the session's events (what the person saw). Model entries sit where the model
was called: what it was sent (state block, history, turn items), what it replied, and its cost.
The last entry is the outcome: facts, plans, jobs, strikes and whether the session ended.
Records are graded before they are written; the written copy is redacted again.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..text import safe_prompt
from .graders import SECRET

# Local paths, including drive paths with forward slashes, UNC shares and user folders whose names
# hold spaces (the user folder is the part that identifies a person).
_PATH = re.compile(r"(?i:[A-Za-z]:[\\/]Users[\\/][^\\/\"']+(?:[\\/][^\s\"']*)?)"
                   r"|[A-Za-z]:[\\/][^\s\"']+|\\\\[^\s\"'\\]+\\[^\s\"']+"
                   r"|/(?:home|Users|tmp|var|opt|mnt|srv)/[^\s\"']+|~[/\\][^\s\"']+")


def new_run_id(mode: str, label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{mode}-{re.sub(r'[^a-z0-9.-]+', '-', label.lower())}-{uuid.uuid4().hex[:4]}"


def git_pins(repo: Path | None = None) -> dict[str, Any]:
    """The commit and whether tracked files had uncommitted changes (with a hash of the diff).

    Untracked files are ignored. Outside a git checkout the commit is "unknown".
    """
    if repo is None:
        here = Path(__file__).resolve()
        repo = here.parents[4]
        if not (repo / "src" / "openepw" / "agent" / "evals" / here.name).exists():
            return {"commit": "unknown", "branch": None, "dirty": None, "diff_sha256": None}   # installed copy

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20, check=True).stdout
    try:
        commit = git("rev-parse", "HEAD").strip()
        branch = git("rev-parse", "--abbrev-ref", "HEAD").strip()
        diff = git("diff", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unknown", "branch": None, "dirty": None, "diff_sha256": None}
    return {"commit": commit, "branch": branch, "dirty": bool(diff),
            "diff_sha256": hashlib.sha256(diff.encode()).hexdigest()[:12] if diff else None}


def run_pins(*, run_id: str, mode: str, model: str, providers: str, security: Any, tasks_hash: str,
             trials: str) -> dict[str, Any]:
    from ... import __version__ as version

    return {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git": git_pins(), "package_version": version, "python": platform.python_version(),
            "mode": mode, "model": model, "providers": providers, "trials": trials,
            "profile": security.profile, "profile_digest": security.digest, "tasks_hash": tasks_hash}


def short_hash(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def trace_entries(events: list[Any], model_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Session events with each model call placed after the last event logged before it."""
    calls = sorted(model_calls, key=lambda call: call["after"])
    entries: list[dict[str, Any]] = []
    position = 0
    for event in events:
        while position < len(calls) and calls[position]["after"] < event.seq:
            entries.append({"type": "model", "data": calls[position]["data"]})
            position += 1
        entries.append({"type": event.type, "seq": event.seq, "text": event.text, "data": event.data})
    entries += [{"type": "model", "data": call["data"]} for call in calls[position:]]
    return entries


def outcome(session: Any) -> dict[str, Any]:
    state, facts, form = session.state, session.facts, session.form
    return {"type": "outcome", "data": {
        "mode": state.mode,
        "facts": facts.model_dump(mode="json"),
        "state": {"strikes": state.strikes, "ended": state.ended, "downgraded": state.downgraded},
        "form": {"kind": form.kind, "gate": form.gate, "prompt": form.prompt} if form else None,
        "jobs": {"submitted": list(facts.job_ids), "finished": list(facts.finished_job_ids)},
        "artifacts": list(facts.artifact_ids)}}


def metrics(trace: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
    events = [entry for entry in trace if entry.get("type") not in ("model", "outcome")]
    model = [entry.get("data") or {} for entry in trace if entry.get("type") == "model"]
    tools = [entry for entry in events if entry.get("type") == "tool"
             and (entry.get("data") or {}).get("phase") == "call"]
    codes: dict[str, int] = {}
    for entry in events:
        data = entry.get("data") or {}
        form_data = (data.get("form") or {}).get("data") or {}
        for code in [data.get("code"), *data.get("guards", []), *form_data.get("guards", [])]:
            if code:
                codes[code] = codes.get(code, 0) + 1
    last = trace[-1].get("data") or {} if trace and trace[-1].get("type") == "outcome" else {}
    return {"seconds": round(seconds, 3),
            "model_calls": len(model),
            "model_steps": sum(1 for entry in events if entry.get("type") == "tool"
                               and (entry.get("data") or {}).get("by") == "model"
                               and (entry.get("data") or {}).get("phase") in ("call", "refused")),
            "tool_calls": len(tools),
            "input_tokens": sum(int(call.get("input_tokens") or 0) for call in model),
            "output_tokens": sum(int(call.get("output_tokens") or 0) for call in model),
            "cost_usd": round(sum(float(call.get("cost_usd") or 0.0) for call in model), 6),
            "codes": codes,
            "strikes": int((last.get("state") or {}).get("strikes") or 0),
            "fallback": "MODEL_UNAVAILABLE" in codes}


def scrub(value: Any) -> Any:
    """A copy with keys and local paths redacted, for writing a record to disk."""
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        # Paths first: the shared redaction stops at the first space of a user folder name.
        return safe_prompt(SECRET.sub("[redacted]", _PATH.sub("[local path]", value)), limit=len(value) + 1)
    return value


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(scrub(record), ensure_ascii=False) + "\n")


def read_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
