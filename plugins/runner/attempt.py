"""Bounded attempt watchdog; executed only inside an owned user-service cgroup."""

from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.protocol import write_json_atomic
from plugins.runner.native import Broker
from plugins.runner.service import verify_limits

STOP = threading.Event()
LOG_LIMIT = 16 * 1024 * 1024
LOG_LOCK = threading.Lock()
LOG_SIZE = 0


def on_signal(_number: int, _frame: Any) -> None:
    STOP.set()


def drain(stream: Any, target: Path) -> None:
    global LOG_SIZE
    with target.open("ab") as handle:
        while chunk := stream.read(65536):
            with LOG_LOCK:
                remaining = max(0, LOG_LIMIT - LOG_SIZE)
                handle.write(chunk[:remaining])
                handle.flush()
                LOG_SIZE += len(chunk)
                if LOG_SIZE > LOG_LIMIT:
                    STOP.set()


def run(job: Path, attempt: str) -> int:
    spec = json.loads((job / "attempt.json").read_text())
    if spec["attempt"] != attempt or spec["uid"] != os.getuid():
        raise ValueError("stale or foreign attempt")
    group = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
    if f"rw-seg-{attempt}.service" not in Path(group).parts:
        raise ValueError("attempt is outside its owned service")
    try:
        verify_limits(Path("/sys/fs/cgroup") / group.lstrip("/"), spec["limits"])
    except (OSError, ValueError) as exc:
        with (job / "task.log").open("a") as handle:
            handle.write(f"Launch blocked: {exc}\n")
        write_json_atomic(job / "worker-exit.json", {"attempt": attempt, "code": 125})
        return 1
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    runtime = Path(spec["runtime_alias"])
    if not runtime.is_symlink() or runtime.resolve() != job / ".runtime":
        raise ValueError("runtime alias does not belong to this attempt")
    for name in ("home", "tmp", "cache"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    env = spec["environment"]
    env.update(
        HOME=str(runtime / "home"),
        TMPDIR=str(runtime / "tmp"),
        XDG_CACHE_HOME=str(runtime / "cache"),
        TORCH_HOME=str(runtime / "cache/torch"),
        TORCHINDUCTOR_CACHE_DIR=str(runtime / "cache/inductor"),
    )
    broker: Broker | None = None
    if spec.get("native_commands"):
        broker = Broker(spec, dict(env), lambda stream: drain(stream, job / "task.log"))
        env.update(RW_NATIVE_SOCKET=str(broker.path), RW_NATIVE_ATTEMPT=attempt)
    sandbox = Path(__file__).with_name("sandbox.py")
    command = [sys.executable, "-I", str(sandbox)]
    for path in spec["write_roots"]:
        command += ["--write", path]
    for path in spec["devices"]:
        command += ["--device", path]
    command += ["--", *spec["command"]]
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    process = subprocess.Popen(
        command,
        cwd=spec["cwd"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        bufsize=0,
    )
    reader = threading.Thread(target=drain, args=(process.stdout, job / "task.log"), daemon=True)
    reader.start()
    termination: float | None = None
    try:
        while process.poll() is None:
            if (job / "cancel").exists() or any(
                shutil.disk_usage(path).free < 64 * 1024 * 1024 for path in spec["write_roots"]
            ):
                STOP.set()
            if STOP.is_set():
                if termination is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    termination = time.monotonic()
                elif time.monotonic() - termination > 5:
                    os.killpg(process.pid, signal.SIGKILL)
            time.sleep(0.1)
        reader.join(timeout=2)
        code = int(process.returncode)
        if STOP.is_set() and code == 0:
            code = -signal.SIGTERM
        write_json_atomic(job / "worker-exit.json", {"attempt": attempt, "code": code})
        return 0 if code == 0 else 1
    finally:
        if broker is not None:
            broker.close()
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()


if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1]), sys.argv[2]))
