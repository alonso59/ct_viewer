"""SEG-07: displayed availability uses the same fail-closed rule as admission."""

from __future__ import annotations

import pytest
from plugins.runner import gpu
from plugins.runner.supervised import Supervisor


def test_display_and_admission_use_free_memory_even_with_compute_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "index": str(i),
            "uuid": f"GPU-{i}",
            "total_mb": 46068,
            "used_mb": used,
            "utilization": util,
            "pids": pids,
        }
        for i, (used, util, pids) in enumerate(
            [(40000, 0, []), (0, 100, []), (10000, 100, [42]), (0, 0, [])]
        )
    ]
    supervisor = object.__new__(Supervisor)
    supervisor.config = {"gpu_pool": ["0", "1", "2", "3"]}
    monkeypatch.setattr(gpu, "inventory", lambda: rows)
    devices = supervisor.inventory_snapshot()["devices"]
    assert [d["busy"] for d in devices] == [True, False, False, False]
    assert supervisor.inventory_snapshot()["required_free_mb"] == gpu.MIN_FREE_MB
    assert all("pids" not in d for d in devices)
    assert gpu.select_devices(rows, ["0", "1", "2", "3"], [], 1) == ["GPU-1"]
