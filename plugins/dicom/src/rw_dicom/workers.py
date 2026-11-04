"""Bounded worker processes that convert one series each at a time (ADR-0042 §7).

The coordinator keeps the plan and every record; a worker receives one pickled job, runs
`pipeline.convert_unit` and returns its plain-data result. Workers are direct children (Linux:
they die with the coordinator), ignore terminal signals the coordinator handles, and share its
process group, so ct_viewer's owned-process cleanup covers them. A worker that dies mid-unit gets
that unit retried once in a fresh worker; a second death fails it as `worker_crashed`.
"""

from __future__ import annotations

import contextlib
import os
import pickle
import selectors
import signal
import struct
import subprocess
import sys
from collections import deque
from collections.abc import Callable, Iterable
from typing import IO, Any, Self

FRAME = struct.Struct("!Q")
UNITS_PER_WORKER = 200  # recycle a worker to bound native-memory growth
Job = tuple[int, Callable[[], dict[str, Any]], int | None]  # (order, payload factory, estimate MiB)


def _send(stream: IO[bytes], obj: Any) -> None:
    data = pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(FRAME.pack(len(data)) + data)
    stream.flush()


def _recv(stream: IO[bytes]) -> Any:
    head = stream.read(FRAME.size)
    if len(head) < FRAME.size:
        return None
    (size,) = FRAME.unpack(head)
    data = stream.read(size)
    if len(data) < size:
        return None
    return pickle.loads(data)


def _vm_mb() -> int:
    try:
        for line in open("/proc/self/status").read().splitlines():  # noqa: SIM115 - tiny proc file
            if line.startswith("VmSize:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


class _Worker:
    def __init__(self) -> None:
        env = {
            **os.environ,
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS": "1",
        }
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "rw_dicom.workers"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.stdin, self.stdout = self.proc.stdin, self.proc.stdout
        hello = _recv(self.stdout)
        if not isinstance(hello, dict):
            self.kill()
            raise RuntimeError("A conversion worker failed to start")  # noqa: TRY004 - not a type error
        self.baseline_mb = int(hello.get("vm_mb", 0))
        self.job: Job | None = None
        self.done = 0

    def kill(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self.proc.kill()
        self.proc.wait()

    def close(self, grace_s: float = 5.0) -> None:
        with contextlib.suppress(OSError):
            self.stdin.close()
        try:
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                self.kill()


class WorkerSet:
    def __init__(self, count: int, units_per_worker: int = UNITS_PER_WORKER) -> None:
        if count < 1:
            raise ValueError("At least one worker is required")
        self.count = count
        self.units_per_worker = units_per_worker
        self.workers: list[_Worker] = []

    def __enter__(self) -> Self:
        return self

    def close(self) -> None:
        self.__exit__(None)

    def __exit__(self, kind: type[BaseException] | None, *_: object) -> None:
        for worker in self.workers:
            if kind is not None:  # interrupted: stop native work now, not after the unit
                worker.kill()
            else:
                worker.close()
        self.workers.clear()

    def run(
        self,
        jobs: Iterable[Job],
        *,
        budget_mb: int | None,
        stop: Callable[[], bool],
        on_result: Callable[[int, dict[str, Any]], None],
    ) -> None:
        """Dispatch while `stop()` is false; in-flight units always finish and report."""
        pending: deque[Job] = deque(jobs)
        crashes: dict[int, int] = {}
        selector = selectors.DefaultSelector()
        try:
            while True:
                self._dispatch(pending, budget_mb, stop, on_result, selector)
                busy = [w for w in self.workers if w.job is not None]
                if not busy:
                    break
                for key, _ in selector.select(timeout=0.2):
                    worker: _Worker = key.data
                    job = worker.job
                    assert job is not None
                    result = _recv(worker.stdout)
                    selector.unregister(worker.stdout)
                    worker.job = None
                    if result is None:  # the worker died during this unit
                        self.workers.remove(worker)
                        worker.kill()
                        crashes[job[0]] = crashes.get(job[0], 0) + 1
                        if crashes[job[0]] == 1:
                            pending.appendleft(job)
                        else:
                            on_result(
                                job[0],
                                {
                                    "status": "failed",
                                    "error": "WorkerCrashed: the conversion process ended "
                                    f"unexpectedly (exit code {worker.proc.returncode}) twice",
                                    "category": "worker_crashed",
                                },
                            )
                        continue
                    on_result(*result)
                    worker.done += 1
                    if worker.done >= self.units_per_worker:
                        self.workers.remove(worker)
                        worker.close()
        finally:
            selector.close()

    def _dispatch(
        self,
        pending: deque[Job],
        budget_mb: int | None,
        stop: Callable[[], bool],
        on_result: Callable[[int, dict[str, Any]], None],
        selector: selectors.BaseSelector,
    ) -> None:
        while pending and not stop():
            idle = next((w for w in self.workers if w.job is None), None)
            if idle is None and len(self.workers) >= self.count:
                return
            order, make, estimate = pending[0]
            in_flight = [w.job[2] or 0 for w in self.workers if w.job is not None]
            if budget_mb is not None:
                baselines = sum(w.baseline_mb for w in self.workers)
                if idle is None:
                    baselines += max((w.baseline_mb for w in self.workers), default=0)
                need = baselines + sum(in_flight) + (estimate or 0)
                if estimate is None or need > budget_mb:
                    if in_flight:
                        return  # wait until running units release their share
                    pending.popleft()
                    on_result(
                        order,
                        {
                            "status": "waiting_for_resources",
                            "detail": {
                                "budget_mb": budget_mb,
                                "required_mb": None if estimate is None else need,
                                "reason": "unknown_geometry" if estimate is None else "memory_budget",
                                "remedy": "configure:DICOM_MEMORY_MB",
                            },
                        },
                    )
                    continue
            worker = idle or self._spawn()
            pending.popleft()
            worker.job = (order, make, estimate)
            _send(worker.stdin, (order, make()))
            selector.register(worker.stdout, selectors.EVENT_READ, worker)

    def _spawn(self) -> _Worker:
        worker = _Worker()
        self.workers.append(worker)
        return worker


def _arm_parent_death() -> None:
    """Linux: the kernel kills this worker when its coordinator dies, even by SIGKILL."""
    if not sys.platform.startswith("linux"):
        return
    import ctypes

    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot arm worker parent-death cleanup")
    if os.getppid() != parent:
        os._exit(1)


def main() -> int:
    _arm_parent_death()
    for sig in (signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)  # the coordinator decides how to stop
    protocol_out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)  # native libraries may print; only frames go to the coordinator
    from rw_dicom import inventory, pipeline

    _send(protocol_out, {"vm_mb": _vm_mb()})
    while (job := _recv(sys.stdin.buffer)) is not None:
        order, payload = job
        if "parse" in payload:  # discovery: header facts of a chunk of files
            result: Any = {"parsed": [inventory.parse_header(p, *payload["parse"]) for p in payload["paths"]]}
        else:
            result = pipeline.convert_unit(payload)
        _send(protocol_out, (order, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
