"""OPS-03 `CACHE_MAX_GB` (AUD-A4-16): one LRU budget over Open-mode scratch and every project's
disposable `cache/` (meshes, thumbnails, npy→NIfTI); PRJ-10 (cache is disposable), R1 (nothing
outside those pools is touched)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.cache_budget import CacheBudget, Pool, enforce, touch, workspace_pools
from app.jobs.types import JobSpec, WorkUnit
from app.main import create_app
from tests.conftest import make_settings
from tests.test_api_ingest import ctx_of, wait

API = "/api/v1"
KB = 1024


def put(path: Path, size: int, age_s: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    t = time.time() - age_s
    os.utime(path, (t, t))
    return path


def layout(ws: Path) -> dict[str, Path]:
    """Two projects with cache files, Open scratch, and files that must never be evicted."""
    p1, p2 = ws / "projects" / "P1", ws / "projects" / "P2"
    f = {
        "open_old": put(ws / ".scratch" / "open" / "fp1.xyz" / "volume.nii.gz", 10 * KB, 5000),
        "mesh_old": put(p1 / "cache" / "meshes" / "a_1_1.mz3", 10 * KB, 4000),
        "thumb_mid": put(p2 / "cache" / "thumbs" / "b.webp", 10 * KB, 3000),
        "npy_new": put(p1 / "cache" / "npy" / "c.nii.gz", 10 * KB, 2000),
        # never evicted: outside the pools, temp files, archived projects, a recent write
        "events": put(p1 / "curation" / "events.jsonl", 50 * KB, 9000),
        "preview": put(p1 / "cache" / "previews" / "pv" / "identity.json", 50 * KB, 9000),
        "tmp": put(p1 / "cache" / "meshes" / ".x.mz3.abc.tmp", 50 * KB, 9000),
        "archived": put(
            ws / "projects" / ".archive" / "P3" / "cache" / "meshes" / "m.mz3", KB, 9000
        ),
        "jobs": put(ws / ".scratch" / "jobs" / "j1" / "out.json", 50 * KB, 9000),
        "fresh": put(p2 / "cache" / "meshes" / "fresh.mz3", 10 * KB, 1),
    }
    return f


def test_lru_across_pools_keeps_everything_else(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    f = layout(ws)
    outside = put(tmp_path / "data" / "image.nii.gz", KB, 9000)
    (ws / "projects" / "P1" / "cache" / "meshes" / "link.mz3").symlink_to(outside)
    pools = workspace_pools(ws, ws / "projects")
    assert Pool(ws / ".scratch" / "open", "dir") in pools
    assert not any(".archive" in str(p.root) for p in pools)

    # 50 KB in the pools (fresh 10 included) → budget 30 KB: the two oldest units go
    freed = enforce(pools, 30 * KB)
    assert freed == 20 * KB
    assert not f["open_old"].exists() and not f["open_old"].parent.exists()  # a whole folder
    assert not f["mesh_old"].exists()
    for k in ("thumb_mid", "npy_new", "events", "preview", "tmp", "archived", "jobs", "fresh"):
        assert f[k].exists(), k
    assert outside.exists()  # a symlink is never followed or evicted

    # Budget 0: all but the fresh unit (in-flight writes are kept for MIN_AGE_S)
    enforce(pools, 0)
    assert not f["thumb_mid"].exists() and not f["npy_new"].exists()
    assert f["fresh"].exists() and outside.exists()
    for k in ("events", "preview", "tmp", "archived", "jobs"):
        assert f[k].exists(), k


def test_touch_marks_use(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    f = layout(ws)
    touch(f["mesh_old"])  # read on a cache hit: now the most recently used, minus the grace
    pools = workspace_pools(ws, ws / "projects")
    enforce(pools, 30 * KB, min_age_s=0)
    assert f["mesh_old"].exists() and f["fresh"].exists()
    assert not f["open_old"].exists() and not f["thumb_mid"].exists()


def test_under_budget_is_a_no_op(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    f = layout(ws)
    assert enforce(workspace_pools(ws, ws / "projects"), 1024 * KB) == 0
    assert all(p.exists() for p in f.values())


def _noop() -> None:
    return None


def test_a_cache_writing_job_triggers_the_sweep(tmp_path: Path) -> None:
    """The lifespan wires the budget: a finished `thumbnail` job sweeps with CACHE_MAX_GB."""
    settings = make_settings(tmp_path)
    settings.cache_max_gb = 0
    with TestClient(create_app(settings, inline_jobs=True)) as c:
        ctx = ctx_of(c)
        assert ctx.cache_budget is not None and ctx.cache_budget.max_bytes == 0
        pid = c.post(f"{API}/projects", json={"name": "cache"}).json()["project_id"]
        pdir = ctx.workspace.project_dir(pid)

        async def settled() -> None:  # the pending sweep (startup or after a job) has run
            budget = ctx.cache_budget
            assert budget is not None
            for _ in range(200):
                if budget._task is None or budget._task.done():
                    return
                await asyncio.sleep(0.02)

        c.portal.call(settled)
        mesh = put(pdir / "cache" / "meshes" / "old.mz3", KB, 5000)
        config = pdir / "project.json"

        async def job() -> str:
            spec = JobSpec(project_id=pid, kind="thumbnail", units=[WorkUnit(_noop)])
            return ctx.jobs.submit(spec).job_id

        wait(c, c.portal.call(job))
        c.portal.call(settled)
        assert not mesh.exists() and config.exists()


def test_request_is_debounced(tmp_path: Path) -> None:
    calls: list[int] = []

    def pools() -> list[Pool]:
        calls.append(1)
        return []

    async def run() -> None:
        b = CacheBudget(pools, 1)
        for _ in range(5):
            b.request()
        assert b._task is not None
        await b._task
        await b.stop()

    asyncio.run(run())
    assert 1 <= len(calls) <= 2  # one sweep, plus at most one for the requests made meanwhile
