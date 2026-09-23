"""Single-writer locking (BE-05).

- `FileLock`: exclusive, non-blocking `fcntl` lock (workspace `.server.lock`, project `.lock`).
- `ProjectLocks`: one `asyncio.Lock` per project serializing appends and atomic writes.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
from pathlib import Path


class LockHeldError(RuntimeError):
    pass


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise LockHeldError(f"Lock is held by another process: {self.path.name}") from None
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


class ProjectLocks:
    """Per-project asyncio write locks; created lazily."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def __call__(self, project_id: str) -> asyncio.Lock:
        lock = self._locks.get(project_id)
        if lock is None:
            lock = self._locks[project_id] = asyncio.Lock()
        return lock
