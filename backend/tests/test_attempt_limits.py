"""OPS-16/19: per-attempt kernel limits must agree with the accepted configuration."""

from pathlib import Path

import pytest
from plugins.runner.service import verify_limits


@pytest.mark.parametrize(
    "changed,value",
    [
        ("memory.max", "max"),
        ("memory.max", str(129 * 1024**2)),
        ("pids.max", "max"),
        ("pids.max", "17"),
        ("memory.swap.max", "1"),
        ("cpu.max", "max 100000"),
        ("cpu.max", "200000 100000"),
    ],
)
def test_attempt_refuses_unenforced_or_excessive_kernel_limits(
    tmp_path: Path,
    changed: str,
    value: str,
) -> None:
    contents = {
        "memory.max": str(128 * 1024**2),
        "pids.max": "16",
        "memory.swap.max": "0",
        "cpu.max": "100000 100000",
        changed: value,
    }
    for name, content in contents.items():
        (tmp_path / name).write_text(content)
    with pytest.raises((ValueError, OSError)):
        verify_limits(tmp_path, {"cpus": 1, "memory_mb": 128, "tasks": 16})


def test_attempt_accepts_stricter_kernel_limits(tmp_path: Path) -> None:
    for name, value in {
        "memory.max": str(64 * 1024**2),
        "pids.max": "8",
        "memory.swap.max": "0",
        "cpu.max": "25000 100000",
    }.items():
        (tmp_path / name).write_text(value)
    verify_limits(tmp_path, {"cpus": 1, "memory_mb": 128, "tasks": 16})
