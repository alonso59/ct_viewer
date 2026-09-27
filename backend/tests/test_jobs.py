"""BE-06 / BE-13 job manager (inline thread pool) and API-41."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.errors import JobConflict, NotFound, ServerBusy
from app.events.bus import EventBus
from app.events.types import Event
from app.jobs import manager as manager_mod
from app.jobs.manager import JobManager
from app.jobs.types import JobInfo, JobSpec, WorkUnit

TIMEOUT = 10.0


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(asyncio.wait_for(coro, TIMEOUT))


def square(x: int) -> int:
    return x * x


def boom(x: int) -> int:
    raise ValueError(f"bad {x}")


def sleepy(s: float) -> float:
    time.sleep(s)
    return s


GATE = threading.Event()


async def until(cond: Callable[[], bool], timeout: float = 5) -> None:
    """Wait for a condition instead of a fixed sleep (AUD-A6-19)."""
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)


def gated(x: int) -> int:
    GATE.wait(5)
    return x


def events(bus: EventBus, kind: str) -> list[Event]:
    return [e for e in bus._buffers.get("p", ()) if e.event == kind]


async def started(workers: int = 2) -> tuple[EventBus, JobManager]:
    bus = EventBus()
    jm = JobManager(bus, workers, inline=True)
    await jm.start()
    return bus, jm


def test_success_results_progress_and_finish() -> None:
    async def body() -> None:
        bus, jm = await started()
        results: list[int] = []
        seen: list[str] = []

        async def on_result(r: int) -> None:
            results.append(r)

        async def on_finish(info: JobInfo) -> str | None:
            seen.append(info.status)
            return "imp-1"

        spec = JobSpec(
            "p", "index", [WorkUnit(square, (i,)) for i in range(10)], on_result, on_finish
        )
        info = jm.submit(spec)
        assert info.status == "queued" and info.total == 10
        done = await jm.wait(info.job_id, 5)
        assert done.status == "succeeded" and done.done == 10 and done.ref == "imp-1"
        assert done.started_at and done.finished_at and done.eta_s == 0.0
        assert sorted(results) == [i * i for i in range(10)]
        assert seen == ["succeeded"]
        prog = events(bus, "job.progress")
        assert prog[-1].data == {
            "job_id": info.job_id,
            "kind": "index",
            "done": 10,
            "total": 10,
            "eta_s": 0.0,
        }
        fin = events(bus, "job.finished")
        assert [e.data for e in fin] == [
            {"job_id": info.job_id, "kind": "index", "status": "succeeded", "ref": "imp-1"}
        ]
        assert jm.active("p", "index") is None
        await jm.shutdown()

    run(body())


def test_spec_ref_fallback_and_empty_job() -> None:
    async def body() -> None:
        _, jm = await started()
        info = jm.submit(JobSpec("p", "hash", [], ref="r0"))
        done = await jm.wait(info.job_id, 5)
        assert (done.status, done.ref, done.total) == ("succeeded", "r0", 0)
        await jm.shutdown()

    run(body())


def test_unit_failure_fails_job_and_stops_scheduling() -> None:
    async def body() -> None:
        bus, jm = await started(workers=1)
        calls: list[int] = []

        async def on_result(r: int) -> None:
            calls.append(r)

        seen: list[str] = []

        async def on_finish(info: JobInfo) -> str | None:
            seen.append(info.status)
            return None

        units = [WorkUnit(square, (1,)), WorkUnit(boom, (2,))] + [
            WorkUnit(square, (i,)) for i in range(3, 50)
        ]
        info = jm.submit(JobSpec("p", "radiomics", units, on_result, on_finish))
        done = await jm.wait(info.job_id, 5)
        assert done.status == "failed" and done.error == "ValueError: bad 2"
        assert calls == [1] and done.done == 1 and seen == ["failed"]
        assert events(bus, "job.finished")[0].data["status"] == "failed"
        await jm.shutdown()

    run(body())


def test_on_result_and_on_finish_exceptions_fail_job() -> None:
    async def body() -> None:
        _, jm = await started()

        async def bad_result(r: int) -> None:
            raise RuntimeError("write failed")

        async def bad_finish(info: JobInfo) -> str | None:
            raise KeyError("x")

        a = jm.submit(JobSpec("p", "index", [WorkUnit(square, (2,))], bad_result))
        b = jm.submit(JobSpec("p", "hash", [WorkUnit(square, (2,))], on_finish=bad_finish))
        ra, rb = await jm.wait(a.job_id, 5), await jm.wait(b.job_id, 5)
        assert (ra.status, ra.error) == ("failed", "RuntimeError: write failed")
        assert (rb.status, rb.error) == ("failed", "KeyError: 'x'")
        await jm.shutdown()

    run(body())


def test_conflict_cancel_and_lookup() -> None:
    async def body() -> None:
        GATE.clear()
        bus, jm = await started()
        finished: list[str] = []

        async def on_finish(info: JobInfo) -> str | None:
            finished.append(info.status)
            return None

        units = [WorkUnit(gated, (i,)) for i in range(100)]
        info = jm.submit(JobSpec("p", "thumbnail", units, on_finish=on_finish, job_id="J1"))
        assert info.job_id == "J1" and jm.active("p", "thumbnail") is info
        assert jm.busy("p") is info and jm.busy("q") is None  # AUD-A5-10 (PRJ-06)
        with pytest.raises(JobConflict):
            jm.submit(JobSpec("p", "thumbnail", []))
        other = jm.submit(JobSpec("p", "thumbnail", [], exclusive=False))
        jm.submit(JobSpec("q", "thumbnail", []))  # other project: fine
        await until(lambda: jm.get("J1").status == "running")
        c = jm.cancel("J1")
        assert c.status == "cancelled" and jm.active("p", "thumbnail") is None
        GATE.set()
        done = await jm.wait("J1", 5)
        assert done.status == "cancelled" and done.done < 100 and finished == ["cancelled"]
        assert jm.cancel("J1") is done  # terminal: unchanged
        assert [
            e.data["status"] for e in events(bus, "job.finished") if e.data["job_id"] == "J1"
        ] == ["cancelled"]
        with pytest.raises(NotFound):
            jm.get("nope")
        with pytest.raises(NotFound):
            jm.cancel("nope")
        await jm.wait(other.job_id, 5)
        assert [i.job_id for i in jm.list("p")] == [other.job_id, "J1"]
        assert len(jm.list()) == 3
        await jm.shutdown()

    run(body())


def test_bounded_inflight() -> None:
    async def body() -> None:
        _, jm = await started(workers=2)
        live = 0
        peak = 0
        lock = threading.Lock()

        def count() -> None:
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.01)
            with lock:
                live -= 1

        info = jm.submit(JobSpec("p", "mesh", [WorkUnit(count) for _ in range(20)]))
        assert (await jm.wait(info.job_id, 5)).done == 20
        assert peak <= 2
        await jm.shutdown()

    run(body())


def test_progress_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_mod, "PROGRESS_INTERVAL_S", 0.1)

    async def body() -> None:
        bus, jm = await started(workers=1)
        info = jm.submit(JobSpec("p", "index", [WorkUnit(sleepy, (0.01,)) for _ in range(40)]))
        t0 = time.monotonic()
        await jm.wait(info.job_id, 5)
        elapsed = time.monotonic() - t0
        prog = events(bus, "job.progress")
        assert prog[0].data["done"] == 0 and prog[0].data["eta_s"] is None
        assert prog[-1].data["done"] == 40
        assert len(prog) <= elapsed / 0.1 + 3
        assert all(p.data["eta_s"] is not None for p in prog[1:])
        await jm.shutdown()

    run(body())


def test_retention_keeps_recent_terminal_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_mod, "KEEP_TERMINAL", 3)

    async def body() -> None:
        _, jm = await started()
        ids = [jm.submit(JobSpec("p", "hash", [], exclusive=False)).job_id for _ in range(5)]
        await jm.wait(ids[-1], 5)  # FIFO: the earlier ones finished first
        assert [i.job_id for i in jm.list()] == ids[:1:-1]
        await jm.shutdown()

    run(body())


def test_shutdown_interrupts_and_rejects() -> None:
    async def body() -> None:
        GATE.clear()
        bus, jm = await started()
        seen: list[str] = []

        async def on_finish(info: JobInfo) -> str | None:
            seen.append(info.status)
            return "partial"

        info = jm.submit(
            JobSpec(
                # one gated unit: the second worker stays free for run_in_worker (AUD-A6-19)
                "p",
                "radiomics",
                [WorkUnit(gated, (0,))],
                on_finish=on_finish,
            )
        )
        await until(lambda: jm.get(info.job_id).status == "running")
        assert await jm.run_in_worker(square, 7) == 49
        # AUD-A6-19: shutdown marks the job at once; the gate opens then, not after a 5 s timeout
        stop = asyncio.create_task(jm.shutdown())
        await until(lambda: jm.get(info.job_id).status == "interrupted")
        GATE.set()
        await stop
        got = jm.get(info.job_id)
        assert got.status == "interrupted" and got.ref == "partial" and seen == ["interrupted"]
        assert [e.data["status"] for e in events(bus, "job.finished")] == ["interrupted"]
        with pytest.raises(ServerBusy):
            jm.submit(JobSpec("p", "hash", []))
        with pytest.raises(ServerBusy):
            await jm.run_in_worker(square, 1)
        await jm.shutdown()  # idempotent

    run(body())


def test_shutdown_bounds_slow_on_finish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_mod, "SHUTDOWN_FINISH_TIMEOUT_S", 0.2)

    async def body() -> None:
        GATE.clear()
        bus, jm = await started()

        async def hang(info: JobInfo) -> str | None:
            await asyncio.sleep(60)
            return None

        info = jm.submit(JobSpec("p", "mesh", [WorkUnit(gated, (1,))], on_finish=hang))
        await until(lambda: jm.get(info.job_id).status == "running")
        await asyncio.wait_for(jm.shutdown(), 3)
        GATE.set()
        assert jm.get(info.job_id).status == "interrupted"
        assert len(events(bus, "job.finished")) == 1

    run(body())


def test_jobs_api(client: TestClient) -> None:
    ctx = client.app.state.ctx  # type: ignore[attr-defined]

    async def submit() -> str:
        info = ctx.jobs.submit(JobSpec("p1", "hash", [WorkUnit(square, (3,))]))
        await ctx.jobs.wait(info.job_id, 5)
        return str(info.job_id)

    job_id = client.portal.call(submit)  # type: ignore[union-attr]
    r = client.get("/api/v1/jobs", params={"project": "p1"})
    assert r.status_code == 200 and [j["job_id"] for j in r.json()] == [job_id]
    assert client.get("/api/v1/jobs", params={"project": "zz"}).json() == []
    r = client.get(f"/api/v1/jobs/{job_id}")
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    r = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "succeeded"
    for r in (client.get("/api/v1/jobs/nope"), client.post("/api/v1/jobs/nope/cancel")):
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/problem+json")
