"""Full SHA-256 job (IMP-09, API-15): hash every referenced source file in job workers.

Sources are only read (`open_source`, BE-03, R1). Results go to `index/hashes.json` in the
project folder (derived and rebuildable, PRJ-10), keyed by alias ref and tagged with the quick
fingerprint seen when hashing; `IndexStore.load` attaches a hash to an item's `image`/`mask`
only while that fingerprint still matches. Never blocks import (PROJECT_FORMAT §Path aliases).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.core.errors import Problem
from app.core.fsio import atomic_write_json, read_json
from app.core.ids import utc_now
from app.core.locks import ProjectLocks
from app.imaging.fingerprint import full_sha256, quick_fingerprint
from app.jobs.types import JobInfo, JobSpec, WorkUnit

if TYPE_CHECKING:
    from app.ingest.models import Item
    from app.jobs.manager import JobManager

log = logging.getLogger("app.ingest.hashing")

HASHES = "hashes.json"
# (ref, absolute path) → (ref, quick fp, sha256, error)
HashTask = tuple[str, str]
HashResult = tuple[str, str | None, str | None, str | None]


class FileHash(BaseModel):
    fp: str  # quick fingerprint of the file when it was hashed
    sha256: str
    hashed_at: str


class HashIndex(BaseModel):
    """`index/hashes.json`."""

    files: dict[str, FileHash] = Field(default_factory=dict)  # alias ref -> hash


class HashJobRequest(BaseModel):
    force: bool = Field(False, description="Re-hash files that already have a current hash")


class HashJobStarted(BaseModel):
    """API-15 `202`: progress and completion arrive as `job.*` SSE events (API-40)."""

    job_id: str
    n_files: int  # files queued (one job unit each)
    n_skipped: int  # already hashed with a matching quick fingerprint (unless `force`)


def hashes_path(index_dir: Path) -> Path:
    return index_dir / HASHES


def load_hashes(index_dir: Path) -> HashIndex:
    p = hashes_path(index_dir)
    if not p.exists():
        return HashIndex()
    try:
        return HashIndex.model_validate(read_json(p))
    except (ValueError, OSError):
        log.warning("ignoring unreadable hashes.json", extra={"path": str(p)})
        return HashIndex()


def hash_file(ref: str, path: str) -> HashResult:
    """Worker: quick fingerprint + full SHA-256 of one source file (read-only)."""
    try:
        p = Path(path)
        return ref, quick_fingerprint(p), full_sha256(p), None
    except OSError as exc:  # logged: the ref, never the absolute path (NFR-17)
        return ref, None, None, f"{type(exc).__name__}: {exc}".replace(path, ref)


async def start_hash_job(
    *,
    project_id: str,
    index_dir: Path,
    items: Sequence[Item],
    resolve: Callable[[str], Path],
    jobs: JobManager,
    locks: ProjectLocks,
    on_written: Callable[[], None],
    force: bool = False,
) -> HashJobStarted:
    """Submit a `hash` job (BE-06; one per project) over the items' image and mask files.

    `resolve(ref) -> Path` is the project's guarded resolver (BE-02); `on_written()` runs after
    `hashes.json` changes (index cache invalidation).
    """
    current = load_hashes(index_dir).files
    tasks: dict[str, HashTask] = {}
    skipped = 0
    for item in items:
        for vol in item.volumes():
            if vol is None or vol.fp is None or vol.ref in tasks:
                continue
            known = current.get(vol.ref)
            if not force and known is not None and known.fp == vol.fp:
                skipped += 1
                continue
            try:
                tasks[vol.ref] = (vol.ref, str(resolve(vol.ref)))
            except Problem:
                continue  # unresolvable now (relink needed); nothing to hash
    results: list[HashResult] = []

    async def on_result(result: Any) -> None:
        results.append(result)

    async def on_finish(info: JobInfo) -> str | None:
        # Keep whatever was hashed, also when cancelled or interrupted.
        ok = [r for r in results if r[1] is not None and r[2] is not None]
        failed = [r for r in results if r[3] is not None]
        if failed:
            log.warning("hashing failed", extra={"n_failed": len(failed), "first": failed[0][3]})
        if ok:
            async with locks(project_id):
                idx = load_hashes(index_dir)
                now = utc_now()
                for ref, fp, sha, _ in ok:
                    assert fp is not None and sha is not None
                    idx.files[ref] = FileHash(fp=fp, sha256=sha, hashed_at=now)
                atomic_write_json(hashes_path(index_dir), idx.model_dump(mode="json"))
            on_written()
        return None

    units = [WorkUnit(hash_file, t) for t in tasks.values()]
    info = jobs.submit(
        JobSpec(
            project_id=project_id,
            kind="hash",
            units=units,
            on_result=on_result,
            on_finish=on_finish,
        )
    )
    return HashJobStarted(job_id=info.job_id, n_files=len(units), n_skipped=skipped)
