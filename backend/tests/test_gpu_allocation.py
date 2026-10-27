"""SEG-07/08, OPS-16: physical identity, conservative admission, shared leases."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any

import pytest
from plugins.runner.gpu import Pool, device_path, select_devices

ROWS: list[dict[str, Any]] = [
    {"index": "0", "uuid": "GPU-A", "total_mb": 46068, "used_mb": 0, "utilization": 0, "pids": []},
    {"index": "6", "uuid": "GPU-B", "total_mb": 46068, "used_mb": 0, "utilization": 0, "pids": []},
    {"index": "7", "uuid": "GPU-C", "total_mb": 46068, "used_mb": 0, "utilization": 0, "pids": []},
]


@pytest.mark.parametrize("minor", ["5", "missing", "-1"])
def test_driver_uuid_mapping_uses_device_minor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minor: str
) -> None:
    info = tmp_path / "information"
    info.write_text(f"GPU UUID: GPU-B\nDevice Minor: {minor}\n")
    original_glob, original_stat = Path.glob, Path.stat
    device_stat = Path("/dev/zero").stat()
    monkeypatch.setattr(
        Path,
        "glob",
        lambda path, pattern: (
            iter([info])
            if path == Path("/proc/driver/nvidia/gpus")
            else original_glob(path, pattern)
        ),
    )
    monkeypatch.setattr(
        Path,
        "stat",
        lambda path, **kwargs: (
            device_stat if path == Path("/dev/nvidia5") else original_stat(path, **kwargs)
        ),
    )
    if minor == "5":
        assert device_path("GPU-B") == Path("/dev/nvidia5")
    else:
        with pytest.raises(ValueError, match="minor"):
            device_path("GPU-B")
    with pytest.raises(ValueError, match="mapping"):
        device_path("GPU-unknown")


def test_explicit_physical_selection_survives_reordered_inventory() -> None:
    assert select_devices(list(reversed(ROWS)), ["0", "6"], ["6"], 1) == ["GPU-B"]


@pytest.mark.parametrize(
    "field,value", [("used_mb", 40000), ("total_mb", None), ("used_mb", -1), ("used_mb", None)]
)
def test_busy_or_unobservable_requested_gpu_is_refused(field: str, value: Any) -> None:
    rows = [{**row, field: value} if row["index"] == "6" else row for row in ROWS]
    with pytest.raises(ValueError, match=r"insufficient|unknown"):
        select_devices(rows, ["0", "6"], ["6"], 1)


@pytest.mark.parametrize("requested", [["7"], ["GPU-C"], ["6", "GPU-B"], ["9"]])
def test_outside_pool_unknown_and_aliased_requests_are_refused(requested: list[str]) -> None:
    with pytest.raises(ValueError):
        select_devices(ROWS, ["0", "6"], requested, len(requested))


def test_automatic_selection_respects_approved_pool() -> None:
    assert select_devices(ROWS, ["6"], [], 1) == ["GPU-B"]


def test_insufficient_available_gpus_never_return_partial_set() -> None:
    with pytest.raises(ValueError, match="available"):
        select_devices(ROWS, ["0"], [], 2)


def test_separate_workspace_allocators_share_a_durable_host_lease(tmp_path: Path) -> None:
    pool_a, pool_b = Pool(tmp_path / "pool"), Pool(tmp_path / "pool")
    assert pool_a.reserve({"attempt": "first", "gpus": ["GPU-A"]}) is True
    assert pool_b.reserve({"attempt": "second", "gpus": ["GPU-A"]}) is False
    assert pool_b.release("second") is False
    assert pool_a.release("first") is True
    assert pool_b.reserve({"attempt": "second", "gpus": ["GPU-A"]}) is True


def test_pool_symlink_cannot_redirect_host_state(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "pool").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match=r"private|canonical"):
        Pool(tmp_path / "pool").reserve({"attempt": "first", "gpus": ["GPU-A"]})


def test_declined_claim_never_creates_a_reservation(tmp_path: Path) -> None:
    pool = Pool(tmp_path / "pool")
    assert pool.reserve({"attempt": "one", "gpus": ["GPU-A"]}, claim=lambda: False) is False
    assert pool.read() is None


def compete(pool: str, workspace: str, barrier: Any, release: Any, results: Any) -> None:
    allocator = Pool(Path(pool))
    barrier.wait(timeout=10)
    acquired = allocator.reserve({"attempt": workspace, "workspace": workspace, "gpus": ["GPU-A"]})
    results.put((workspace, acquired))
    release.wait(timeout=15)


def test_simultaneous_processes_never_share_the_participating_host_slot(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    barrier, release, results = context.Barrier(3), context.Event(), context.Queue()
    processes = [
        context.Process(
            target=compete, args=(str(tmp_path / "pool"), name, barrier, release, results)
        )
        for name in ("workspace-a", "workspace-b")
    ]
    try:
        for process in processes:
            process.start()
        barrier.wait(timeout=10)
        outcomes = [results.get(timeout=10) for _ in processes]
        winners = [name for name, acquired in outcomes if acquired]
        assert len(winners) == 1, outcomes
        lease = Pool(tmp_path / "pool").read()
        assert lease is not None and lease["workspace"] == winners[0]
        assert Pool(tmp_path / "pool").release("stale-generation") is False
    finally:
        release.set()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        results.close()
    assert all(process.exitcode == 0 for process in processes)


def test_active_gpu_with_sufficient_free_memory_can_be_selected() -> None:
    rows = [{**ROWS[1], "used_mb": 24000, "utilization": 100, "pids": [123]}]
    assert select_devices(rows, ["6"], ["6"], 1, minimum_mb=16000) == ["GPU-B"]
    with pytest.raises(ValueError, match="insufficient"):
        select_devices(rows, ["6"], ["6"], 1, minimum_mb=24000)
