"""BE-06 with real spawn worker processes: units must be module-level (picklable)."""

from __future__ import annotations

import asyncio
import os
import time

from app.events.bus import EventBus
from app.jobs.manager import JobManager
from app.jobs.types import JobSpec, WorkUnit


def pid_of(x: int) -> tuple[int, int]:
    return x, os.getpid()


def fail(x: int) -> int:
    raise ValueError(f"unit {x}")


def slow(x: int) -> int:
    time.sleep(0.2)
    return x


def test_spawn_pool_success_failure_cancel() -> None:
    async def body() -> None:
        jm = JobManager(EventBus(), 2, inline=False)
        await jm.start()
        try:
            got: list[tuple[int, int]] = []

            async def on_result(r: tuple[int, int]) -> None:
                got.append(r)

            ok = jm.submit(
                JobSpec("p", "index", [WorkUnit(pid_of, (i,)) for i in range(6)], on_result)
            )
            assert (await jm.wait(ok.job_id, 60)).status == "succeeded"
            assert sorted(x for x, _ in got) == list(range(6))
            assert os.getpid() not in {p for _, p in got}

            bad = jm.submit(JobSpec("p", "hash", [WorkUnit(fail, (1,))]))
            done = await jm.wait(bad.job_id, 30)
            assert (done.status, done.error) == ("failed", "ValueError: unit 1")

            long = jm.submit(JobSpec("p", "mesh", [WorkUnit(slow, (i,)) for i in range(50)]))
            await asyncio.sleep(0.3)
            assert jm.cancel(long.job_id).status == "cancelled"
            done = await jm.wait(long.job_id, 10)
            assert done.status == "cancelled" and done.done < 50

            assert await jm.run_in_worker(pid_of, 9) != (9, os.getpid())
        finally:
            await asyncio.wait_for(jm.shutdown(), 10)

    asyncio.run(asyncio.wait_for(body(), 120))
