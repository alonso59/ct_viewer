"""`CACHE_MAX_GB` (OPS-03, AUD-A4-16): one LRU budget over every disposable cache.

The budget covers Open-mode scratch (`.scratch/open/{fingerprint}.{order}/`, evicted a folder at
a time) and every active project's `cache/meshes`, `cache/thumbs` and `cache/npy` (evicted a file
at a time). "Last used" is the newest mtime/atime of the unit; readers call `touch()` on a cache
hit, because many filesystems do not update atime. Nothing outside those pools is ever looked at
or deleted (R1, PRJ-10): pool roots that are symlinks, symlinked entries and entries that resolve
outside their pool are skipped; temp files of an atomic write (`.name.*.tmp`) are left alone, and
units used in the last `min_age_s` seconds are kept (in-flight writes, files being served).

`enforce()` is the pure sweep (a thread); `CacheBudget` runs it after cache writes (debounced,
`request()`) and periodically from the lifespan.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger("app.cache")

GB = 1024**3
PROJECT_POOLS = ("meshes", "thumbs", "npy")  # under a project's `cache/` (PRJ-10)
SWEEP_INTERVAL_S = 600.0
MIN_AGE_S = 60.0


@dataclass(frozen=True)
class Pool:
    """A disposable directory; `unit` = evict single files, or each top-level folder whole."""

    root: Path
    unit: Literal["file", "dir"]


@dataclass(frozen=True)
class Unit:
    path: Path
    size: int
    last_used: float


def touch(path: Path) -> None:
    """Mark a cache entry as used (LRU): atime = now, mtime kept (it dates the build)."""
    with contextlib.suppress(OSError):
        os.utime(path, ns=(time.time_ns(), path.stat().st_mtime_ns))


def workspace_pools(workspace_root: Path, projects_dir: Path) -> list[Pool]:
    """Open scratch + each active project's disposable cache folders (archived ones are purged)."""
    pools = [Pool(workspace_root / ".scratch" / "open", "dir")]
    if projects_dir.is_dir():
        for p in sorted(projects_dir.iterdir()):
            if p.name.startswith(".") or not p.is_dir() or p.is_symlink():
                continue
            pools += [Pool(p / "cache" / name, "file") for name in PROJECT_POOLS]
    return pools


def _stamp(st: os.stat_result) -> float:
    return max(st.st_mtime, st.st_atime)


def _is_temp(p: Path) -> bool:
    return p.name.startswith(".") and p.name.endswith(".tmp")


def _files(d: Path) -> Iterator[tuple[Path, os.stat_result]]:
    for dirpath, dirnames, filenames in os.walk(d, followlinks=False):
        dirnames[:] = [n for n in dirnames if not Path(dirpath, n).is_symlink()]
        for n in filenames:
            f = Path(dirpath, n)
            if f.is_symlink():
                continue
            with contextlib.suppress(OSError):
                yield f, f.stat()


def units(pool: Pool) -> list[Unit]:
    root = pool.root
    if not root.is_dir() or root.is_symlink():
        return []
    real_root = root.resolve()
    out: list[Unit] = []
    for entry in root.iterdir():
        if entry.is_symlink() or _is_temp(entry) or not entry.resolve().is_relative_to(real_root):
            continue
        try:
            if pool.unit == "file":
                if entry.is_dir():  # nested files, each its own unit
                    files = [(f, st) for f, st in _files(entry) if not _is_temp(f)]
                    out += [Unit(f, st.st_size, _stamp(st)) for f, st in files]
                else:
                    st = entry.stat()
                    out.append(Unit(entry, st.st_size, _stamp(st)))
            elif entry.is_dir():
                files = list(_files(entry))
                size = sum(st.st_size for _, st in files)
                # its files' use (a folder's own mtime only when it is empty)
                last = max((_stamp(st) for _, st in files), default=_stamp(entry.stat()))
                out.append(Unit(entry, size, last))
        except OSError:
            continue
    return out


def enforce(pools: Iterable[Pool], max_bytes: int, *, min_age_s: float = MIN_AGE_S) -> int:
    """Delete least-recently-used units until the pools fit `max_bytes`; returns bytes freed."""
    pools = list(pools)
    roots = [(p.root.resolve(), p) for p in pools if p.root.is_dir() and not p.root.is_symlink()]
    all_units = [u for _, p in roots for u in units(p)]
    total = sum(u.size for u in all_units)
    if total <= max_bytes:
        return 0
    now = time.time()
    freed = 0
    for u in sorted(all_units, key=lambda u: u.last_used):
        if total <= max_bytes:
            break
        if now - u.last_used < min_age_s:
            continue
        real = u.path.resolve()
        if u.path.is_symlink() or not any(real.is_relative_to(r) for r, _ in roots):
            continue  # never outside a pool (R1)
        try:
            if u.path.is_dir():
                shutil.rmtree(u.path)
            else:
                u.path.unlink()
        except OSError:
            continue
        total -= u.size
        freed += u.size
    if freed:
        log.info("cache budget: evicted", extra={"freed_bytes": freed, "total_bytes": total})
    return freed


class CacheBudget:
    """Runs `enforce` in a thread: after writes (debounced) and every `interval_s`."""

    def __init__(
        self,
        pools: Callable[[], list[Pool]],
        max_gb: float,
        *,
        interval_s: float = SWEEP_INTERVAL_S,
        min_age_s: float = MIN_AGE_S,
    ) -> None:
        self.pools = pools
        self.max_bytes = int(max_gb * GB)
        self.interval_s = interval_s
        self.min_age_s = min_age_s
        self._task: asyncio.Task[None] | None = None
        self._again = False
        self._loop_task: asyncio.Task[None] | None = None

    async def sweep(self) -> int:
        return await asyncio.to_thread(
            lambda: enforce(self.pools(), self.max_bytes, min_age_s=self.min_age_s)
        )

    def request(self) -> None:
        """A cache write happened: sweep soon (one sweep at a time, one more if asked meanwhile)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is not None and not self._task.done():
            self._again = True
            return
        self._task = loop.create_task(self._run())

    async def _run(self) -> None:
        while True:
            self._again = False
            try:
                await self.sweep()
            except Exception:
                log.exception("cache budget sweep failed")
            if not self._again:
                return

    def start(self) -> None:
        async def periodic() -> None:
            while True:
                self.request()
                await asyncio.sleep(self.interval_s)

        self._loop_task = asyncio.get_running_loop().create_task(periodic())

    async def stop(self) -> None:
        for t in (self._loop_task, self._task):
            if t is not None and not t.done():
                t.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await t
