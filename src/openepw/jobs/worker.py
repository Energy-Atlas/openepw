import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from ..models import Issue, OpenEPWError, WeatherPlan, utcnow
from .store import JobStore


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
        for output in outputs:
            if self.store.get(job_id).cancellation_requested:
                break
            name = output.name if output else "future"
            if name in completed:
                continue
            try:
                subplan = plan
                if output:
                    raw = plan.model_dump(mode="json", exclude={"plan_hash"})
                    raw["outputs"] = [o.model_dump() for o in plan.outputs if o.name == output.name]
                    raw["tasks"] = [t.model_dump() for t in plan.tasks if t.id in output.task_ids]
                    subplan = WeatherPlan.model_validate(raw)
                bundle = self.service.execute(
                    subplan, cancelled=lambda: self.store.get(job_id).cancellation_requested
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
            job.completed = sum(
                bool(b.weather) and not any(i.severity == "error" for i in b.issues)
                for b in completed.values()
            )
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
        job.completed = sum(
            bool(b.weather) and not any(i.severity == "error" for i in b.issues)
            for b in completed.values()
        )
        job.failed = sum(
            not b.weather or any(i.severity == "error" for i in b.issues)
            for b in completed.values()
        ) + max(0, len(outputs) - len(completed))
        if self.store.get(job_id).cancellation_requested:
            job.state = "cancelled"
        elif job.errors or job.failed:
            job.state = "partially_completed" if weather else "failed"
        else:
            job.state = "completed"
        job.finished_at = utcnow()
        self.store.save(job)
