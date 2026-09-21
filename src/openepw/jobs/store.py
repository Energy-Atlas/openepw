import base64
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from ..models import ArtifactBundle, OpenEPWError, WeatherJob, WeatherPlan

# The stored plan is authoritative for job kind, including rows written before
# WeatherJob carried it.
JOB_COLUMNS = "job, coalesce(json_extract(plan, '$.kind'), 'weather')"


def job_from_row(row):
    return WeatherJob.model_validate_json(row[0]).model_copy(update={"kind": row[1]})


class JobStore:
    def __init__(self, root):
        self.path = Path(root) / "jobs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, idempotency TEXT UNIQUE, plan TEXT NOT NULL, job TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS items (job_id TEXT, name TEXT, bundle TEXT, PRIMARY KEY(job_id,name))"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA busy_timeout=30000")
            with db:
                yield db
        finally:
            # sqlite's transaction context commits/rolls back but does not close.
            db.close()

    def submit(self, plan, idempotency_key=None):
        job = WeatherJob(
            id=uuid.uuid4().hex,
            plan_hash=plan.plan_hash,
            kind=plan.kind,
            total=max(1, len({o.name for o in plan.outputs})),
            idempotency_key=idempotency_key,
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                row = db.execute(
                    f"SELECT {JOB_COLUMNS} FROM jobs WHERE idempotency=?", (idempotency_key,)
                ).fetchone()
                if row:
                    prior = job_from_row(row)
                    if prior.plan_hash != plan.plan_hash:
                        raise OpenEPWError(
                            "IDEMPOTENCY_CONFLICT", "Key already refers to a different plan"
                        )
                    return prior
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?)",
                (job.id, idempotency_key, plan.model_dump_json(), job.model_dump_json()),
            )
        return job

    def get(self, job_id):
        with self.connect() as db:
            row = db.execute(f"SELECT {JOB_COLUMNS} FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise OpenEPWError("JOB_NOT_FOUND", "Unknown job identifier")
        return job_from_row(row)

    def plan(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT plan FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise OpenEPWError("JOB_NOT_FOUND", "Unknown job identifier")
        return WeatherPlan.model_validate_json(row[0])

    def save(self, job):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = WeatherJob.model_validate_json(
                db.execute("SELECT job FROM jobs WHERE id=?", (job.id,)).fetchone()[0]
            )
            job.cancellation_requested = old.cancellation_requested or job.cancellation_requested
            db.execute("UPDATE jobs SET job=? WHERE id=?", (job.model_dump_json(), job.id))

    def cancel(self, job_id):
        job = self.get(job_id)
        if job.state in ("queued", "running"):
            job.cancellation_requested = True
            self.save(job)
        return self.get(job_id)

    def items(self, job_id):
        with self.connect() as db:
            rows = db.execute("SELECT name,bundle FROM items WHERE job_id=?", (job_id,)).fetchall()
        return {name: ArtifactBundle.model_validate_json(body) for name, body in rows}

    def complete_item(self, job_id, name, bundle):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO items VALUES (?,?,?)",
                (job_id, name, bundle.model_dump_json()),
            )

    def list_jobs(self, limit=20, cursor=None):
        from ..models import JobListResponse

        if not 1 <= limit <= 100:
            raise OpenEPWError("INVALID_REQUEST", "Job limit must be 1..100")
        after = None
        if cursor:
            try:
                if len(cursor) > 512:
                    raise ValueError()
                after = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
                if (
                    not isinstance(after, list)
                    or len(after) != 2
                    or not all(isinstance(x, str) for x in after)
                ):
                    raise ValueError()
            except (ValueError, TypeError):
                raise OpenEPWError("INVALID_REQUEST", "Invalid job cursor") from None
        with self.connect() as db:
            clause = "WHERE (json_extract(job, '$.submitted_at'), id) < (?, ?)" if after else ""
            rows = db.execute(
                f"SELECT {JOB_COLUMNS} FROM jobs "
                + clause
                + " ORDER BY json_extract(job, '$.submitted_at') DESC, id DESC LIMIT ?",
                (*after, limit + 1) if after else (limit + 1,),
            ).fetchall()
        jobs = [job_from_row(row) for row in rows]
        more = len(jobs) > limit
        jobs = jobs[:limit]
        token = (
            base64.urlsafe_b64encode(
                json.dumps([jobs[-1].submitted_at, jobs[-1].id]).encode()
            ).decode()
            if more
            else None
        )
        return JobListResponse(items=jobs, next_cursor=token)

    def unfinished(self):
        with self.connect() as db:
            rows = db.execute("SELECT job FROM jobs").fetchall()
        return [
            j.id
            for (raw,) in rows
            if (j := WeatherJob.model_validate_json(raw)).state in ("queued", "running")
        ]
