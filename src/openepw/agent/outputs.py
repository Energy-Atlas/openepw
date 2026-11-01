"""After a download: the session's files, download offers, retries and the follow-ups that ask for them.

Both modes use these host steps. Nothing here plans or submits new weather: listing and
download offers read the jobs' verified manifests, and a retry runs only after the person
approves the retry form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .guard import clean_external
from .interactions import Interaction, Option
from .mcp_port import ToolFailure
from .session import AgentSession
from .state import Facts

RETRY_LIMIT = 3              # retries in one job's chain
FAILED = frozenset({"failed", "cancelled"})
PRODUCT_WORDS = {"tmy": "typical year (TMY)", "tmyx": "typical year (TMYx)", "published": "published typical year"}


async def session_outputs(s: AgentSession) -> list[dict[str, Any]]:
    """The outputs of the session's finished jobs, numbered, from each job's verified manifest.

    Rows of a retry replace the rows they retried when they succeed (merged by output id), so
    "the 2017 file" means the one that exists. EPWs the person uploaded follow the job rows.
    """
    merged: dict[str, dict[str, Any]] = {}
    for job_id in s.facts.finished_job_ids[-20:]:
        data = (await s.tool("job_outputs", job_id=job_id)).data
        for index, row in enumerate(data.get("outputs", [])):
            key = row.get("output_id") or f"{job_id}:{index}"
            earlier = merged.get(key)
            if earlier is None or row["status"] == "succeeded" or earlier["status"] != "succeeded":
                merged[key] = {**row, "job_id": job_id}
    rows = list(merged.values())
    known = {row["artifact_id"] for row in rows if row.get("artifact_id")}
    rows += [{"place": {"name": None}, "product": "upload", "year": None, "status": "succeeded",
              "artifact_id": artifact_id, "filename": None, "issue_codes": [], "uploaded": True}
             for artifact_id in dict.fromkeys(s.facts.artifact_ids) if artifact_id not in known]
    return [{**row, "number": number} for number, row in enumerate(rows, start=1)]


def output_label(row: dict[str, Any], max_chars: int = 120) -> str:
    if row.get("uploaded"):
        return f"Uploaded EPW ({row['artifact_id'][:8]})"
    place = row.get("place") or {}
    name = clean_external(str(place.get("name") or "point"), max_chars)
    if place.get("lat") is not None:
        name += f" ({place['lat']:.2f}, {place['lon']:.2f})"
    when = (str(row["year"]) if row.get("year") else PRODUCT_WORDS.get(row.get("product") or "")
            or (f"{row['period_start']} to {row['period_end']}" if row.get("period_start") else "typical year"))
    source = "/".join(str(item) for item in (row.get("provider"), row.get("dataset")) if item)
    return " · ".join(part for part in (name, when, source) if part)


def output_line(row: dict[str, Any], max_chars: int = 120) -> str:
    if row["status"] == "succeeded":
        size = f", {row['bytes'] / 1e6:.1f} MB" if row.get("bytes") else ""
        detail = f"file {row['filename']}{size}" if row.get("filename") else "file ready"
    else:
        codes = row.get("issue_codes") or []
        detail = row["status"] + (f" ({', '.join(codes[:4])})" if codes else "")
    return f"{row['number']}. {output_label(row, max_chars)} — {detail}"


def pick_outputs(rows: list[dict[str, Any]], *, years: Any = (), place: str | None = None,
                 status: str | None = None, numbers: Any = ()) -> list[dict[str, Any]]:
    """Rows matching numbers, years, a place name (every word of it) and a status."""
    picked = [row for row in rows if not numbers or row["number"] in set(numbers)]
    if years:
        picked = [row for row in picked if row.get("year") in set(years)]
    if place:
        words = [word for word in re.findall(r"[a-z]+", place.casefold()) if len(word) > 2]
        picked = [row for row in picked
                  if all(word in str((row.get("place") or {}).get("name") or "").casefold() for word in words)]
    if status == "failed":
        picked = [row for row in picked if row["status"] in FAILED]
    elif status == "succeeded":
        picked = [row for row in picked if row["status"] == "succeeded"]
    return picked


def no_outputs_text(s: AgentSession) -> str:
    if s.facts.running_jobs:
        return "Your weather job is still running; its files are listed when it finishes."
    return 'There are no files yet. Ask for weather first, for example "AMY 2018 for Ithaca, NY".'


def show_outputs(s: AgentSession, rows: list[dict[str, Any]], *, heading: str = "Your files:") -> None:
    """List outputs in the host's words: numbered, with status and issue codes."""
    if not rows:
        s.emit("assistant", no_outputs_text(s), code="NO_OUTPUTS")
        return
    limit = s.security.external_text.max_chars
    lines = [output_line(row, limit) for row in rows[:50]]
    if len(rows) > 50:
        lines.append(f"... and {len(rows) - 50} more")
    if any(row["status"] in FAILED for row in rows) and s.facts.retryable_jobs:
        lines.append("Failed outputs can be retried.")
    s.emit("assistant", "\n".join([heading, *lines]), code="OUTPUTS_LISTED",
           numbers=[row["number"] for row in rows[:50]])


