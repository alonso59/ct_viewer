#!/usr/bin/env python3
"""Host runner for external tasks. Standard library only.

Runs on the host, inside the plugin's own environment (e.g. an activated conda env; R4), and
talks to the app only through files under `WORKSPACE_ROOT/queue/`:

    python scripts/rw-runner.py --workspace <WORKSPACE_HOST> --plugins <PLUGINS_ROOT> \
        [--tasks segment.nnunet] [--concurrency 1]

- Heartbeat `queue/runners/{runner_id}.json` `{tasks[], gpu, pid, at}` every 10 s.
- Claims a job by creating `queue/{job_id}/claim` with O_EXCL, then runs the manifest's
  `runtime.command` in the plugin folder (`{python}` = this interpreter, `{job_dir}` = the job
  folder); stdout/stderr go to `task.log`, the exit code to `exit.json`.
- A `cancel` file → SIGTERM, then SIGKILL after 30 s. A queued job with `pause` is never claimed.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.runner.preflight import inspect_host
from plugins.runner.supervised import Supervisor, isolated_argv

HEARTBEAT_S = 10.0
KILL_AFTER_S = 30.0


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def stopped(job_dir: Path) -> bool:
    """A `cancel` or supervised `pause` request: nothing new may start for this job."""
    return (job_dir / "cancel").exists() or (job_dir / "pause").exists()


def job_task_id(job_dir: Path) -> str | None:
    spec_path = job_dir / "job.json"
    if spec_path.is_symlink():
        return None
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(spec, dict) or not isinstance(spec.get("task"), dict):
        return None
    task_id = spec["task"].get("id")
    return task_id if isinstance(task_id, str) else None


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
        if not isinstance(tid, str) or runtime.get("type") != "external" or not runtime.get("command"):
            continue
        if only and tid not in only:
            continue
        out[tid] = (m, path.parent)
    return out


def checked_manifests(
    manifests: dict[str, tuple[dict[str, Any], Path]],
    supervisor: Supervisor | None = None,
    reports: dict[str, Any] | None = None,
) -> dict[str, tuple[dict[str, Any], Path]]:
    """Run optional plugin-owned startup checks before advertising a task."""
    available: dict[str, tuple[dict[str, Any], Path]] = {}
    for task_id, (manifest, plugin_dir) in manifests.items():
        if (manifest.get("resources") or {}).get("gpu") in {
            "required",
            "optional",
        } and supervisor is None:
            report = inspect_host()
            print(
                f"[rw-runner] {task_id}: containment not verified: " + ", ".join(report["blockers"]),
                file=sys.stderr,
            )
            continue
        check = plugin_dir / "check.py"
        if not check.is_file():
            available[task_id] = (manifest, plugin_dir)
            continue
        try:
            result = subprocess.run(
                isolated_argv(supervisor.python if supervisor else sys.executable, check),
                cwd=plugin_dir,
                env={
                    **supervisor.environment(),
                    "CUDA_VISIBLE_DEVICES": ",".join(supervisor.config.get("gpu_pool", [])),
                }
                if supervisor
                else os.environ,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"[rw-runner] {task_id}: startup check failed: {exc}", file=sys.stderr)
            continue
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()[-1000:]
            print(f"[rw-runner] {task_id}: startup check failed: {detail}", file=sys.stderr)
            continue
        detail = result.stdout.decode(errors="replace").strip()
        if reports is not None and detail:
            try:
                report = json.loads(detail.splitlines()[-1])
                if isinstance(report, dict):
                    reports[task_id] = report
            except (TypeError, ValueError):
                pass
        if detail:
            print(f"[rw-runner] {task_id}: {detail}", flush=True)
        available[task_id] = (manifest, plugin_dir)
    return available


@dataclass
class Running:
    job_dir: Path
    proc: subprocess.Popen[bytes]
    log: Any
    term_at: float | None = None


class Runner:
    def __init__(
        self,
        workspace: Path,
        plugins: Path,
        tasks: set[str],
        concurrency: int,
        deployment: Path | None = None,
    ) -> None:
        self.queue = workspace / "queue"
        self.plugins = plugins
        self.only = tasks
        self.concurrency = max(1, concurrency)
        self.runner_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.running: dict[str, Running] = {}
        self.last_beat = 0.0
        self.supervisor = Supervisor(deployment, workspace) if deployment else None
        if self.supervisor:
            self.supervisor.verify()
        self.reports: dict[str, Any] = {}
        self.manifests = checked_manifests(load_manifests(plugins, tasks), self.supervisor, self.reports)

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
                "model_catalog": self.reports.get("segment.nnunet", {}).get("model_catalog"),
                "running": sorted(
                    [
                        *self.running,
                        *(
                            [Path(self.supervisor.record["job"]).name]
                            if self.supervisor and self.supervisor.record
                            else []
                        ),
                    ]
                ),
                "execution": {
                    "backend": self.supervisor.config["backend"],
                    "limits": self.supervisor.config["limits"],
                    "allocation": self.supervisor.pool.identity(),
                    "write_network_confinement": True,
                    "device_exclusivity": False,
                    "logout_persistence": False,
                    "last_error": self.supervisor.last_error,
                    "inventory": self.supervisor.inventory_snapshot(),
                }
                if self.supervisor
                else None,
            },
        )

    def stop_heartbeat(self) -> None:
        (self.queue / "runners" / f"{self.runner_id}.json").unlink(missing_ok=True)

    def claim(self, job_dir: Path) -> bool:
        if job_dir.is_symlink() or job_dir.resolve().parent != self.queue.resolve() or stopped(job_dir):
            return False
        try:
            fd = os.open(job_dir / "claim", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
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
            if job.is_symlink() or job.name == "runners" or not (job / "job.json").is_file():
                continue
            if (job / "claim").exists() or stopped(job):
                continue
            if job_task_id(job) not in self.manifests:
                continue
            out.append(job)
        return out

    def start(self, job_dir: Path) -> None:
        if job_dir.is_symlink() or job_dir.resolve().parent != self.queue.resolve():
            return
        if (job_dir / "job.json").is_symlink() or stopped(job_dir):
            return
        tid = job_task_id(job_dir)
        if tid in self.manifests and self.supervisor is not None:
            manifest, plugin_dir = self.manifests[tid]
            if (manifest.get("resources") or {}).get("gpu") in {"required", "optional"}:
                try:
                    self.supervisor.start(job_dir, manifest, plugin_dir, self.claim)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    self.supervisor.last_error = str(exc)
                    if self.claim(job_dir):
                        write_json(job_dir / "result.json", {"status": "failed", "error": str(exc)})
                        write_json(job_dir / "exit.json", {"code": 125, "at": utc_now(), "cleanup_verified": True})
                return
        if tid is None or tid not in self.manifests or not self.claim(job_dir):
            return
        if (job_dir / "cancel").exists():
            write_json(
                job_dir / "exit.json",
                {"code": -signal.SIGTERM, "at": utc_now(), "runner_id": self.runner_id},
            )
            return
        manifest, plugin_dir = self.manifests[tid]
        argv = [
            str(a).replace("{python}", sys.executable).replace("{job_dir}", str(job_dir))
            for a in manifest["runtime"]["command"]
        ]
        log = None
        try:
            fd = os.open(job_dir / "task.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            log = os.fdopen(fd, "ab")
            env = {**os.environ, "RW_JOB_DIR": str(job_dir)}
            proc = subprocess.Popen(argv, cwd=plugin_dir, stdout=log, stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            if log is not None:
                log.close()
            write_json(
                job_dir / "exit.json",
                {
                    "code": 1,
                    "at": utc_now(),
                    "runner_id": self.runner_id,
                    "error": type(exc).__name__,
                },
            )
            return
        self.running[job_dir.name] = Running(job_dir, proc, log)
        print(f"[rw-runner] {tid} {job_dir.name} started (pid {proc.pid})", flush=True)

    def reap(self) -> None:
        if self.supervisor:
            self.supervisor.poll()
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
                if (
                    once
                    and not self.running
                    and not (self.supervisor and self.supervisor.record)
                    and not self.pending()
                ):
                    return 0
                time.sleep(poll)
        except KeyboardInterrupt:
            return 0
        finally:
            try:
                self.stop_tasks()
            finally:
                self.stop_heartbeat()

    def stop_tasks(self) -> None:
        if self.supervisor:
            self.supervisor.stop()
        for running in self.running.values():
            if running.proc.poll() is None:
                running.proc.terminate()
        deadline = time.monotonic() + KILL_AFTER_S
        while any(r.proc.poll() is None for r in self.running.values()) and time.monotonic() < deadline:
            time.sleep(0.05)
        for running in self.running.values():
            if running.proc.poll() is None:
                running.proc.kill()
            running.proc.wait(timeout=5)
        self.reap()


def _stop(_signum: int, _frame: Any) -> None:
    """SIGTERM behaves like Ctrl-C: stop children, remove the heartbeat."""
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Radiology Workbench host runner")
    ap.add_argument("--workspace", type=Path, help="WORKSPACE_ROOT as seen on the host")
    ap.add_argument("--plugins", type=Path, help="PLUGINS_ROOT (external manifests)")
    ap.add_argument("--deployment", type=Path, help="Private operator-owned deployment JSON")
    ap.add_argument(
        "--verify-host",
        action="store_true",
        help="With --preflight --deployment: run GPU-free effect checks",
    )
    ap.add_argument("--preflight", action="store_true", help="Report containment prerequisites; do not run jobs")
    ap.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--poll", type=float, default=1.0, help="seconds between queue scans")
    ap.add_argument("--once", action="store_true", help="exit when the queue is empty (tests)")
    a = ap.parse_args(argv)
    configured: Supervisor | None = None
    if a.deployment:
        try:
            configured = Supervisor(a.deployment, a.workspace.resolve() if a.workspace else None)
        except (OSError, ValueError) as exc:
            print(f"[rw-runner] invalid deployment: {exc}", file=sys.stderr)
            return 2
        a.workspace = configured.workspace
    if a.verify_host and not (a.preflight and configured):
        ap.error("--verify-host requires --preflight and --deployment")
    if a.preflight:
        try:
            report = configured.diagnostics(verify_host=a.verify_host) if configured else inspect_host()
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            report = {"ready": False, "error": str(exc)}
        print(json.dumps(report, indent=2))
        return 0 if report["ready"] else 2
    if a.workspace is None or a.plugins is None:
        ap.error("--workspace and --plugins are required unless --preflight is used")
    only = {t.strip() for t in a.tasks.split(",") if t.strip()}
    try:
        runner = Runner(a.workspace.resolve(), a.plugins.resolve(), only, a.concurrency, a.deployment)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"[rw-runner] deployment unavailable: {exc}", file=sys.stderr)
        return 2
    if not runner.manifests:
        print(f"[rw-runner] no external manifests under {a.plugins}", file=sys.stderr)
        return 2
    print(f"[rw-runner] {runner.runner_id}: {', '.join(sorted(runner.manifests))}", flush=True)
    signal.signal(signal.SIGTERM, _stop)
    return runner.run(a.poll, a.once)


if __name__ == "__main__":
    sys.exit(main())
