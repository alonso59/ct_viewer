"""OPS-16/17, TST-22: opt-in, GPU-free effective user-service containment probe."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

REQUIRED_CHECKS = frozenset(
    {
        "memory_limit",
        "tasks_limit",
        "swap_limit",
        "cpu_limit",
        "source_visible",
        "read_only",
        "device_policy",
        "network_isolation",
        "setsid_stays_in_cgroup",
    }
)

PROBE = r"""
import errno, json, os, socket, subprocess, sys
from pathlib import Path
readonly, port = Path(sys.argv[1]), int(sys.argv[2])
group = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
root = Path('/sys/fs/cgroup') / group.lstrip('/')
quota, period = (root / 'cpu.max').read_text().split()
checks = {
    'memory_limit': int((root / 'memory.max').read_text()) <= 100663296,
    'tasks_limit': int((root / 'pids.max').read_text()) <= 16,
    'swap_limit': (root / 'memory.swap.max').read_text().strip() == '0',
    'cpu_limit': quota != 'max' and int(quota) / int(period) <= .25,
    'source_visible': readonly.read_text() == 'sentinel',
}
try:
    with readonly.open('a') as handle:
        handle.write('bad')
    checks['read_only'] = False
except OSError as error:
    checks['read_only'] = error.errno in (errno.EACCES, errno.EPERM, errno.EROFS)
try:
    descriptor = os.open('/dev/ptmx', os.O_RDWR | os.O_NOCTTY)
    os.close(descriptor)
    checks['device_policy'] = False
except OSError as error:
    checks['device_policy'] = error.errno in (errno.EACCES, errno.EPERM)
connection = None
try:
    connection = socket.socket()
    connection.settimeout(.5)
    connection.connect(('127.0.0.1', port))
    checks['network_isolation'] = False
except OSError:
    checks['network_isolation'] = True
finally:
    if connection is not None:
        connection.close()
child = subprocess.run(
    [sys.executable, '-c',
     "from pathlib import Path; print(Path('/proc/self/cgroup').read_text().strip())"],
    start_new_session=True, capture_output=True, text=True, timeout=2)
checks['setsid_stays_in_cgroup'] = (
    child.returncode == 0
    and child.stdout.strip() == Path('/proc/self/cgroup').read_text().strip())
print(json.dumps({'checks': checks}), flush=True)
sys.exit(0 if all(checks.values()) else 1)
"""


def run_probe(*, unprivileged: bool = False) -> dict[str, Any]:
    systemd_run, systemctl = shutil.which("systemd-run"), shutil.which("systemctl")
    if not systemd_run or not systemctl:
        return {"ready": False, "error": "systemd user-service tools are missing"}
    unit = f"rw-containment-probe-{uuid.uuid4().hex}.service"
    properties = [
        "RuntimeMaxSec=10",
        "TasksMax=16",
        "MemoryMax=96M",
        "MemorySwapMax=0",
        "CPUQuota=25%",
        "PrivateUsers=yes",
        "PrivateNetwork=yes",
        "ProtectSystem=strict",
        "KillMode=control-group",
        "NoNewPrivileges=yes",
        "DevicePolicy=strict",
        "DeviceAllow=/dev/null rw",
    ]
    if unprivileged:
        properties = [
            value
            for value in properties
            if value.split("=", 1)[0]
            not in {
                "PrivateUsers",
                "PrivateNetwork",
                "ProtectSystem",
                "DevicePolicy",
                "DeviceAllow",
            }
        ]
    with tempfile.TemporaryDirectory(prefix="rw-containment-probe-") as temporary:
        sentinel = Path(temporary) / "readonly"
        sentinel.write_text("sentinel")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            descriptor = os.open("/dev/ptmx", os.O_RDWR | os.O_NOCTTY)
            os.close(descriptor)
            argv = [systemd_run, "--user", "--wait", "--collect", "--pipe", f"--unit={unit}"]
            argv += [f"--property={value}" for value in properties]
            if unprivileged:
                scratch = Path(temporary) / "scratch"
                scratch.mkdir()
                sandbox = Path(__file__).resolve().parents[2] / "plugins/runner/sandbox.py"
                argv += [
                    sys.executable,
                    str(sandbox),
                    "--write",
                    str(scratch),
                    "--",
                    sys.executable,
                ]
            else:
                argv += [sys.executable]
            argv += ["-c", PROBE, str(sentinel), str(listener.getsockname()[1])]
            try:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
                try:
                    raw = json.loads(result.stdout)
                    if not isinstance(raw, dict) or not isinstance(raw.get("checks"), dict):
                        raise TypeError("invalid probe result")
                    report: dict[str, Any] = raw
                except (ValueError, TypeError):
                    report = {"checks": {}, "error": "probe did not complete its checks"}
                report["ready"] = (
                    result.returncode == 0
                    and set(report["checks"]) == REQUIRED_CHECKS
                    and all(value is True for value in report["checks"].values())
                )
                report["source_unchanged"] = sentinel.read_text() == "sentinel"
                report["ready"] = report["ready"] and report["source_unchanged"]
                report["diagnostic"] = result.stderr.strip()[-1500:]
                report["unit"] = unit
                report["policy_changed"] = False
                report["gpu_work_started"] = False
                report["mode"] = "unprivileged" if unprivileged else "strict-namespaces"
                report["blockers"] = sorted(name for name in REQUIRED_CHECKS if report["checks"].get(name) is not True)
                if not report["source_unchanged"]:
                    report["blockers"].append("source_unchanged")
            finally:
                # Only this invocation's random, disposable unit; never a caller-supplied PID/unit.
                stopped = subprocess.run(
                    [systemctl, "--user", "stop", unit], capture_output=True, timeout=5, check=False
                )
                state = subprocess.run(
                    [
                        systemctl,
                        "--user",
                        "show",
                        unit,
                        "--property=LoadState",
                        "--property=ActiveState",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            properties_observed = dict(line.split("=", 1) for line in state.stdout.splitlines() if "=" in line)
            report["cleanup_verified"] = (
                state.returncode == 0
                and properties_observed.get("ActiveState") == "inactive"
                and (stopped.returncode == 0 or properties_observed.get("LoadState") == "not-found")
            )
            if not report["cleanup_verified"]:
                report["blockers"].append("cleanup_unverified")
            report["ready"] = report["ready"] and report["cleanup_verified"]
            return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Create one disposable tightly limited user service")
    parser.add_argument("--unprivileged", action="store_true", help="Use Landlock/seccomp without namespaces")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required; this probe creates a disposable user service")
    try:
        report = run_probe(unprivileged=args.unprivileged)
    except (OSError, subprocess.TimeoutExpired) as exc:
        report = {"ready": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, indent=2))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
