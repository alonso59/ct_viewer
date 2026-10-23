"""SEG-07: displayed availability uses the same fail-closed rule as admission."""

from __future__ import annotations

import pytest
from plugins.runner import gpu
from plugins.runner.supervised import Supervisor


def test_inventory_does_not_report_unattributed_memory_or_utilization_as_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"index": str(i), "uuid": f"GPU-{i}", "used_mb": used, "utilization": util, "pids": pids}
        for i, (used, util, pids) in enumerate([(65, 0, []), (0, 6, []), (0, 0, [42]), (0, 0, [])])
    ]
    supervisor = object.__new__(Supervisor)
    supervisor.config = {"gpu_pool": ["0", "1", "2", "3"]}
    monkeypatch.setattr(gpu, "inventory", lambda: rows)
    devices = supervisor.inventory_snapshot()["devices"]
    assert [d["busy"] for d in devices] == [True, True, True, False]
    assert all("pids" not in d for d in devices)
    assert gpu.select_devices(rows, ["0", "1", "2", "3"], [], 1) == ["GPU-3"]
