"""One job runner per data root: a cross-process file lock, shared within one process."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import IO, Any

from ..models import OpenEPWError

_guard = threading.Lock()
_held: dict[Path, list[Any]] = {}          # lock path -> [owner count, open file]


def _lock(file: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(file: IO[bytes]) -> None:
    file.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def acquire_runner_lock(root: str | Path) -> Path:
    """Hold the data root for job execution; owners in this process share one lock."""
    path = Path(root).resolve() / "runner.lock"
    with _guard:
        if path in _held:
            _held[path][0] += 1
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        file = path.open("a+b")
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.write(b"\0")
            file.flush()
        file.seek(0)
        try:
            _lock(file)
        except OSError:
            file.close()
            raise OpenEPWError(
                "DATA_ROOT_BUSY",
                "Another OpenEPW process is running jobs for this data root; stop it or use another "
                "--data-root") from None
        _held[path] = [1, file]
        return path


def release_runner_lock(path: Path) -> None:
    with _guard:
        entry = _held.get(path)
        if entry is None:
            return
        entry[0] -= 1
        if entry[0] == 0:
            _unlock(entry[1])
            entry[1].close()
            del _held[path]
