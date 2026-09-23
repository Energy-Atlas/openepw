import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..models import Issue, OpenEPWError, WeatherPlan, utcnow
from .store import JobStore

TERMINAL = ("completed", "partially_completed", "failed", "cancelled")


def subplan(plan, outputs):
    """Restrict a plan to output identities and their required fetch tasks."""
    keys = {output.id or output.name for output in outputs}
    task_ids = {task_id for output in outputs for task_id in output.task_ids}
    raw = plan.model_dump(mode="json", exclude={"plan_hash"})
    raw["outputs"] = [
        output.model_dump(mode="json")
        for output in plan.outputs
        if (output.id or output.name) in keys
    ]
    raw["tasks"] = [task.model_dump(mode="json") for task in plan.tasks if task.id in task_ids]
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

    def submit(self, plan, idempotency_key=None, retry_of=None):
        job = self.store.submit(plan, idempotency_key, retry_of=retry_of)
        self.enqueue(job.id)
        return job

    def retry_failed(self, job_id, idempotency_key=None):
        """Submit only output identities that have no verified successful artifact."""
        job = self.store.get(job_id)
        if job.state not in TERMINAL:
            raise OpenEPWError("INVALID_REQUEST", "Only a finished job can be retried")
        plan = self.store.plan(job_id)
        produced: set[str] = set()
        for key, bundle in self.store.items(job_id).items():
            try:
                if plan.kind == "future":
                    for ref in bundle.weather:
                        self.service.artifacts.resolve(ref.id)
                        produced.update(
                            output.id or output.name
                            for output in plan.outputs
                            if output.name == Path(ref.path).name
                        )
                elif bundle.weather and all(
                    self.service.artifacts.resolve(ref.id) for ref in bundle.weather
                ):
                    produced.add(key)
            except OpenEPWError:
                pass
        missing = [o for o in plan.outputs if (o.id or o.name) not in produced]
        if not missing:
            raise OpenEPWError("NOTHING_TO_RETRY", "Every planned output was produced")
        return self.submit(subplan(plan, missing), idempotency_key, retry_of=job_id)

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
        outputs = list({(o.id or o.name): o for o in plan.outputs}.values())
        if plan.kind == "future":
            outputs = [None]
        attempted = len(completed)
        for output in outputs:
            if self.store.get(job_id).cancellation_requested:
                break
            name = (output.id or output.name) if output else "future"
            if name in completed:
                continue
            try:
                execution_plan = subplan(plan, [output]) if output else plan
                bundle = self.service.execute(
                    execution_plan, cancelled=lambda: self.store.get(job_id).cancellation_requested
                )
                self.store.complete_item(job_id, name, bundle)
                completed[name] = bundle
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
            attempted += 1
            job.completed = sum(len(b.weather) for b in completed.values())
            job.failed = max(0, attempted - job.completed)
            self.store.save(job)
        weather = []
        extra = []
        errors = list(job.errors)
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
