"""The shared run lifecycle `jobs.runs.RunStore` (AUD-A6-06): one `run.json` protocol for task
runs (TSK-06/07/10) and radiomics runs (RAD-08/09, RAD-13), restart reconcile (BE-06)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from app.core.errors import JobConflict, NotFound, ServerBusy
from app.core.ids import new_ulid
from app.core.locks import ProjectLocks
from app.jobs.manager import JobManager
from app.jobs.runs import RunStore
from app.jobs.types import JobSpec


class Rec(BaseModel):
    run_id: str
    status: str
    job_id: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class _Jobs:
    """No job is known (a restarted server); `submit` is refused as busy."""

    def get(self, job_id: str) -> Any:
        raise NotFound(job_id)

    def submit(self, spec: JobSpec) -> None:
        raise ServerBusy("queue full")


def _store(tmp_path: Path) -> RunStore[Rec]:
    return RunStore(
        Rec,
        lambda pid: tmp_path / pid / "runs",
        cast(JobManager, _Jobs()),
        ProjectLocks(),
        terminal=frozenset({"completed", "failed", "cancelled", "interrupted"}),
        resumable=frozenset({"failed", "cancelled", "interrupted"}),
        noun="Run",
    )


def _new(store: RunStore[Rec], status: str) -> Path:
    rid = new_ulid()
    d = store.runs_dir("p") / rid
    d.mkdir(parents=True)
    store.write(d, Rec(run_id=rid, status=status, job_id=new_ulid()))
    return d


def test_status_moves_forward_and_restart_reconciles(tmp_path: Path) -> None:
    store = _store(tmp_path)
    d = _new(store, "queued")
    assert store.has("p", d.name) and not store.has("p", "not-a-ulid")
    with pytest.raises(NotFound):
        store.run_dir("p", new_ulid())
    asyncio.run(store.set_status("p", d, "running"))
    rec = store.read(d)
    assert rec.status == "running" and rec.started_at
    # the job is unknown to this process → interrupted, and then resumable
    assert asyncio.run(store.reconcile("p", d)).status == "interrupted"
    asyncio.run(store.set_status("p", d, "running"))  # a terminal run keeps its status
    assert store.read(d).status == "interrupted" and store.read(d).finished_at
    assert asyncio.run(store.resumable("p", d)).status == "interrupted"
    done = _new(store, "completed")
    with pytest.raises(JobConflict):
        asyncio.run(store.resumable("p", done))
    assert [p.name for p in store.run_dirs("p")] == sorted([d.name, done.name], reverse=True)


def test_refused_submit_records_failed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    d = _new(store, "interrupted")
    cleaned: list[bool] = []

    async def noop(_: Any) -> None:
        return None

    spec = JobSpec(project_id="p", kind="task", units=[], driver=noop, job_id=new_ulid())
    with pytest.raises(ServerBusy):
        asyncio.run(store.submit("p", d, spec, on_error=lambda: cleaned.append(True)))
    rec = store.read(d)
    assert rec.status == "failed" and rec.job_id == spec.job_id and rec.error == "queue full"
    assert cleaned == [True]
