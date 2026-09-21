import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from ..models import Issue, OpenEPWError, WeatherPlan, utcnow
from .store import JobStore

TERMINAL = ("completed", "partially_completed", "failed", "cancelled")


def subplan(plan, outputs):
    """A plan restricted to the given outputs and the tasks they need, with a fresh hash."""
    names = {output.name for output in outputs}
    task_ids = {task_id for output in outputs for task_id in output.task_ids}
    raw = plan.model_dump(mode="json", exclude={"plan_hash"})
    raw["outputs"] = [o.model_dump(mode="json") for o in plan.outputs if o.name in names]
    raw["tasks"] = [t.model_dump(mode="json") for t in plan.tasks if t.id in task_ids]
    raw["issues"] = []
    return WeatherPlan.model_validate(raw)


class JobRunner:
    def __init__(self, service, store=None):
        self.service = service
        self.store = store or JobStore(service.config.data_root)
        self.pool = ThreadPoolExecutor(
            max_workers=service.config.workers, thread_name_prefix="openepw"
        )
        self.lock = threading.Lock()
        self.active = set()

    def submit(self, plan, idempotency_key=None):
        job = self.store.submit(plan, idempotency_key)
        self.enqueue(job.id)
        return job

    def retry_failed(self, job_id, idempotency_key=None):
        """Submit a new job for the outputs a finished job did not produce."""
        job = self.store.get(job_id)
        if job.state not in TERMINAL:
            raise OpenEPWError("INVALID_REQUEST", "Only a finished job can be retried")
        plan = self.store.plan(job_id)
        if plan.kind == "future":
            if job.state == "completed":
                raise OpenEPWError("NOTHING_TO_RETRY", "The projection job has no failed outputs")
            return self.submit(plan, idempotency_key)
        produced = {name for name, bundle in self.store.items(job_id).items() if bundle.weather}
        failed = [o for o in {o.name: o for o in plan.outputs}.values() if o.name not in produced]
        if not failed:
            raise OpenEPWError("NOTHING_TO_RETRY", "Every planned output was produced")
        return self.submit(subplan(plan, failed), idempotency_key)

    def enqueue(self, job_id):
        with self.lock:
            if job_id in self.active:
                return
            self.active.add(job_id)
        self.pool.submit(self._run, job_id)

    def _run(self, job_id):
        try:
            self.run(job_id)
        finally:
            with self.lock:
                self.active.discard(job_id)

    def recover(self):
        for job_id in self.store.unfinished():
            self.enqueue(job_id)

    def close(self):
        self.pool.shutdown(wait=True)

    def run(self, job_id):
        job = self.store.get(job_id)
        if job.state not in ("queued", "running"):
            return
        job.state = "running"
        self.store.save(job)
        plan = self.store.plan(job_id)
        completed = self.store.items(job_id)
        # Verify prior artifacts, including provenance, before resuming around them.
        for name, bundle in list(completed.items()):
            try:
                for ref in [
                    *bundle.weather,
                    bundle.request,
                    bundle.plan,
                    bundle.manifest,
                    bundle.qc,
                    *bundle.additional,
                ]:
                    self.service.artifacts.resolve(ref.id)
            except OpenEPWError:
                del completed[name]
        outputs = list({o.name: o for o in plan.outputs}.values())
        if plan.kind == "future":
            outputs = [None]
        # Counted per attempt so a resumed job does not double-count retried failures.
        failures = 0
        for output in outputs:
            if self.store.get(job_id).cancellation_requested:
                break
            name = output.name if output else "future"
            if name in completed:
                continue
            try:
                bundle = self.service.execute(
                    subplan(plan, [output]) if output else plan,
                    cancelled=lambda: self.store.get(job_id).cancellation_requested,
                )
                self.store.complete_item(job_id, name, bundle)
                completed[name] = bundle
                if not bundle.weather:
                    failures += 1
            except Exception as exc:
                # Do not serialize raw provider/dependency exceptions or secret-bearing URLs.
                issue = (
                    exc.issue
                    if isinstance(exc, OpenEPWError)
                    else Issue(
                        code="JOB_FAILURE",
                        message="Unexpected job failure; raw exception suppressed",
                        severity="error",
                    )
                )
                job.errors.append(issue)
                failures += 1
            # Persist progress after every output so clients can show it while running.
            job.completed = sum(len(b.weather) for b in completed.values())
            job.failed = failures
            self.store.save(job)
        weather = []
        extra = []
        errors = [*plan.issues, *job.errors]
        manifests = []
        qc = []
        for bundle in completed.values():
            weather.extend(bundle.weather)
            extra.extend(bundle.additional)
            errors.extend(bundle.issues)
            _, mp = self.service.artifacts.resolve(bundle.manifest.id)
            _, qp = self.service.artifacts.resolve(bundle.qc.id)
            manifests.extend(json.loads(mp.read_text())["outputs"])
            qc.extend(json.loads(qp.read_text()))
        job.bundle = self.service._bundle(
            plan, uuid.uuid4().hex, weather, extra, errors, manifests, qc
        )
        job.errors = [i for i in errors if i.severity == "error"]
        job.completed = len(weather)
        job.failed = max(0, job.total - job.completed)
        if self.store.get(job_id).cancellation_requested:
            job.failed = sum(not b.weather for b in completed.values())
            job.state = "cancelled"
        elif job.errors or job.failed:
            job.state = "partially_completed" if weather else "failed"
        else:
            job.state = "completed"
        job.finished_at = utcnow()
        self.store.save(job)
