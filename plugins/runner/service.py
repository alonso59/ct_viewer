"""Per-attempt unprivileged systemd ownership and resource controls."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any


def command(argv: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def unit_name(attempt: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", attempt):
        raise ValueError("invalid attempt identity")
    return f"rw-seg-{attempt}.service"


def verify_limits(group: Path, limits: dict[str, int]) -> None:
    """Verify kernel limits for this attempt before its task process starts."""
    for name, maximum in {
        "memory.max": limits["memory_mb"] * 1024**2,
        "pids.max": limits["tasks"],
        "memory.swap.max": 0,
    }.items():
        value = (group / name).read_text().strip()
        if value == "max" or int(value) > maximum:
            raise ValueError(f"attempt resource bound not enforced: {name}")
    quota, period = (group / "cpu.max").read_text().split()
    if quota == "max" or int(period) <= 0 or not 0 < int(quota) <= int(period) * limits["cpus"]:
        raise ValueError("attempt resource bound not enforced: cpu.max")


def show(attempt: str) -> dict[str, str]:
    result = command(
        [
            "systemctl",
            "--user",
            "show",
            unit_name(attempt),
            "--property=LoadState",
            "--property=ActiveState",
            "--property=SubState",
            "--property=InvocationID",
            "--property=ControlGroup",
            "--property=Description",
            "--property=ExecMainStatus",
            "--property=Result",
        ]
    )
    if result.returncode:
        raise ValueError("user-service state unavailable")
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def owned(record: dict[str, Any], state: dict[str, str]) -> bool:
    return (
        record.get("uid") == os.getuid()
        and record.get("boot_id") == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and state.get("Description") == f"RW attempt {record['attempt']}"
        and bool(state.get("InvocationID"))
        and (not record.get("invocation") or state["InvocationID"] == record["invocation"])
    )


def empty(state: dict[str, str]) -> bool:
    if state.get("ActiveState") not in {"inactive", "failed"}:
        return False
    group = state.get("ControlGroup", "")
    if not group:
        return True
    path = Path(group)
    if not group.startswith(f"/user.slice/user-{os.getuid()}.slice/") or ".." in path.parts:
        return False
    try:
        events = (Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.events").read_text()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return "populated 0" in events.splitlines()


def launch(record: dict[str, Any], limits: dict[str, int], python: Path, job: Path) -> None:
    properties = [
        "Type=exec",
        "RemainAfterExit=yes",
        "KillMode=control-group",
        "NoNewPrivileges=yes",
        "UMask=0077",
        "TimeoutStopSec=10",
        "SendSIGKILL=yes",
        "MemorySwapMax=0",
        f"CPUQuota={limits['cpus'] * 100}%",
        f"MemoryMax={limits['memory_mb']}M",
        f"TasksMax={limits['tasks']}",
        f"RuntimeMaxSec={limits['seconds']}",
        "LimitFSIZE=2147483648",
        "LimitNOFILE=1024",
    ]
    worker = Path(__file__).with_name("attempt.py")
    argv = [
        "systemd-run",
        "--user",
        "--quiet",
        f"--unit={unit_name(record['attempt'])}",
        f"--description=RW attempt {record['attempt']}",
    ]
    argv += [f"--property={value}" for value in properties]
    argv += [str(python), "-I", str(worker), str(job), record["attempt"]]
    result = command(argv)
    if result.returncode:
        raise ValueError("attempt service launch failed: " + result.stderr.strip()[-500:])


def stop(record: dict[str, Any]) -> bool:
    state = show(record["attempt"])
    if empty(state):
        return True
    if not owned(record, state):
        return False
    result = command(["systemctl", "--user", "stop", unit_name(record["attempt"])], timeout=20)
    return result.returncode == 0 and empty(show(record["attempt"]))
