"""OPS-16/17: observed host prerequisites are not proof of effective containment."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def command(argv: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(argv, capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, type(exc).__name__
    detail = (result.stdout if result.returncode == 0 else result.stderr).decode(errors="replace")
    return result.returncode == 0, detail.strip()[-500:]


def controllers(control_group: str) -> set[str]:
    relative = Path(control_group.lstrip("/"))
    if not control_group.startswith("/") or ".." in relative.parts:
        return set()
    try:
        root = Path("/sys/fs/cgroup") / relative
        return set((root / "cgroup.controllers").read_text().split())
    except OSError:
        return set()


def storage_bounded(root: str, maximum: str) -> bool:
    try:
        path = Path(root)
        budget = int(maximum)
        if (
            not path.is_absolute()
            or path.parent == path
            or path.resolve() != path
            or not path.is_mount()
            or budget <= 0
        ):
            return False
        owner = path.stat()
        if owner.st_uid != os.getuid() or owner.st_mode & 0o022:
            return False
        stat = os.statvfs(path)
        return 0 < stat.f_blocks * stat.f_frsize <= budget
    except (OSError, ValueError):
        return False


def inspect_host() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, observed: bool, detail: str, *, required: bool = True) -> None:
        checks.append(
            {
                "name": name,
                "observed": observed,
                "verified": False,
                "required": required,
                "detail": detail,
            }
        )

    add("linux", sys.platform == "linux", "Linux cgroup v2/user-service backend required")
    systemctl, loginctl = shutil.which("systemctl"), shutil.which("loginctl")
    manager_ok, group = (
        command([systemctl, "--user", "show", "--property=ControlGroup", "--value"])
        if systemctl
        else (False, "systemctl missing")
    )
    add("user_manager", manager_ok and bool(group), "An accessible systemd user manager is required")
    available = controllers(group) if manager_ok else set()
    add(
        "controllers",
        {"cpu", "memory", "pids"} <= available,
        "Delegated cpu, memory and pids controllers are required",
    )
    linger_ok, linger = (
        command([loginctl, "show-user", str(os.getuid()), "--property=Linger", "--value"])
        if loginctl
        else (False, "loginctl missing")
    )
    add(
        "logout_persistence",
        linger_ok and linger == "yes",
        "User lingering is required; no policy changes are made",
    )
    unshare, true = shutil.which("unshare"), shutil.which("true")
    namespaces_ok, detail = (
        command([unshare, "--user", "--map-root-user", "--mount", "--net", true])
        if unshare and true
        else (False, "unshare/true missing")
    )
    add(
        "namespace_probe",
        namespaces_ok,
        detail or "Disposable user/mount/network namespace probe",
        required=False,
    )
    add(
        "bounded_storage",
        storage_bounded(
            os.environ.get("RW_RUNNER_STORAGE_ROOT", ""),
            os.environ.get("RW_RUNNER_STORAGE_MAX_BYTES", "0"),
        ),
        "Configure an independently bounded mounted scratch/output filesystem and its byte budget",
    )
    add(
        "effective_containment",
        False,
        "P7g per-attempt supervision and effective filesystem/device/network/resource acceptance are not yet verified",
    )
    return {
        "report": 1,
        "ready": False,
        "prerequisites_ready": all(check["observed"] for check in checks[:-1] if check["required"]),
        "checks": checks,
        "blockers": [check["name"] for check in checks if check["required"] and not check["observed"]],
        "policy_changed": False,
        "gpu_work_started": False,
    }
