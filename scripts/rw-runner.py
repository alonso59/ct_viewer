#!/usr/bin/env python3
"""Host runner for external tasks (TSK-11, BE-14, OPS-13). Standard library only.

Runs on the host, inside the plugin's own environment (e.g. an activated conda env; R4), and
talks to the app only through files under `WORKSPACE_ROOT/queue/`:

    python scripts/rw-runner.py --workspace <WORKSPACE_HOST> --plugins <PLUGINS_ROOT> \
        [--tasks segment.nnunet] [--concurrency 1]

- Heartbeat `queue/runners/{runner_id}.json` `{tasks[], gpu, pid, at}` every 10 s.
- Claims a job by creating `queue/{job_id}/claim` with O_EXCL, then runs the manifest's
  `runtime.command` in the plugin folder (`{python}` = this interpreter, `{job_dir}` = the job
  folder); stdout/stderr go to `task.log`, the exit code to `exit.json`.
- A `cancel` file → SIGTERM, then SIGKILL after 30 s.
The backend writes only `job.json` and `cancel`; this runner and its tasks write the rest.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HEARTBEAT_S = 10.0
KILL_AFTER_S = 30.0


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_manifests(plugins: Path, only: set[str]) -> dict[str, tuple[dict[str, Any], Path]]:
    """External manifests under PLUGINS_ROOT (`*/task.json`), by task id."""
    out: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in sorted(plugins.glob("*/task.json")):
        try:
            m = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runtime = m.get("runtime") or {}
        tid = m.get("id")
        if (
            not isinstance(tid, str)
            or runtime.get("type") != "external"
            or not runtime.get("command")
        ):
            continue
        if only and tid not in only:
            continue
        out[tid] = (m, path.parent)
    return out


@dataclass
class Running:
    job_dir: Path
    proc: subprocess.Popen[bytes]
    log: Any
    term_at: float | None = None


class Runner:
    def __init__(self, workspace: Path, plugins: Path, tasks: set[str], concurrency: int) -> None:
        self.queue = workspace / "queue"
        self.plugins = plugins
        self.only = tasks
        self.concurrency = max(1, concurrency)
        self.runner_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.running: dict[str, Running] = {}
        self.last_beat = 0.0
        self.manifests = load_manifests(plugins, tasks)

    # -- heartbeat ----------------------------------------------------------------------------

    def heartbeat(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_beat < HEARTBEAT_S:
            return
        self.last_beat = now
        (self.queue / "runners").mkdir(parents=True, exist_ok=True)
        write_json(
            self.queue / "runners" / f"{self.runner_id}.json",
            {
                "tasks": sorted(self.manifests),
                "gpu": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "pid": os.getpid(),
                "at": utc_now(),
                "running": sorted(self.running),
            },
        )

    def stop_heartbeat(self) -> None:
        (self.queue / "runners" / f"{self.runner_id}.json").unlink(missing_ok=True)

    # -- jobs ---------------------------------------------------------------------------------

    def claim(self, job_dir: Path) -> bool:
        try:
            fd = os.open(job_dir / "claim", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"runner_id": self.runner_id, "pid": os.getpid(), "at": utc_now()}, fh)
        return True

    def pending(self) -> list[Path]:
        out: list[Path] = []
        if not self.queue.is_dir():
            return out
        for job in sorted(self.queue.iterdir()):
            if job.name == "runners" or not (job / "job.json").is_file():
                continue
            if (job / "claim").exists() or (job / "cancel").exists():
                continue
            out.append(job)
        return out

    def start(self, job_dir: Path) -> None:
        try:
            spec = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        tid = (spec.get("task") or {}).get("id")
        if tid not in self.manifests or not self.claim(job_dir):
            return
        manifest, plugin_dir = self.manifests[tid]
        argv = [
            str(a).replace("{python}", sys.executable).replace("{job_dir}", str(job_dir))
            for a in manifest["runtime"]["command"]
        ]
        log = (job_dir / "task.log").open("ab")
        env = {**os.environ, "RW_JOB_DIR": str(job_dir)}
        proc = subprocess.Popen(argv, cwd=plugin_dir, stdout=log, stderr=subprocess.STDOUT, env=env)
        self.running[job_dir.name] = Running(job_dir, proc, log)
        print(f"[rw-runner] {tid} {job_dir.name} started (pid {proc.pid})", flush=True)

    def reap(self) -> None:
        for name, r in list(self.running.items()):
            code = r.proc.poll()
            if code is None:
                if (r.job_dir / "cancel").exists():
                    if r.term_at is None:
                        r.proc.send_signal(signal.SIGTERM)
                        r.term_at = time.monotonic()
                    elif time.monotonic() - r.term_at > KILL_AFTER_S:
                        r.proc.kill()
                continue
            r.log.close()
            write_json(
                r.job_dir / "exit.json",
                {"code": code, "at": utc_now(), "runner_id": self.runner_id},
            )
            print(f"[rw-runner] {name} exited with {code}", flush=True)
            del self.running[name]

    def step(self) -> None:
        self.heartbeat()
        self.reap()
        for job_dir in self.pending():
            if len(self.running) >= self.concurrency:
                break
            self.start(job_dir)

    def run(self, poll: float, once: bool) -> int:
        self.heartbeat(force=True)
        try:
            while True:
                self.step()
                if once and not self.running and not self.pending():
                    return 0
                time.sleep(poll)
        except KeyboardInterrupt:
            return 0
        finally:
            for r in self.running.values():
                r.proc.terminate()
            self.stop_heartbeat()


def _stop(_signum: int, _frame: Any) -> None:
    """SIGTERM behaves like Ctrl-C: stop children, remove the heartbeat."""
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Radiology Workbench host runner (TSK-11)")
    ap.add_argument(
        "--workspace", type=Path, required=True, help="WORKSPACE_ROOT as seen on the host"
    )
    ap.add_argument("--plugins", type=Path, required=True, help="PLUGINS_ROOT (external manifests)")
    ap.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between queue scans")
    ap.add_argument("--once", action="store_true", help="exit when the queue is empty (tests)")
    a = ap.parse_args(argv)
    only = {t.strip() for t in a.tasks.split(",") if t.strip()}
    runner = Runner(a.workspace.resolve(), a.plugins.resolve(), only, a.concurrency)
    if not runner.manifests:
        print(f"[rw-runner] no external manifests under {a.plugins}", file=sys.stderr)
        return 2
    print(f"[rw-runner] {runner.runner_id}: {', '.join(sorted(runner.manifests))}", flush=True)
    signal.signal(signal.SIGTERM, _stop)
    return runner.run(a.poll, a.once)


if __name__ == "__main__":
    sys.exit(main())
