"""Prevent simultaneous console writers from sharing a checkpoint thread."""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SessionBusy(RuntimeError):
    """A console already owns this data root and conversation ID."""


@contextmanager
def session_lock(root: str | Path, thread_id: str) -> Iterator[None]:
    name = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()[:16]
    path = Path(root).resolve() / "harness" / f"chat-{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        file.seek(0, os.SEEK_END)
        if file.tell() == 0:
            file.seek(0)
            file.write(b"\0")
            file.flush()
        file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SessionBusy(
                "Another OpenEPW chat is using this data root and thread ID. "
                "Close that session or use --thread-id <another-name>."
            ) from error
        try:
            yield
        finally:
            file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
