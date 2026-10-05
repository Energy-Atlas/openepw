import os
import subprocess
import sys
from pathlib import Path

from openepw.config import RuntimeConfig
from openepw.jobs.lock import acquire_runner_lock, release_runner_lock
from openepw.jobs.worker import JobRunner
from openepw.service import WeatherService

SRC = Path(__file__).parents[2] / "src"
PROBE = (
    "import sys\n"
    "from openepw.jobs.lock import acquire_runner_lock\n"
    "try:\n"
    "    acquire_runner_lock(sys.argv[1])\n"
    "except Exception as error:\n"
    "    print(getattr(getattr(error, 'issue', None), 'code', type(error).__name__))\n"
    "    raise SystemExit(3)\n"
)


def _probe(root):
    return subprocess.run([sys.executable, "-c", PROBE, str(root)], capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": str(SRC)}, timeout=60)


def test_owners_in_one_process_share_the_lock(tmp_path):
    first = acquire_runner_lock(tmp_path)
    second = acquire_runner_lock(tmp_path)
    assert first == second
    release_runner_lock(second)
    release_runner_lock(first)
    release_runner_lock(acquire_runner_lock(tmp_path))


def test_another_process_is_refused_until_the_lock_is_released(tmp_path):
    held = acquire_runner_lock(tmp_path)
    try:
        refused = _probe(tmp_path)
        assert refused.returncode == 3 and "DATA_ROOT_BUSY" in refused.stdout
    finally:
        release_runner_lock(held)
    assert _probe(tmp_path).returncode == 0


def test_a_recovering_runner_holds_the_root_until_closed(tmp_path):
    runner = JobRunner(WeatherService(RuntimeConfig(data_root=tmp_path)))
    try:
        runner.recover()
        refused = _probe(tmp_path)
        assert refused.returncode == 3 and "DATA_ROOT_BUSY" in refused.stdout
    finally:
        runner.close()
    assert _probe(tmp_path).returncode == 0