def offer_downloads(s: AgentSession, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Offer succeeded outputs as downloads (a ``download`` event). The browser or the CLI's
    /download saves them to the person's disk; nothing is retrieved again."""
    files = [row for row in rows if row["status"] == "succeeded" and row.get("artifact_id")]
    if not files:
        s.emit("assistant", "No finished file matches that." if rows else no_outputs_text(s), code="NO_OUTPUTS")
        return []
    limit = s.security.external_text.max_chars
    shown = files[:100]
    s.emit("download", "Ready to download:\n" + "\n".join(output_line(row, limit) for row in shown), files=[{
        "number": row["number"], "label": output_label(row, limit), "artifact_id": row["artifact_id"],
        "filename": row.get("filename"), "bytes": row.get("bytes"), "sha256": row.get("sha256")}
        for row in shown])
    return shown


def offer_export(s: AgentSession, artifact_id: str, size: int, sha256: str | None = None) -> None:
    """Offer a compact ZIP as a download."""
    s.emit("download", f"Compact ZIP ready: artifact {artifact_id} ({size} bytes).", artifact_id=artifact_id,
           files=[{"number": None, "label": "Compact ZIP of the outputs", "artifact_id": artifact_id,
                   "filename": f"openepw-{artifact_id[:12]}.zip", "bytes": size, "sha256": sha256}])


def _chain(facts: Facts, job_id: str) -> int:
    """How many retries led to this job."""
    count = 0
    while job_id in facts.retry_of and count <= RETRY_LIMIT:
        job_id, count = facts.retry_of[job_id], count + 1
    return count


def _retry_jobs(facts: Facts) -> list[str]:
    return [job for job in facts.retryable_jobs if _chain(facts, job) < RETRY_LIMIT]


async def retry_form(s: AgentSession) -> Interaction | None:
    """The retry form lists every failed output the retry covers, so the person approves its
    scope. None, with the reason shown, when there is nothing the person may retry."""
    facts = s.facts
    if facts.stage != "results" or facts.running_jobs:
        s.emit("assistant", "Retry is offered once the current weather jobs have finished.", code="RETRY_UNAVAILABLE")
        return None
    jobs = _retry_jobs(facts)
    if not jobs:
        capped = bool(facts.retryable_jobs)
        s.emit("assistant", f"These outputs were already retried {RETRY_LIMIT} times; start a new request instead."
               if capped else "There are no failed outputs to retry.", code="RETRY_UNAVAILABLE")
        return None
    rows = [row for row in await session_outputs(s) if row.get("job_id") in jobs and row["status"] in FAILED]
    limit = s.security.external_text.max_chars
    lines = [output_line(row, limit) for row in rows[:25]]
    if len(rows) > 25:
        lines.append(f"... and {len(rows) - 25} more")
    lines.append("Retry asks the providers again for every failed output listed, from the plan you ran. "
                 "Outputs that already succeeded are kept.")
    return Interaction(kind="choice", gate="review_retry", prompt="Retry the failed outputs?",
                       summary="\n".join(lines), data={"jobs": jobs},
                       options=[Option(id="retry", label=f"Retry {len(rows)} failed output(s)"),
                                Option(id="cancel", label="Not now")])


async def run_retry(s: AgentSession, form: Interaction) -> list[str]:
    """Submit job_retry_failed for the jobs on the retry form the person approved. Each retry is
    confirmed with a one-shot approval of its job's original plan."""
    facts = s.facts
    jobs = _retry_jobs(facts)
    if form.data.get("jobs") != jobs or facts.running_jobs:
        s.emit("error", "The failed outputs changed since the retry form was shown.", code="GATE_REQUIRED")
        refreshed = await retry_form(s)
        if refreshed is not None:
            s.open_form(refreshed)
        return []
    started = []
    for job_id in jobs:
        plan_hash = (await s.tool("job_inspect", job_id=job_id)).data["plan_hash"]
        s.approvals.approve(plan_hash)
        try:
            job = (await s.tool("job_retry_failed", job_id=job_id,
                                idempotency_key=f"agent-retry:{s.id}:{job_id}")).data
        except ToolFailure as failure:              # one job that cannot retry must not stop the rest
            s.emit("error", f"Job {job_id[:8]}: {failure.code}: {failure.message}", code=failure.code, job_id=job_id)
            continue
        finally:
            s.approvals.consume(plan_hash)          # one approval, one submission
        facts.retry_of[job["id"]] = job_id
        facts.job_ids.append(job["id"])
        started.append(job["id"])
        s.emit("job", f"Retry job {job['id'][:8]} started for the failed outputs of job {job_id[:8]}",
               job_id=job["id"], retry_of=job_id, state=job.get("state"))
    s.close_form()
    return started


async def report_jobs(s: AgentSession) -> None:
    """One look at the running jobs (never a wait)."""
    running = s.facts.running_jobs
    if not running:
        s.emit("assistant", "No weather job is running." + (" Your files are ready; ask what you got."
                                                           if s.facts.finished_job_ids else ""), code="JOB_STATUS")
        return
    for job_id in running:
        job = (await s.tool("job_inspect", job_id=job_id)).data
        s.emit("job", f"Job {job_id[:8]} {job.get('state')}: {job.get('completed', 0)} of {job.get('total', 0)} "
                      f"outputs done, {job.get('failed', 0)} failed", job_id=job_id, state=job.get("state"),
               completed=job.get("completed", 0), total=job.get("total", 0), failed=job.get("failed", 0))



# Follow-ups guided mode reads, checked before places and years so they never change a request.
_RETRY = re.compile(r"\b(?:re-?try|try (?:it |that |them |those |the failed (?:ones? |outputs? )?)?again"
                    r"|re-?run (?:the )?(?:failed|failures|missing))\b", re.I)
_DOWNLOAD = re.compile(r"^(?:please\s+|can i\s+|could i\s+|i want to\s+|let me\s+)?(?:download|save)\b", re.I)
_LIST = re.compile(r"what (?:did|have) i (?:get|got|retrieved?)|where (?:are|is) my (?:files?|epws?|outputs?|results?)"
                   r"|(?:list|show)(?: me)? (?:my|the|all) (?:files?|epws?|outputs?|results?)"
                   r"|^(?:my )?(?:files|epws|outputs|results)$|which (?:one|file|epw|output) is", re.I)
_FAILED = re.compile(r"what happened (?:to|with)|why did .{0,60}fail|(?:which|what) .{0,40}failed"
                     r"|failed (?:outputs?|files?|years?)", re.I)
_STATUS = re.compile(r"how(?:'s| is) (?:it|the job|my job|the retrieval|the download) going|^status$"
                     r"|^progress$|is (?:it|my job|the job) (?:done|finished|ready)", re.I)
FOLLOW_UPS = (("retry", _RETRY), ("download", _DOWNLOAD), ("failed", _FAILED), ("list", _LIST), ("status", _STATUS))
# Words around a file reference; what remains (besides years) names a place to filter by.
_FILLER = frozenset("""a all an and any are as at be by can could did do every everything file files epw epws for from
get got happened have i in is it its let list me my of on one ones output outputs please result results retrieved
save download show the them these this those to try want was what where which why with year years you zip
fail failed""".split())
# Words of a new weather request: "download AMY 2019 for Boston" is a request, not a follow-up.
_REQUEST = re.compile(r"\b(?:weather|amy|tmyx?|historical|actual|typical|climate|data)\b", re.I)


@dataclass(frozen=True)
class FollowUp:
    kind: str                            # retry, download, failed, list or status
    years: tuple[int, ...] = ()
    place: str = ""                      # words left after the verb, years and filler
    everything: bool = False             # "download all"


def read_follow_up(text: str) -> FollowUp | None:
    """A short follow-up about the session's files or jobs, else None (read the text as a request)."""
    cleaned = text.strip().rstrip(" ?.!")
    if not cleaned or len(cleaned.split()) > 14:
        return None
    kind = next((kind for kind, pattern in FOLLOW_UPS if pattern.search(cleaned)), None)
    if kind is None or (kind == "download" and _REQUEST.search(cleaned)):
        return None
    years = tuple(sorted({int(year) for year in re.findall(r"\b(?:19|20)\d{2}\b", cleaned)}))
    words = [word for word in re.findall(r"[a-z]+", cleaned.casefold()) if word not in _FILLER]
    place = " ".join(words) if kind in ("download", "list", "failed") else ""
    return FollowUp(kind, years, place, bool(re.search(r"\b(?:all|every|everything)\b", cleaned, re.I)))


async def follow_up(s: AgentSession, asked: FollowUp) -> None:
    """Answer a follow-up by the host's rules. The open form stays open (a request in progress
    is never cleared); only retry replaces the "What next?" form with the retry form."""
    if asked.kind == "status":
        await report_jobs(s)
        return
    if asked.kind == "retry":
        form = await retry_form(s)
        if form is not None:
            s.open_form(form)
        return
    rows = await session_outputs(s)
    place = asked.place
    if asked.kind == "download":
        picked = rows if asked.everything else pick_outputs(rows, years=asked.years, place=place)
        offer_downloads(s, picked)
    elif asked.kind == "failed":
        picked = pick_outputs(rows, years=asked.years, place=place, status="failed")
        if rows and not picked:
            s.emit("assistant", "No output failed" + (f" for {', '.join(map(str, asked.years))}." if asked.years
                                                      else "."), code="OUTPUTS_LISTED")
        else:
            show_outputs(s, picked, heading="Failed outputs and their recorded issue codes:")
    else:
        picked = pick_outputs(rows, years=asked.years, place=place)
        show_outputs(s, picked if picked or not rows else rows,
                     heading="Your files:" if picked or not rows else "No file matches that; your files:")
