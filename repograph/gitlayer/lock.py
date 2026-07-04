"""Cross-process lockfile serializing sync runs (CLAUDE.md §7.1).

O_CREAT|O_EXCL is atomic on every platform we care about. A lock older than
``STALE_AFTER`` is presumed abandoned (crashed process) and broken; the
subsequent re-acquire race is safe because creation is atomic — exactly one
contender wins.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

STALE_AFTER = 600.0  # seconds
_POLL_INTERVAL = 0.05


class LockTimeout(RuntimeError):
    pass


class FileLock:
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: int | None = None

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return
            except FileExistsError:
                self._break_if_stale()
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"could not acquire {self.path} within {self.timeout}s; "
                        "another sync may be running (or crashed — delete the "
                        "lockfile if you are sure)"
                    )
                time.sleep(_POLL_INTERVAL)

    def _break_if_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age > STALE_AFTER:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()
